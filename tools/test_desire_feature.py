"""三尸自动合成的状态机与日志测试：不连微信，用假 transport 驱动。"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from package.daily_tasks.scheduler import ExecutionUncertain, RetryableTaskError
from package.plugin_manager.features import desire as mod


class State:
    closing = False
    installed = True
    stop_operation = False


class Panel:
    def __init__(self):
        self.status = ''
        self.stats = ''
        self.message = ''
        self.running = False
        self.report = None

    def set_ready(self, value): pass
    def set_running(self, value): self.running = bool(value)
    def set_status(self, text): self.status = text
    def set_stats(self, text): self.stats = text
    def set_message(self, text): self.message = text
    def set_report_path(self, path): self.report = path


class Store:
    def __init__(self, config): self.config = config
    def snapshot(self): return {'desire': self.config}


class Transport:
    """按脚本返回回执；合成会真的扣减库存，成功后往上一档加一件。"""

    def __init__(self, counts, outcomes):
        self.counts = dict(counts)
        self.outcomes = list(outcomes)
        self.calls = []
        self.raises = []
        self.on_compose = None
        self.feature = None

    def groups(self):
        return [{'type': t, 'quality': q, 'count': c, 'distinct': c, 'pairs': c // 2}
                for (t, q), c in sorted(self.counts.items()) if c > 0]

    async def call(self, op, payload=None):
        self.calls.append((op, payload))
        if op == 'desire_bag_stats':
            return {'confirmed': True, 'groups': self.groups(), 'rates': [],
                    'qualityNames': {1: '白', 2: '蓝', 3: '紫'}, 'typeCodes': {}}
        if op in ('desire_compose_open', 'desire_compose_close', 'home'):
            return {'confirmed': True}
        if op == 'desire_compose_probe':
            return {'confirmed': True}
        if op == 'desire_compose_once':
            if self.raises:
                raise self.raises.pop(0)
            t, q = payload['type'], payload['quality']
            self.counts[(t, q)] = self.counts.get((t, q), 0) - 2
            won = bool(self.outcomes.pop(0)) if self.outcomes else False
            if won:
                self.counts[(t, q + 1)] = self.counts.get((t, q + 1), 0) + 1
            if self.on_compose:
                self.on_compose(self.feature)
            return {'confirmed': True, 'success': won, 'type': t, 'quality': q,
                    'itemIds': [101, 101], 'sameUuid': False, 'ratio': 30.0,
                    'returned': 1, 'items': 1, 'groups': self.groups()}
        raise AssertionError('未知操作 ' + op)

    def composed(self):
        return [p['quality'] for op, p in self.calls if op == 'desire_compose_once' and p]


def config(**overrides):
    base = {'kind': 1, 'start_quality': 1, 'max_material_quality': 3,
            'fail_limits': {'1': 2, '2': 2, '3': 2}, 'max_attempts': 50, 'expected_rate': 30.0}
    base.update(overrides)
    return base


@pytest.fixture
def feature(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'LOG_PATH', tmp_path / 'desire_compose.csv')
    monkeypatch.setattr(mod, 'REPORT_DIR', tmp_path)
    def make(counts, outcomes, **cfg):
        transport = Transport(counts, outcomes)
        f = mod.DesireFeature(transport, State(), Panel(), Store(config(**cfg)))
        transport.feature = f
        return f, transport
    return make


def rows(path):
    if not Path(path).exists():
        return []
    with Path(path).open(encoding='utf-8', newline='') as file:
        return list(csv.DictReader(file))


def test_escalates_after_consecutive_failures(feature):
    f, t = feature({(4, 1): 10}, [False, False])
    asyncio.run(f.run_batch())
    assert t.composed()[0] == 1, '从最低档起步'
    assert len(t.composed()) >= 2, '连败到上限后升档，之后还要回最低档继续'


def test_success_resets_the_streak(feature):
    f, t = feature({(4, 1): 10}, [False, True, False, True, False, False])
    asyncio.run(f.run_batch())
    assert t.composed()[:4] == [1, 1, 1, 1], '失败后成功会清零连败，留在同一品质档'


def test_skips_quality_without_two_items(feature):
    f, t = feature({(4, 1): 1, (4, 2): 4}, [False, False])
    asyncio.run(f.run_batch())
    assert t.composed() == [2, 2], '不足两件直接跳到下一档'


def test_material_ceiling_stops_the_batch(feature):
    f, t = feature({(4, 1): 0, (4, 2): 10, (4, 3): 10}, [False, False], max_material_quality=2)
    asyncio.run(f.run_batch())
    assert 3 not in t.composed(), '超过最高材料品质就不该再合'


def test_stop_halts_the_batch(feature):
    f, t = feature({(4, 1): 10}, [False] * 10)
    def stop_after_two(_feature):
        if len(t.composed()) >= 2:
            _feature._stop = True
    t.on_compose = stop_after_two
    asyncio.run(f.run_batch())
    assert len(t.composed()) == 2
    assert '已请求停止' in f.panel.status


def test_uncertain_receipt_aborts_immediately(feature):
    f, t = feature({(4, 1): 10}, [True] * 10)
    t.raises = [ExecutionUncertain('回执缺失')]
    asyncio.run(f.run_batch())
    assert len(t.composed()) == 1, '结果未知必须立刻停，绝不重试或重放'
    assert '结果未知' in f.panel.status


def test_repeated_rejections_abort_without_logging(feature, tmp_path):
    f, t = feature({(4, 1): 10}, [True] * 10)
    t.raises = [RetryableTaskError('未获准')] * 3
    asyncio.run(f.run_batch())
    assert len(t.composed()) == 3
    assert rows(tmp_path / 'desire_compose.csv') == [], '被拒绝的操作没有发生，不该写日志'
    assert '未获准' in f.panel.status


def test_seq_is_global_and_batch_increments(feature, tmp_path):
    f, t = feature({(4, 1): 2}, [True])
    asyncio.run(f.run_batch())
    f2, t2 = feature({(4, 1): 2}, [True])
    asyncio.run(f2.run_batch())
    data = rows(tmp_path / 'desire_compose.csv')
    assert [r['seq'] for r in data] == ['0', '1'], '次数序号全局累计，跨批次不归零'
    assert [r['batch'] for r in data] == ['0', '1'], '每开始一批批次号 +1'
    assert data[0]['quality_name'] == '白'
    assert data[0]['success'] == '1'


def test_report_html_has_no_placeholder(feature, tmp_path):
    f, t = feature({(4, 1): 10}, [True, False, False, True])
    asyncio.run(f.run_batch())
    f.write_report()
    assert f.panel.report is not None
    html = Path(f.panel.report).read_text(encoding='utf-8')
    assert '__PAYLOAD__' not in html
    assert '连续失败次数分布' in html


def test_failure_gaps_counts_failures_between_successes():
    from package.plugin_manager.desire_report import failure_gaps
    rows = [{'ok': 0}, {'ok': 0}, {'ok': 1}, {'ok': 0}, {'ok': 1}, {'ok': 0}, {'ok': 0}]
    gaps, trailing = failure_gaps(rows)
    assert gaps == [2, 1], '每次成功结束一段，段内是这段之前的失败次数'
    assert trailing == 2, '末尾未结束的连败单独返回，不进分布'


def test_summary_rate_and_gaps():
    from package.plugin_manager.desire_report import summarize
    rows = [{'ok': 1}, {'ok': 0}, {'ok': 0}, {'ok': 1}]
    s = summarize(rows)
    assert s['n'] == 4 and s['ok'] == 2 and s['rate'] == 0.5
    assert s['gaps'] == 2 and s['max_gap'] == 2 and s['trailing'] == 0


def test_daily_automation_stop_flag_does_not_halt_a_manual_batch(feature):
    """日常自动化总开关默认关闭时 state.stop_operation 是 True，不能把手动批次也停掉。"""
    f, t = feature({(4, 1): 4}, [True])
    f.state.stop_operation = True
    asyncio.run(f.run_batch())
    assert len(t.composed()) >= 1, '手动发起的批次不受日常调度器的停止信号影响'


def test_nothing_to_compose_never_opens_the_ui(feature):
    f, t = feature({(4, 1): 1}, [True])
    asyncio.run(f.run_batch())
    assert not any(op == 'desire_compose_open' for op, _ in t.calls), '没得合就不该进三尸界面'
    assert '没有可合成的三尸' in f.panel.status


def test_failed_compose_does_not_bounce_home_mid_batch(feature):
    """合成失败时不能自动回主界面——那会把整批打断，表现就是"进一下又退回来"。"""
    f, t = feature({(4, 1): 6}, [True, True])
    t.raises = [RetryableTaskError('未获准')]
    asyncio.run(f.run_batch())
    assert not any(op == 'home' for op, _ in t.calls), '合成失败不该自动 home'
    assert len(t.composed()) >= 2, '一次未获准应换档继续，而不是整批中止'


def _types(t):
    return [p['type'] for op, p in t.calls if op == 'desire_compose_once' and p]


def test_heart_is_used_on_the_last_chance_of_a_tier(feature):
    """本档最后一次机会时，有心就用心；其余时候先用凡。kinds[0]=心(1)，kinds[1]=凡(4)。"""
    f, t = feature({(1, 1): 4, (4, 1): 4}, [False, False])
    asyncio.run(f.run_batch())
    assert _types(t)[0] == 4, '非最后机会先用凡'
    assert _types(t)[1] == 1, '最后一次机会改用核心'


def test_heart_is_used_at_the_last_chance_when_ordinary_runs_out(feature):
    f, t = feature({(1, 1): 4}, [False, False])
    asyncio.run(f.run_batch())
    assert _types(t)[0] == 1, '凡不够时才在本档最后一次机会动心'


def test_poll_does_not_query_the_bag_every_tick(feature):
    """库存不按秒轮询：就绪后只拉一次，免得日志每半分钟刷一行。"""
    f, t = feature({(4, 1): 4}, [True])
    for _ in range(5):
        asyncio.run(f.poll({}))
    assert sum(1 for op, _ in t.calls if op == 'desire_bag_stats') == 1


def test_poll_refreshes_again_after_the_session_drops(feature):
    f, t = feature({(4, 1): 4}, [True])
    asyncio.run(f.poll({}))
    f.state.installed = False
    asyncio.run(f.poll({}))
    f.state.installed = True
    asyncio.run(f.poll({}))
    assert sum(1 for op, _ in t.calls if op == 'desire_bag_stats') == 2, '新会话要重新拉一次'
