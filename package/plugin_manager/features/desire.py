"""三尸自动合成：按品质阶梯做二合一，每次合成落一行日志，可生成离线 HTML 报告。

策略（每次「开始」跑一批）：
  从起始品质档开始，用该品质的三尸两两合成；每个品质档有独立的「连续失败上限」，
  连续失败达到上限就把材料品质升一档；某品质可用数量不足 2 件就直接跳到下一档；
  材料品质超过「最高材料品质」就停止整批。

合成不可逆，所以回执规则沿用日常任务那套：拿不到 `confirmed` 且 `success` 明确的回执，
一律按「结果未知」终止整批，绝不重试或重放。
"""

from __future__ import annotations

import asyncio
import csv
import logging
from datetime import datetime
from pathlib import Path

from package.daily_tasks.scheduler import ExecutionUncertain, RetryableTaskError

from ..resident import ResidentGame

from ..desire_report import write_outputs

LOG = logging.getLogger('plugin_manager')

REPORT_DIR = Path('logs')
LOG_PATH = REPORT_DIR / 'desire_compose.csv'
COLUMNS = ('seq', 'batch', 'time', 'type', 'quality', 'quality_name', 'success', 'ratio', 'same_uuid')

# 种类（贪/嗔/痴）→ DesireType 的组内两个子类型；canDoCompose 要求 type 完全相同，心与凡不能互合。
KIND_TYPES = {1: (1, 4), 2: (2, 5), 3: (3, 6)}
KIND_NAMES = {1: '贪', 2: '嗔', 3: '痴'}
TYPE_NAMES = {1: '贪·心', 2: '嗔·心', 3: '痴·心', 4: '贪·凡', 5: '嗔·凡', 6: '痴·凡'}
# 仅在拿不到游戏内名称时兜底；日志里写的是运行时从 roleHelper.getRareName 取到的真名。
QUALITY_FALLBACK = {1: '白', 2: '蓝', 3: '紫', 4: '橙', 5: '红', 6: '黑金', 7: '幻彩', 8: '轮回'}

MAX_SOFT_ERRORS = 3


def _receipt(value, action: str) -> dict:
    """只认「明确回执」：合成会吃掉三尸，没有明确结果就不能继续，更不能重放。"""
    if not isinstance(value, dict) or value.get('confirmed') is not True or type(value.get('success')) is not bool:
        raise ExecutionUncertain(f'{action}未获得明确回执，禁止重复调用')
    return value


class DesireFeature:
    def __init__(self, transport, state, panel, store):
        self.transport = transport
        self.game = ResidentGame(transport)
        self.state = state
        self.panel = panel
        self.store = store
        self._running = False
        self._stop = False
        self._job = None
        self._seq = 0
        self._batch = 0
        self._quality_names = dict(QUALITY_FALLBACK)
        self._report_path = None
        self._stats_loaded = False

    @property
    def busy(self) -> bool:
        return self._running

    @property
    def _halted(self) -> bool:
        """只看本功能的停止按钮和关窗。

        不能用 state.stop_operation：那是日常自动化调度器的停止信号，
        日常总开关默认关闭时它是 True，会把手动发起的批次立刻判定成该收尾。
        """
        return self._stop or bool(self.state.closing)

    # ── 面板操作 ──

    def request(self, op: str, args: dict | None = None) -> None:
        if op == 'stop':
            self._stop = True
            self.panel.set_message('已请求停止，当前这一次合成结束后收尾')
            return
        if self.state.closing or not self.state.installed:
            self.panel.set_message('三尸合成需要游戏与插件就绪')
            return
        if op == 'start' and self._running:
            self.panel.set_message('已经在合成中')
            return
        asyncio.create_task(self.handle(op, args or {}))

    async def handle(self, op: str, args: dict) -> None:
        try:
            if op == 'start':
                await self.run_batch()
            elif op == 'report':
                self.write_report()
            elif op == 'probe':
                # 先把三尸合成页打开，否则诊断只能看到"界面未打开"，看不出东西。
                kind = int((self.store.snapshot().get('desire') or {}).get('kind') or 1)
                try:
                    await self.game.desire_compose_open(kind)
                except Exception as exc:
                    LOG.warning('诊断前打开三尸界面未成功：%s', exc)
                await self.refresh_stats()
                await self._diagnose()
            elif op == 'refresh':
                await self.refresh_stats()
        except Exception as exc:
            LOG.error('三尸合成操作失败：%s', exc)
            self.panel.set_message(f'操作失败：{exc}')

    async def wait_operation(self) -> None:
        if self._job is not None and not self._job.done():
            await asyncio.shield(self._job)

    # ── 每秒轮询：只更新就绪态，批次由按钮驱动 ──

    async def poll(self, config: dict) -> None:
        """只维护就绪态；库存不按秒轮询，就绪后拉一次就够（日志和CDP都省下来）。"""
        ready = self.state.installed and not self.state.closing
        self.panel.set_ready(ready and not self._running)
        if not ready or self._running:
            self._stats_loaded = False
            return
        if self._stats_loaded:
            return
        self._stats_loaded = True
        await self.refresh_stats()

    async def refresh_stats(self) -> None:
        try:
            stats = await self.game.desire_bag_stats()
        except Exception as exc:
            LOG.debug('三尸背包统计未取到：%s', exc)
            return
        if not isinstance(stats, dict):
            return
        names = stats.get('qualityNames') or {}
        for key, value in names.items():
            try:
                self._quality_names[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
        self.panel.set_stats(self._stock_text(stats))

    def _stock_text(self, stats: dict) -> str:
        groups = stats.get('groups') or []
        if not groups:
            return '背包里没有可用于合成的三尸'
        lines = ['可合成库存（已排除锁定与已镶嵌）：']
        for row in groups:
            type_id = int(row.get('type') or 0)
            quality = int(row.get('quality') or 0)
            lines.append(f"  {TYPE_NAMES.get(type_id, f'种类{type_id}')} · "
                         f"{self._quality_names.get(quality, f'品质{quality}')}："
                         f"{int(row.get('count') or 0)} 件（可配 {int(row.get('pairs') or 0)} 对）")
        excluded = stats.get('excluded') or {}
        if any(excluded.values()):
            lines.append('')
            lines.append(f"被排除：锁定 {excluded.get('locked', 0)} 件 · "
                         f"已镶嵌在方案里 {excluded.get('embedded', 0)} 件 · "
                         f"品质不可合 {excluded.get('uncomposable', 0)} 件")
            lines.append('（起点从最低的、凑得出一对的品质开始；如果白色被排除光了就会从蓝色起步）')
        return '\n'.join(lines)

    def quality_name(self, quality: int) -> str:
        return self._quality_names.get(int(quality), f'品质{quality}')

    # ── 日志 ──

    def _load_counters(self) -> tuple[int, int]:
        """seq 全局累计、batch 每次 +1；两者都从已有日志反推，重启或删配置都不会漂移。"""
        if not LOG_PATH.exists():
            return 0, 0
        seq = batch = 0
        try:
            with LOG_PATH.open(encoding='utf-8', newline='') as file:
                for row in csv.DictReader(file):
                    try:
                        seq = max(seq, int(row.get('seq') or 0) + 1)
                        batch = max(batch, int(row.get('batch') or 0) + 1)
                    except (TypeError, ValueError):
                        continue
        except OSError as exc:
            LOG.warning('三尸合成日志读取失败，按空日志处理：%s', exc)
        return seq, batch

    def _append(self, record: dict) -> None:
        fresh = not LOG_PATH.exists()
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open('a', encoding='utf-8', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=COLUMNS)
                if fresh:
                    writer.writeheader()
                writer.writerow({key: record.get(key, '') for key in COLUMNS})
        except OSError as exc:
            LOG.error('三尸合成日志写入失败：%s', exc)
            self.panel.set_message(f'日志写入失败：{exc}')

    # ── 批次 ──

    async def run_batch(self) -> None:
        self._running = True
        self._stop = False
        self.panel.set_running(True)
        self._job = asyncio.current_task()
        self._seq, self._batch = self._load_counters()
        config = (self.store.snapshot().get('desire') or {})
        kinds = KIND_TYPES.get(int(config.get('kind') or 1), KIND_TYPES[1])
        start = int(config.get('start_quality') or 1)
        ceiling = int(config.get('max_material_quality') or 4)
        limits = {int(k): int(v) for k, v in (config.get('fail_limits') or {}).items()}
        fuse = int(config.get('max_attempts') or 200)
        done = success = 0
        total_streak = 0
        threshold = int(config.get("success_after_failures", 20))
        pause_failures = None
        soft_errors = 0
        halt_reason = ''
        try:
            if not kinds:
                self.panel.set_status('未选择三尸种类')
                return
            stats = await self._inventory()
            if stats is None:
                return
            groups = list(stats.get('groups') or [])
            # 没得合就别开界面：开了又立刻关回去，看起来像点错了一样。
            if not self._anything_to_compose(groups, kinds, start, ceiling):
                self.panel.set_status('没有可合成的三尸：' + self._nothing_reason(groups, kinds, start, ceiling))
                return
            await self.game.desire_compose_open(int(config.get('kind') or 1))
            # kinds = (心, 凡)。心更值钱：先用凡，只有本档最后一次机会才动心。
            heart, ordinary = kinds
            while True:
                if self._halted:
                    break
                if done >= fuse:
                    self.panel.set_message(f'已达单批次上限 {fuse} 次，本批提前结束')
                    break
                # 每轮都从最低的、凑得出一对的档位开始：升档后成功一次、或撞到品质上限，都回到这里重来。
                quality = self._lowest_available(groups, kinds, start, ceiling)
                if quality is None:
                    break
                streak = 0
                escalated = False
                before_round = done
                while quality <= ceiling:
                    if self._halted:
                        break
                    if done >= fuse:
                        self.panel.set_message(f'已达单批次上限 {fuse} 次，本批提前结束')
                        break
                    limit = limits.get(quality, 4)
                    last_chance = streak >= limit - 1
                    # 本档最后一次机会时，有心就用心；其余时候先用凡。
                    if last_chance and self._available(groups, heart, quality) >= 2:
                        type_id = heart
                    elif self._available(groups, ordinary, quality) >= 2:
                        type_id = ordinary
                    elif self._available(groups, heart, quality) >= 2:
                        # 凡不够但心还有：直接跳到最后一次机会，别把心白白留到升档
                        streak = limit - 1
                        continue
                    else:
                        quality += 1
                        streak = 0
                        continue
                    used = quality          # 升档发生在记日志之前，先把本次真正用的品质存下来
                    self.panel.set_status(self._progress_text(type_id, quality, streak, limit, done, success) + f" · 距上次成功连续失败 {total_streak} 次")
                    try:
                        # 不走 ResidentGame._call：它失败后会自动 home()，把整批打断。
                        result = _receipt(await self.transport.call(
                            'desire_compose_once', {'type': type_id, 'quality': quality}), '三尸合成')
                    except ExecutionUncertain as exc:
                        # 合成不可逆：结果未知立刻停，不重试也不继续，但先把现场抓出来。
                        self._stop = True
                        halt_reason = f'结果未知，已停止：{exc}'
                        self.panel.set_message(halt_reason)
                        LOG.error('三尸合成结果未知，终止本批：%s', exc)
                        await self._diagnose()
                        break
                    except RetryableTaskError as exc:
                        soft_errors += 1
                        LOG.warning('三尸合成未获准（第%d次）：%s', soft_errors, exc)
                        if soft_errors == 1:
                            self.panel.set_message(f'合成未获准：{exc}')
                            await self._diagnose()
                        if soft_errors >= MAX_SOFT_ERRORS:
                            self._stop = True
                            halt_reason = f'连续{soft_errors}次未获准，停止本批：{exc}'
                            break
                        # 重新开一次合成页（已开着就立刻返回，不会回主界面）。
                        try:
                            await self.game.desire_compose_open(int(config.get('kind') or 1))
                        except Exception as open_exc:
                            LOG.warning('合成页重开失败：%s', open_exc)
                        groups = await self._regroup()
                        continue
                    soft_errors = 0
                    done += 1
                    won = bool(result.get('success'))
                    previous_failures = total_streak
                    total_streak = 0 if won else total_streak + 1
                    break_round = False
                    if won:
                        success += 1
                        streak = 0
                        break_round = escalated
                        if threshold > 0 and previous_failures >= threshold:
                            pause_failures = previous_failures
                            self._stop = True
                            halt_reason = f'连败 {previous_failures} 次后成功，已停止；距上次成功连续失败 0 次，可考虑手工进行高阶三尸合成'
                            LOG.info('三尸合成连败检测触发：批次=%s，连败=%s，阈值=%s',self._batch,previous_failures,threshold)
                    else:
                        streak += 1
                        if streak >= limit:
                            quality += 1
                            streak = 0
                            escalated = True
                            break_round = quality > ceiling
                    self._append({'seq': self._seq, 'batch': self._batch,
                                  'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                  'type': type_id, 'quality': used,
                                  'quality_name': self.quality_name(used),
                                  'success': 1 if won else 0,
                                  'ratio': result.get('ratio') if result.get('ratio') is not None else '',
                                  'same_uuid': 1 if result.get('sameUuid') else 0})
                    self._seq += 1
                    self.panel.set_status(self._progress_text(type_id, used, streak, limit, done, success) + f" · 距上次成功连续失败 {total_streak} 次")
                    if pause_failures is not None:
                        break
                    groups = list(result.get('groups') or []) or await self._regroup()
                    if break_round:
                        break
                if done == before_round:
                    break               # 一整轮一次都没合成，说明没有可合的材料了
            # 异常终止的原因要留在面板上，不能被"本批结束"这句盖掉。
            self.panel.set_status(halt_reason or (f'本批结束：合成 {done} 次，成功 {success} 次'
                                                  + f' · 距上次成功连续失败 {total_streak} 次'
                                                  + ('（已请求停止）' if self._stop else '')))
            if halt_reason:
                # 出错时别把界面关回去：留着现场，用户可以直接点「诊断现场」或自己看一眼。
                self.panel.set_message(halt_reason + '；三尸界面保持打开，可点「诊断现场」看实况')
            else:
                try:
                    await self.game.desire_compose_close()
                except Exception as exc:
                    LOG.warning('三尸合成结束后返回主界面未成功：%s', exc)
            await self.refresh_stats()
            if pause_failures is not None:
                self.panel.show_success_pause(pause_failures)
        finally:
            self._running = False
            self.panel.set_running(False)
            self._job = None

    async def _inventory(self) -> dict | None:
        try:
            stats = await self.game.desire_bag_stats()
        except (ExecutionUncertain, RetryableTaskError) as exc:
            self.panel.set_status(f'背包统计未取到，未开始合成：{exc}')
            return None
        if not isinstance(stats, dict):
            self.panel.set_status('背包统计返回异常，未开始合成')
            return None
        names = stats.get('qualityNames') or {}
        for key, value in names.items():
            try:
                self._quality_names[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
        return stats

    async def _diagnose(self) -> None:
        """第一次失败就把现场抓出来：面板和日志都能直接看出断在哪一环。"""
        try:
            probe = await self.game.desire_compose_probe()
        except Exception as exc:
            LOG.error('三尸合成诊断失败：%s', exc)
            return
        LOG.error('三尸合成诊断：%s', probe)
        self.panel.set_stats('合成失败现场：\n' + self._probe_text(probe))

    @staticmethod
    def _probe_text(probe) -> str:
        if not isinstance(probe, dict):
            return str(probe)
        lines = []
        cfg = probe.get('cfg') or {}
        lines.append(f"界面配置  三尸页={cfg.get('DesireUI')} 确认框={cfg.get('CommonConfirm')} 奖励页={cfg.get('Congrats')}")
        defs = probe.get('defs') or {}
        lines.append(f"协议入口  DesireService={defs.get('DesireService')} composeGem={defs.get('composeGem')}")
        lines.append(f"三尸模块  {probe.get('module')}{('（' + str(probe.get('moduleError')) + '）') if probe.get('moduleError') else ''}")
        api = probe.get('moduleApi')
        if api:
            lines.append('  接口    ' + '  '.join(f'{k}={v}' for k, v in api.items()))
        bag = probe.get('bag') or {}
        lines.append(f"背包      present={bag.get('present')} size={bag.get('size')}")
        if probe.get('groupsError'):
            lines.append(f"  统计失败：{probe['groupsError']}")
        else:
            lines.append(f"  可合成分组 {len(probe.get('groups') or [])} 项")
        page = probe.get('page')
        if page is None:
            lines.append(f"三尸页    未打开（screenOpen={probe.get('screenOpen')}）")
        else:
            lines.append(f"合成页    present={page.get('present')} hasComposeAll={page.get('hasComposeAll')} "
                         f"当前页签={page.get('curSelectedIndex')} btnTabGroup={page.get('hasTabGroup')}")
            for name, state in (page.get('buttons') or {}).items():
                lines.append(f"  按钮 {name}  " + ('无' if state is None else
                             f"active={state.get('active')} interactable={state.get('interactable')} "
                             f"enabled={state.get('enabled')} clickable={state.get('clickable')}"))
            lines.append(f"  槽位 {page.get('slots')}")
        if 'confirmOpen' in probe:
            lines.append(f"  确认框打开={probe.get('confirmOpen')}")
        return '\n'.join(lines)

    async def _regroup(self) -> list:
        try:
            stats = await self.game.desire_bag_stats()
        except Exception:
            return []
        return list((stats or {}).get('groups') or [])

    @staticmethod
    def _available(groups: list, type_id: int, quality: int) -> int:
        for row in groups:
            if int(row.get('type') or 0) == type_id and int(row.get('quality') or 0) == quality:
                return int(row.get('count') or 0)
        return 0

    def _lowest_available(self, groups: list, kinds: tuple, start: int, ceiling: int):
        """最低的、凑得出一对的品质档；都凑不出就返回 None（该收尾了）。"""
        for quality in range(start, ceiling + 1):
            for type_id in kinds:
                if self._available(groups, type_id, quality) >= 2:
                    return quality
        return None

    def _anything_to_compose(self, groups: list, kinds: tuple, start: int, ceiling: int) -> bool:
        return self._lowest_available(groups, kinds, start, ceiling) is not None

    def _nothing_reason(self, groups: list, kinds: tuple, start: int, ceiling: int) -> str:
        """说清楚是压根没有，还是都在锁定／镶嵌里，还是数量凑不出一对。"""
        owned = [row for row in groups if int(row.get('type') or 0) in kinds
                 and start <= int(row.get('quality') or 0) <= ceiling]
        if not owned:
            return (f'所选种类在品质 {self.quality_name(start)}～{self.quality_name(ceiling)} 之间'
                    '没有任何未锁定、未镶嵌且可合成的三尸')
        detail = '、'.join(f"{TYPE_NAMES.get(int(r.get('type') or 0), '?')}·"
                          f"{self.quality_name(int(r.get('quality') or 0))} "
                          f"{int(r.get('count') or 0)} 件" for r in owned)
        return f'每个品质都要两件才够合，当前只有：{detail}'

    def _progress_text(self, type_id: int, quality: int, streak: int, limit: int,
                       done: int, success: int) -> str:
        return (f'合成中 · 第{self._batch}批 · {TYPE_NAMES.get(type_id, f"种类{type_id}")} · '
                f'{self.quality_name(quality)} · 连续失败 {streak}/{limit} · '
                f'本批 {done} 次（成功 {success}）')

    # ── 报告 ──

    def write_report(self) -> None:
        try:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            config = (self.store.snapshot().get('desire') or {})
            written = write_outputs(LOG_PATH, REPORT_DIR, stamp,
                                    expected_rate=float(config.get('expected_rate') or 30.0))
            html = next((p for p in written if p.suffix == '.html'), None)
            self._report_path = html
            self.panel.set_report_path(html)
            LOG.info('三尸合成报告已生成：%s', html)
        except (OSError, ValueError) as exc:
            LOG.error('三尸合成报告写入失败：%s', exc)
            self.panel.set_message(f'报告写入失败：{exc}')
