"""扫荡处理器与常驻桥集成测试，不连接真实游戏。"""
import asyncio
import copy
import importlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from package.daily_tasks.config import load_config
from package.daily_tasks.scheduler import ExecutionUncertain, RetryableTaskError, Scheduler, TaskContext


def energy_module():
    try:
        return importlib.import_module("package.daily_tasks.energy")
    except ModuleNotFoundError:
        pytest.fail("energy扫荡处理器尚未接入")


def context(stop=lambda: False):
    return TaskContext(load_config().tasks["energy"], None, stop)


class FakeGame:
    def __init__(self, energy=90, maximum=100, limits=99):
        self.energy, self.maximum, self.limits = energy, maximum, limits
        self.selection = {"sanshi": 0, "artifact": 201, "plan": 1, "eye": 10}
        self.original = self.snapshot()
        self.costs = [10, 20, 30]
        self.num = 0
        self.calls = []
        self.journal = None
        self.failure = None
        self.on_sweep = None
        self.last_recovery = 1000.0
        self.server_now = 1100.0

    def snapshot(self):
        return {"role_id": 12345, "selection": copy.deepcopy(self.selection), "slots": [10, 11, 0, 0], "formation": 1}

    @asynccontextmanager
    async def transaction(self, journal):
        yield

    async def inspect(self):
        self.calls.append(("inspect", None))
        return {"energy": self.energy, "maximum": self.maximum, "safe": True,
                "last_recovery": self.last_recovery, "server_now": self.server_now}

    async def catalog(self, name):
        self.calls.append(("catalog", name))
        return {"sanshi": [0, 1], "magic": [{"artifact": 201, "plan": 1}, {"artifact": 201, "plan": 2}], "eye": 11}

    async def optimize(self):
        """驻留脚本按数据选方案：这里模拟选到贪财最高的组合并切过去。"""
        self.calls.append(("optimize", None))
        if self.failure == "optimize":
            raise RetryableTaskError("方案页面不可用")
        choice = {"sanshi": 1, "artifact": 201, "plan": 2}
        self.selection.update(choice)
        return {"choice": dict(choice), "gold": 100 * choice["sanshi"] + 10 * choice["plan"],
                "scores": [], "measured": []}

    async def capture(self):
        return self.snapshot()

    async def set_eye(self, eye):
        assert self.journal is None or self.journal.exists()
        self.calls.append(("eye", eye))
        self.selection["eye"] = eye

    async def select(self, choice):
        assert self.journal is None or self.journal.exists()
        self.calls.append(("select", copy.deepcopy(choice)))
        if self.failure == "select":
            raise RetryableTaskError("服务器明确拒绝")
        self.selection.update(choice)
        return 100 * self.selection["sanshi"] + 10 * self.selection["plan"]

    async def home(self):
        self.calls.append(("home", None))

    async def quote(self):
        return {"energy": self.energy, "sweep_num": self.num, "cost": self.costs[min(self.num, len(self.costs)-1)], "allowed": self.num < self.limits}

    async def sweep(self):
        self.calls.append(("sweep", copy.deepcopy(self.selection)))
        if self.failure == "uncertain":
            raise ExecutionUncertain("响应丢失")
        if self.failure == "reject":
            raise RetryableTaskError("服务器次数不足")
        if self.failure == "no_progress":
            return {"energy": self.energy, "sweep_num": self.num}
        cost = self.costs[min(self.num, len(self.costs)-1)]
        self.energy -= cost
        self.num += 1
        if self.on_sweep:
            self.on_sweep()
        return {"energy": self.energy, "sweep_num": self.num}

    async def restore(self, original):
        self.calls.append(("restore", original))
        if self.failure == "restore":
            raise ExecutionUncertain("恢复失败")
        self.selection = copy.deepcopy(original["selection"])
        return self.snapshot()


@pytest.mark.parametrize("value", [0, 89])
def test_below_threshold_never_switches_or_spends(tmp_path, value):
    async def run():
        m = energy_module()
        game = FakeGame(energy=value)
        path = tmp_path / "restore.json"
        result = await m.EnergyTask(game, path)(context())
        assert result.status == "waiting"
        assert game.calls == [("inspect", None)]
        assert not path.exists()
    asyncio.run(run())


def test_below_threshold_waits_until_energy_recovers(tmp_path):
    async def run():
        m = energy_module()
        game = FakeGame(energy=30)  # 上限100，阈值90 → 还差60点
        result = await m.EnergyTask(game, tmp_path / "restore.json")(context())
        assert result.status == "waiting"
        # 每点420秒 × 60点 = 25200秒，受"一次叫醒"上限(3600秒)约束。
        assert result.next_delay_seconds == 3600.0
        assert "预计" in result.message
        assert game.calls == [("inspect", None)]
    asyncio.run(run())


def test_threshold_wait_uses_recovery_timestamp(tmp_path, caplog):
    async def run():
        import logging
        m = energy_module()
        game = FakeGame(energy=88)
        game.last_recovery, game.server_now = 1000.0, 1100.0  # 上次恢复在100秒前
        with caplog.at_level(logging.INFO, logger="plugin_manager.energy"):
            result = await m.EnergyTask(game, tmp_path / "restore.json")(context())
        # 还差2点：上次恢复时刻1000 + 420×2 = 1840，现在1100 → 740秒
        assert result.next_delay_seconds == 740.0 + 5.0
        assert "校准" in caplog.text
    asyncio.run(run())


def test_missing_recovery_data_falls_back_to_interval(tmp_path):
    async def run():
        m = energy_module()
        game = FakeGame(energy=30)
        game.last_recovery, game.server_now = None, None
        result = await m.EnergyTask(game, tmp_path / "restore.json")(context())
        # 拿不到服务器时间也能按"缺几点×间隔"估算
        assert result.next_delay_seconds == 3600.0
    asyncio.run(run())


def test_highest_existing_combo_then_spend_and_restore(tmp_path):
    async def run():
        m = energy_module()
        game = FakeGame()
        path = tmp_path / "restore.json"
        game.journal = path
        result = await m.EnergyTask(game, path)(context())
        assert result.status == "success"
        sweeps = [v for name, v in game.calls if name == "sweep"]
        assert len(sweeps) == 4
        assert all(v == {"sanshi": 1, "artifact": 201, "plan": 2, "eye": 11} for v in sweeps)
        assert game.energy == 0
        assert game.selection == game.original["selection"]
        assert game.calls[-2][0] == "restore" and game.calls[-1][0] == "home"
        assert not path.exists()
    asyncio.run(run())


@pytest.mark.parametrize("field", ["eye", "artifact"])
def test_unrestorable_original_is_rejected_before_any_switch(tmp_path, field):
    async def run():
        m = energy_module()
        game = FakeGame()
        game.selection[field] = 0
        path = tmp_path / "restore.json"
        result = await m.EnergyTask(game, path)(context())
        assert result.status == "waiting"
        assert not any(name in {"eye", "select", "sweep"} for name, _ in game.calls)
        assert not path.exists()
    asyncio.run(run())


def test_plan_choice_uses_one_optimize_instead_of_switching_every_combination(tmp_path):
    async def run():
        m = energy_module()
        game = FakeGame()
        result = await m.EnergyTask(game, tmp_path / "restore.json")(context())
        assert result.status == "success"
        names = [name for name, _ in game.calls]
        assert names.count("optimize") == 1
        assert "select" not in names  # 不再逐组合切方案
        assert names.count("eye") == 1
    asyncio.run(run())


def test_daily_limit_stops_without_purchase(tmp_path):
    async def run():
        m = energy_module()
        game = FakeGame(limits=1)
        await m.EnergyTask(game, tmp_path / "restore.json")(context())
        assert game.num == 1
        assert game.selection == game.original["selection"]
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["optimize", "reject"])
def test_confirmed_rejection_restores_then_reports_waiting(tmp_path, failure):
    async def run():
        m = energy_module()
        game = FakeGame()
        game.failure = failure
        path = tmp_path / "restore.json"
        result = await m.EnergyTask(game, path)(context())
        assert result.status == "waiting"
        assert game.selection == game.original["selection"]
        assert not path.exists()
        assert sum(name == "sweep" for name, _ in game.calls) <= 1
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["uncertain", "no_progress", "restore"])
def test_unknown_preserves_journal_and_blocks_new_round(tmp_path, failure):
    async def run():
        m = energy_module()
        game = FakeGame()
        game.failure = failure
        path = tmp_path / "restore.json"
        handler = m.EnergyTask(game, path)
        with pytest.raises(ExecutionUncertain):
            await handler(context())
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8")) == game.original
        old = len(game.calls)
        with pytest.raises(ExecutionUncertain):
            await handler(context())
        assert len(game.calls) == old
        if failure == "uncertain":
            assert not any(name == "restore" for name, _ in game.calls)
    asyncio.run(run())


def test_stop_between_sweeps_restores_without_next_spend(tmp_path):
    async def run():
        m = energy_module()
        game = FakeGame()
        stopped = False
        def stop():
            nonlocal stopped
            stopped = True
        game.on_sweep = stop
        await m.EnergyTask(game, tmp_path / "restore.json")(context(lambda: stopped))
        assert game.num == 1
        assert game.selection == game.original["selection"]
    asyncio.run(run())


def test_cancel_between_confirmed_operations_still_restores(tmp_path):
    async def run():
        m = energy_module()
        game = FakeGame()
        entered = asyncio.Event()
        original = game.optimize
        async def optimize():
            await original()
            entered.set()
            await asyncio.Event().wait()
        game.optimize = optimize
        path = tmp_path / "restore.json"
        job = asyncio.create_task(m.EnergyTask(game, path)(context()))
        await entered.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert game.selection == game.original["selection"]
        assert not path.exists()
    asyncio.run(run())


def test_existing_journal_is_not_overwritten(tmp_path):
    async def run():
        m = energy_module()
        path = tmp_path / "restore.json"
        path.write_text('{"old":true}', encoding="utf-8")
        game = FakeGame()
        with pytest.raises(ExecutionUncertain):
            await m.EnergyTask(game, path)(context())
        assert not game.calls
        assert path.read_text(encoding="utf-8") == '{"old":true}'
    asyncio.run(run())


def test_bridge_client_reuses_http_channel_and_quotes_js_safely(tmp_path):
    async def run():
        energy_module()
        b = importlib.import_module("package.daily_tasks.bridge_game")
        state = tmp_path / "bridge.json"
        state.write_text(json.dumps({"port": 61999, "token": "private"}), encoding="utf-8")
        requests = []
        async def peer(request):
            requests.append(request)
            assert request.headers["authorization"] == "Bearer private"
            body = json.loads(request.content)
            assert body["context"] == "game"
            return httpx.Response(200, json={"ok": True, "result": {"type": "object", "value": {"status": "ok", "value": {"energy": 90, "maximum": 100, "safe": True}}}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(peer))
        game = b.BridgeGame(state, client=client)
        try:
            assert (await game.inspect())["energy"] == 90
            await game.catalog('引号";throw new Error(); //')
            body = json.loads(requests[1].content)
            assert json.dumps({'name': '引号";throw new Error(); //'}, ensure_ascii=False) in body["expression"]
            assert len(requests) == 2
        finally:
            await client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("reply", [{"ok": False, "execution_may_have_run": True, "error": {"kind": "timeout"}}, {"ok": True, "result": {"value": {"status": "uncertain", "message": "未确认"}}}])
def test_bridge_unknown_mutation_is_not_retried(tmp_path, reply):
    async def run():
        energy_module()
        b = importlib.import_module("package.daily_tasks.bridge_game")
        state = tmp_path / "bridge.json"
        state.write_text(json.dumps({"port": 61999, "token": "private"}), encoding="utf-8")
        calls = []
        async def peer(request):
            calls.append(request)
            return httpx.Response(200, json=reply)
        async with httpx.AsyncClient(transport=httpx.MockTransport(peer)) as client:
            game = b.BridgeGame(state, client=client)
            with pytest.raises(ExecutionUncertain):
                await game.sweep()
            assert len(calls) == 1
    asyncio.run(run())


def test_cli_scheduler_registers_energy_without_connecting_bridge(tmp_path):
    m = energy_module()
    from tools.daily_tasks import build_scheduler
    from package.daily_tasks.config import parse_config
    raw = load_config().raw
    raw["enabled"] = False
    config = parse_config(raw)
    scheduler, game = build_scheduler(config, tmp_path / 'missing-bridge.json', tmp_path / 'restore.json')
    assert scheduler.snapshot()["tasks"]["energy"]["registered"]
    assert not scheduler.config.enabled
    assert game.client is None


def test_energy_config_rejects_unimplemented_or_unsafe_modes():
    energy_module()
    from package.daily_tasks.config import parse_config
    baseline = load_config().raw
    for key, value in [("spend_mode", "buy_more"), ("sanshi_plan_scope", "edit"), ("artifact_plan_scope", "edit"),
                       ("restore_original", False), ("formation_eye_name", ""), ("typo", 1)]:
        raw = copy.deepcopy(baseline)
        raw["tasks"]["energy"]["params"][key] = value
        with pytest.raises(ValueError):
            parse_config(raw)


def test_distinct_configs_cannot_overlap_same_game_transaction(tmp_path, monkeypatch):
    async def run():
        energy_module()
        b = importlib.import_module("package.daily_tasks.bridge_game")
        monkeypatch.setattr(b, "TRANSACTION_DIR", tmp_path)
        state = tmp_path / "bridge.json"
        state.write_text(json.dumps({"port":61999,"token":"private"}), encoding="utf-8")
        game_a, game_b = b.BridgeGame(state), b.BridgeGame(state)
        journal_a, journal_b = tmp_path / 'a.json', tmp_path / 'b.json'
        async with game_a.transaction(journal_a):
            with pytest.raises(RetryableTaskError):
                async with game_b.transaction(journal_b):
                    pytest.fail('同一账号出现并发扫荡轮次')
        async with game_b.transaction(journal_b):
            pass
        with pytest.raises(ExecutionUncertain):
            async with game_a.transaction(journal_a):
                journal_a.write_text('{}')
                raise ExecutionUncertain('未确认')
        with pytest.raises(ExecutionUncertain):
            async with game_b.transaction(journal_b):
                pytest.fail('未决轮次被另一个配置忽略')
    asyncio.run(run())


@pytest.mark.parametrize("status", ["ok", "uncertain"])
def test_bridge_cancel_waits_for_pending_js_receipt(tmp_path, status):
    async def run():
        energy_module()
        b = importlib.import_module("package.daily_tasks.bridge_game")
        state = tmp_path / "bridge.json"
        state.write_text(json.dumps({"port":61999,"token":"private"}), encoding="utf-8")
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def peer(request):
            calls.append(request)
            entered.set()
            await release.wait()
            return httpx.Response(200,json={"ok":True,"result":{"value":{"status":status,"value":10}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(peer)) as client:
            game = b.BridgeGame(state,client=client)
            job = asyncio.create_task(game.set_eye(11))
            await entered.wait()
            job.cancel()
            await asyncio.sleep(0)
            assert not job.done()
            release.set()
            with pytest.raises(asyncio.CancelledError if status=="ok" else ExecutionUncertain):
                await job
            assert len(calls)==1
    asyncio.run(run())


def test_gui_energy_uses_memory_only_and_force_trigger(tmp_path):
    async def run():
        m = energy_module()
        game = FakeGame(energy=30)
        handler = m.EnergyTask(game, None)
        result = await handler.run(context(), force_trigger=True)
        assert result.status == 'success'
        assert game.num == 2
        assert game.selection == game.original['selection']
        assert handler.pending_original is None
        assert not list(tmp_path.iterdir())
    asyncio.run(run())


def test_task_returns_to_main_before_sweeping_when_on_normal_page(tmp_path):
    async def run():
        m=energy_module();game=FakeGame()
        on_page=True
        original_inspect=game.inspect
        original_home=game.home
        async def inspect():
            result=await original_inspect();result['safe']=not on_page;return result
        async def home():
            nonlocal on_page
            await original_home();on_page=False
        game.inspect=inspect;game.home=home
        result=await m.EnergyTask(game,tmp_path/'restore.json')(context())
        assert result.status=='success'
        names=[name for name,_ in game.calls]
        assert names[:3]==['inspect','home','inspect']
        assert game.num>0
    asyncio.run(run())


def test_blocked_return_to_home_never_changes_equipment_or_spends(tmp_path):
    async def run():
        m=energy_module();game=FakeGame()
        async def inspect():return {'energy':90,'maximum':100,'safe':False,'blockers':['BattleUI']}
        async def home():raise RetryableTaskError('战斗进行中，不能直接返回大厅')
        game.inspect=inspect;game.home=home
        result=await m.EnergyTask(game,tmp_path/'restore.json')(context())
        assert result.status=='waiting'
        assert '战斗' in result.message
        assert not any(name in ('select','eye','sweep') for name,_ in game.calls)
    asyncio.run(run())


def test_registration_keeps_other_tasks_unregistered():
    m = energy_module()
    config = load_config()
    scheduler = Scheduler(config)
    m.register_energy(scheduler, FakeGame(), Path("unused-restore.json"))
    assert scheduler.snapshot()["tasks"]["energy"]["registered"]
    assert not scheduler.snapshot()["tasks"]["arena"]["registered"]
