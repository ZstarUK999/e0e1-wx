"""墓任务按正常公开UI回执执行；仅使用本地假游戏，不连接游戏。"""

import asyncio
import copy
import importlib

import pytest

from package.daily_tasks.config import Schedule, TaskConfig
from package.daily_tasks.scheduler import ExecutionUncertain, RetryableTaskError, TaskContext


def tomb_module():
    try:
        return importlib.import_module("package.daily_tasks.tombs")
    except ModuleNotFoundError:
        pytest.fail("正常UI墓任务处理器尚未实现")


def context(kind="sanshi", mode="raid", stop=lambda: False, **params):
    task = TaskConfig(f"{kind}_{mode}", "墓任务", True, 1, 30, 20,
                      Schedule("interval", 5), params)
    return TaskContext(task, None, stop)


class FakeGame:
    def __init__(self):
        self.states = {kind: {"ready": True, "finished": False, "filling": True, "idle": False,
                              "raid_remaining": 2, "fill_remaining": 2}
                       for kind in ("sanshi", "artifact")}
        self.targets = {kind: [{"id": 101, "site_num": 15, "can_fill": True},
                               {"id": 102, "site_num": 16, "can_fill": True},
                               {"id": 103, "site_num": 18, "can_fill": False}]
                        for kind in self.states}
        self.calls = []
        self.receipts = {}
        self.errors = {}
        self.after = None
        self.win = True
        self.after_collect = None
        self.next_ready_at = None
        self.server_now = 1000.0
        self.cross_day_at = 500.0  # 上次跨日：500 秒（下次跨日 86900 秒）

    def record(self, name, kind=None, *args):
        self.calls.append((name, kind, *args))
        if name in self.errors:
            raise self.errors[name]

    def respond(self, name, receipt):
        if self.after:
            self.after(name)
        return copy.deepcopy(self.receipts.get(name, receipt))

    async def tomb_state(self, kind):
        self.record("state", kind)
        state = self.respond("state", self.states[kind])
        # 到期时间/服务器时间/跨日时刻：给任务算等待用。
        state.setdefault("next_ready_at", self.next_ready_at)
        state.setdefault("server_now", self.server_now)
        state.setdefault("cross_day_at", self.cross_day_at)
        return state

    async def tomb_collect(self, kind):
        self.record("collect", kind)
        self.states[kind].update(finished=False, filling=False, idle=True)
        if self.after_collect:
            self.states[kind].update(self.after_collect)
        return self.respond("collect", {"confirmed": True})

    async def tomb_start(self, kind):
        self.record("start", kind)
        self.states[kind].update(finished=False, filling=True, idle=False)
        return self.respond("start", {"confirmed": True})

    async def tomb_recruit(self, kind):
        self.record("recruit", kind)
        return self.respond("recruit", {"confirmed": True})

    async def tomb_targets(self, kind, mode, refresh=True, minimum=0):
        self.record("targets", kind, mode, refresh)
        return self.respond("targets", self.targets[kind])

    async def tomb_raid(self, kind, target_id):
        self.record("raid", kind, target_id)
        # 服务端扣次数：循环继续与否靠重新读到的次数判断。
        self.states[kind]["raid_remaining"] -= 1
        return self.respond("raid", {"confirmed": True, "win": self.win})

    async def tomb_fill(self, kind, target_id):
        self.record("fill", kind, target_id)
        self.states[kind]["fill_remaining"] -= 1
        return self.respond("fill", {"confirmed": True})

    async def home(self):
        self.record("home")
        self.respond("home", None)


def make_task(game, mode, kind="sanshi", failed_ids=None):
    m = tomb_module()
    if mode == "cycle":
        return m.TombCycleTask(game, kind)
    if mode == "raid":
        return m.TombRaidTask(game, kind, failed_ids)
    return m.TombFillTask(game, kind)


@pytest.mark.parametrize("kind", ["sanshi", "artifact"])
def test_cycle_collects_then_rereads_and_reopens_before_recruit(kind):
    async def run():
        game = FakeGame()
        game.states[kind].update(finished=True, filling=False)
        task = make_task(game, "cycle", kind)
        result = await task(context(kind, "cycle", recruit=True))
        assert result.status == "success"
        assert game.calls == [("home", None), ("state", kind), ("collect", kind), ("state", kind),
                              ("start", kind), ("recruit", kind), ("home", None)]
        assert game.states[kind]["filling"] is True
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["sanshi", "artifact"])
def test_idle_cycle_starts_once_and_recruits_only_after_that_start(kind):
    async def run():
        game = FakeGame()
        game.states[kind].update(filling=False, idle=True)
        task = make_task(game, "cycle", kind)
        assert (await task.run(context(kind, "cycle"), force_trigger=True)).status == "success"
        assert game.calls == [("home", None), ("state", kind), ("start", kind), ("recruit", kind), ("home", None)]
        game.calls.clear()
        assert (await task(context(kind, "cycle"))).status == "waiting"
        assert game.calls == [("home", None), ("state", kind), ("home", None)]
    asyncio.run(run())


def test_cycle_recruit_can_be_disabled_without_skipping_reopen():
    async def run():
        game = FakeGame()
        game.states["sanshi"].update(filling=False, idle=True)
        result = await make_task(game, "cycle")(context(mode="cycle", recruit=False))
        assert result.status == "success"
        assert [call[0] for call in game.calls] == ["home", "state", "start", "home"]
    asyncio.run(run())


def test_cycle_uses_state_after_collection_instead_of_assuming_idle():
    async def run():
        game = FakeGame()
        game.states["sanshi"].update(finished=True, filling=False)
        game.after_collect = {"filling": True, "idle": False}
        result = await make_task(game, "cycle")(context(mode="cycle"))
        assert result.status == "success"
        assert [call[0] for call in game.calls] == ["home", "state", "collect", "state", "home"]
    asyncio.run(run())


def test_recruit_cooldown_is_not_bypassed_or_repeated_on_active_tomb():
    async def run():
        game = FakeGame()
        game.states["sanshi"].update(filling=False, idle=True)
        game.errors["recruit"] = RetryableTaskError("招募冷却尚未结束")
        task = make_task(game, "cycle")
        result = await task(context(mode="cycle"))
        assert result.status == "waiting"
        assert "冷却" in result.message
        assert result.next_delay_seconds == 20
        assert [call[0] for call in game.calls] == ["home", "state", "start", "recruit", "home"]
        game.calls.clear()
        await task(context(mode="cycle"))
        assert [call[0] for call in game.calls] == ["home", "state", "home"]
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["sanshi", "artifact"])
@pytest.mark.parametrize("mode", ["raid", "fill"])
def test_counts_exhausted_never_scan_even_when_forced(kind, mode):
    async def run():
        game = FakeGame()
        game.states[kind][f"{mode}_remaining"] = 0
        result = await make_task(game, mode, kind).run(context(kind, mode), force_trigger=True)
        assert result.status == "waiting"
        assert game.calls == [("home", None), ("state", kind), ("home", None)]
        assert game.states[kind]["fill_remaining" if mode == "raid" else "raid_remaining"] == 2
    asyncio.run(run())


def test_raid_and_fill_counts_are_independent_between_modes_and_systems():
    async def run():
        game = FakeGame()
        game.states["sanshi"]["raid_remaining"] = 0
        await make_task(game, "raid", "sanshi")(context("sanshi", "raid"))
        assert not any(call[0] == "targets" for call in game.calls)
        game.calls.clear()
        assert (await make_task(game, "fill", "sanshi")(context("sanshi", "fill"))).status == "success"
        assert (await make_task(game, "raid", "artifact")(context("artifact", "raid"))).status == "success"
        assert game.states["sanshi"]["raid_remaining"] == 0
        # 填土一轮把当前列表里可填的目标都填完。
        assert game.states["sanshi"]["fill_remaining"] == 0
        # 盗掠同样把剩余次数打完，所以法器也归零；填土次数没有被盗掠影响。
        assert game.states["artifact"]["raid_remaining"] == 0
        assert game.states["artifact"]["fill_remaining"] == 2
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["sanshi", "artifact"])
def test_raid_requires_single_players_sixteen_tombs_and_executes_one_target(kind):
    async def run():
        game = FakeGame()
        result = await make_task(game, "raid", kind)(context(kind, "raid", minimum_tombs=16))
        assert result.status == "success"
        assert result.next_delay_seconds is None
        # 还有次数就继续打：2次机会用完两次盗掠才收工。
        assert game.calls == [("home", None), ("state", kind), ("targets", kind, "raid", True),
                              ("raid", kind, 102), ("state", kind), ("targets", kind, "raid", True),
                              ("raid", kind, 102), ("state", kind), ("home", None)]
        assert game.states[kind]["raid_remaining"] == 0
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["raid", "fill"])
def test_no_eligible_target_waits_for_configured_rescan(mode):
    async def run():
        game = FakeGame()
        game.targets["sanshi"] = [{"id": 1, "site_num": 8, "can_fill": False},
                                  {"id": 2, "site_num": 8, "can_fill": False}]
        result = await make_task(game, mode)(context(mode=mode, rescan_seconds=60))
        assert result.status == "waiting"
        assert result.next_delay_seconds == 60
        # 填土在没有可填目标时会再拉一次列表确认，仍没有才结束。
        extra = ["state", "targets"] if mode == "fill" else []
        assert [call[0] for call in game.calls] == ["home", "state", "targets"] + extra + ["home"]
    asyncio.run(run())


def test_raid_no_candidate_uses_rescan_not_repeating_attack():
    async def run():
        game = FakeGame()
        game.targets["sanshi"] = []
        result = await make_task(game, "raid")(context(rescan_seconds=75))
        assert result.next_delay_seconds == 75
        assert not any(call[0] == "raid" for call in game.calls)
    asyncio.run(run())


def test_loss_is_not_success_and_failed_ids_are_shared_in_this_session():
    async def run():
        game = FakeGame()
        game.win = False
        failed = set()
        task = make_task(game, "raid", failed_ids=failed)
        result = await task(context(skip_failed_players=True))
        assert result.status == "waiting"
        assert "负" in result.message
        # 两次机会都打完：102 失败后跳过，继续打 103。
        assert failed == {102, 103}
        assert game.states["sanshi"]["raid_remaining"] == 0
        game.states["sanshi"]["raid_remaining"] = 1
        game.win = True
        # 只把 102 记在失败名单里：跳过它去打 103，胜利后名单不变。
        shared = {102}
        task = make_task(game, "raid", failed_ids=shared)
        result = await task(context(skip_failed_players=True))
        assert result.status == "success"
        assert shared == {102}
        assert [call[2] for call in game.calls if call[0] == "raid"][-1] == 103
        old_scans = sum(call[0] == "targets" for call in game.calls)
        await task(context())
        assert sum(call[0] == "targets" for call in game.calls) == old_scans
    asyncio.run(run())


def test_failed_players_skip_is_kind_local_and_can_be_disabled():
    async def run():
        game = FakeGame()
        task = make_task(game, "raid", failed_ids={102})
        assert (await task(context(skip_failed_players=False))).status == "success"
        # 关闭跳过后同一目标可以连打，直到次数用完（初始2次）。
        assert [call[2] for call in game.calls if call[0] == "raid"] == [102, 102]
        game.calls.clear()
        task = make_task(game, "raid", "artifact", failed_ids=set())
        await task(context("artifact", "raid", skip_failed_players=True))
        assert [call[2] for call in game.calls if call[0] == "raid"] == [102, 102]
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["sanshi", "artifact"])
def test_fill_uses_can_fill_and_does_not_require_any_tomb_count(kind):
    async def run():
        game = FakeGame()
        game.targets[kind] = [{"id": 99, "site_num": 99, "can_fill": False},
                              {"id": 101, "site_num": 0, "can_fill": True},
                              {"id": 102, "site_num": 17, "can_fill": True}]
        result = await make_task(game, "fill", kind)(context(kind, "fill", minimum_tombs=16))
        assert result.status == "success"
        # 2次机会全部用在同一批可填目标上（同一玩家可重复填）。
        fills = [call[2] for call in game.calls if call[0] == "fill"]
        assert len(fills) == 2
        assert set(fills) <= {101, 102}
        assert game.calls[0] == ("home", None) and game.calls[-1] == ("home", None)
        assert game.states[kind]["fill_remaining"] == 0
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cycle", "raid", "fill"])
def test_not_ready_does_not_issue_mutations_or_scan(mode):
    async def run():
        game = FakeGame()
        game.states["sanshi"]["ready"] = False
        result = await make_task(game, mode)(context(mode=mode))
        assert result.status == "waiting"
        assert game.calls == [("home", None), ("state", "sanshi"), ("home", None)]
    asyncio.run(run())


@pytest.mark.parametrize("mode,action", [("cycle", "collect"), ("cycle", "start"),
                                         ("cycle", "recruit"), ("raid", "raid"), ("fill", "fill")])
@pytest.mark.parametrize("receipt", [None, {}, {"confirmed": False}, {"confirmed": 1}])
def test_mutation_requires_explicit_receipt_and_blocks_replay(mode, action, receipt):
    async def run():
        game = FakeGame()
        if action == "collect":
            game.states["sanshi"].update(finished=True, filling=False)
        if action in ("start", "recruit"):
            game.states["sanshi"].update(filling=False, idle=True)
        game.receipts[action] = receipt
        task = make_task(game, mode)
        with pytest.raises(ExecutionUncertain):
            await task(context(mode=mode))
        assert game.calls[-1][0] == action
        # 开头回到大厅是允许的；未确认后不得收尾回大厅。
        assert not any(call[0] == "home" for call in game.calls[1:])
        old_calls = list(game.calls)
        with pytest.raises(ExecutionUncertain):
            await task(context(mode=mode))
        assert game.calls == old_calls
    asyncio.run(run())


@pytest.mark.parametrize("receipt", [{"confirmed": True}, {"confirmed": True, "win": None},
                                     {"confirmed": True, "win": 1}])
def test_raid_unknown_battle_outcome_stops_without_marking_failed(receipt):
    async def run():
        game = FakeGame()
        game.receipts["raid"] = receipt
        failed = set()
        with pytest.raises(ExecutionUncertain):
            await make_task(game, "raid", failed_ids=failed)(context())
        assert failed == set()
        assert game.calls[-1] == ("raid", "sanshi", 102)
    asyncio.run(run())


@pytest.mark.parametrize("mode,action", [("cycle", "collect"), ("raid", "raid"), ("fill", "fill")])
@pytest.mark.parametrize("error", [ExecutionUncertain("响应未确认"), RuntimeError("未知运行错误")])
def test_unknown_error_never_returns_home_or_retries(mode, action, error):
    async def run():
        game = FakeGame()
        if mode == "cycle":
            game.states["sanshi"].update(finished=True, filling=False)
        game.errors[action] = error
        task = make_task(game, mode)
        with pytest.raises(ExecutionUncertain):
            await task(context(mode=mode))
        assert game.calls[-1][0] == action
        before = list(game.calls)
        with pytest.raises(ExecutionUncertain):
            await task(context(mode=mode))
        assert game.calls == before
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cycle", "raid", "fill"])
def test_explicit_rejection_returns_home_and_is_not_success(mode):
    async def run():
        game = FakeGame()
        action = "collect" if mode == "cycle" else mode
        if mode == "cycle":
            game.states["sanshi"].update(finished=True, filling=False)
        game.errors[action] = RetryableTaskError("正常按钮被明确拒绝")
        failed = set()
        result = await make_task(game, mode, failed_ids=failed)(context(mode=mode))
        assert result.status == "waiting"
        # 填土全部被拒绝时按“下次重扫”等待，其余按失败重试间隔。
        assert result.next_delay_seconds == (60 if mode == "fill" else 20)
        assert game.calls[-1] == ("home", None)
        # 填土会对每个可填目标各试一次；其余动作整轮只发一次。
        assert sum(call[0] == action for call in game.calls) == (2 if mode == "fill" else 1)
        assert failed == set()
    asyncio.run(run())


def test_unfinished_tomb_waits_for_its_ready_time(caplog):
    async def run():
        import logging
        game = FakeGame()
        game.next_ready_at = 1000.0 + 42 * 60  # 42 分钟后到期
        with caplog.at_level(logging.INFO, logger="plugin_manager.tombs"):
            result = await make_task(game, "cycle")(context(mode="cycle"))
        assert result.status == "waiting"
        assert result.next_delay_seconds == 42 * 60 + 5
        assert "预计" in caplog.text and "校准" in caplog.text
    asyncio.run(run())


def test_unfinished_tomb_without_ready_time_falls_back_to_interval():
    async def run():
        game = FakeGame()
        game.next_ready_at = None
        result = await make_task(game, "cycle")(context(mode="cycle", rescan_seconds=90))
        assert result.next_delay_seconds == 90
    asyncio.run(run())


def test_exhausted_allowance_waits_for_next_cross_day(caplog):
    async def run():
        import logging
        for mode, field in (("raid", "raid_remaining"), ("fill", "fill_remaining")):
            game = FakeGame()
            game.states["sanshi"][field] = 0
            with caplog.at_level(logging.INFO, logger="plugin_manager.tombs"):
                result = await make_task(game, mode)(context(mode=mode))
            assert result.status == "waiting"
            # 下次跨日 = 500 + 86400 = 86900，现在 1000 → 85900 秒，受 1 小时上限约束。
            assert result.next_delay_seconds == 3600.0
            assert "跨日" in result.message
            assert "跨日" in caplog.text
    asyncio.run(run())


def test_exhausted_allowance_without_cross_day_falls_back_to_interval():
    async def run():
        game = FakeGame()
        game.cross_day_at = None
        game.states["sanshi"]["raid_remaining"] = 0
        result = await make_task(game, "raid")(context(rescan_seconds=120))
        assert result.next_delay_seconds == 120
    asyncio.run(run())


def test_fill_round_fills_every_available_target_until_allowance_runs_out():
    async def run():
        game = FakeGame()
        game.targets["sanshi"] = [{"id": 101, "site_num": 0, "can_fill": True},
                                  {"id": 102, "site_num": 0, "can_fill": True},
                                  {"id": 103, "site_num": 0, "can_fill": True}]
        game.states["sanshi"]["fill_remaining"] = 2
        result = await make_task(game, "fill")(context(mode="fill"))
        assert result.status == "success"
        assert len([call for call in game.calls if call[0] == "fill"]) == 2
        assert game.states["sanshi"]["fill_remaining"] == 0
    asyncio.run(run())


def test_fill_can_repeat_the_same_player_until_allowance_runs_out():
    async def run():
        game = FakeGame()
        # 只有一个可填玩家，3次机会应全部填给他。
        game.targets["sanshi"] = [{"id": 101, "site_num": 0, "can_fill": True}]
        game.states["sanshi"]["fill_remaining"] = 3
        result = await make_task(game, "fill")(context(mode="fill"))
        assert result.status == "success"
        assert [call[2] for call in game.calls if call[0] == "fill"] == [101, 101, 101]
        assert game.states["sanshi"]["fill_remaining"] == 0
        assert "3次" in result.message
    asyncio.run(run())


def test_fill_skips_rejected_target_and_continues():
    async def run():
        game = FakeGame()
        game.targets["sanshi"] = [{"id": 101, "site_num": 0, "can_fill": True},
                                  {"id": 102, "site_num": 0, "can_fill": True}]
        original = game.tomb_fill
        async def fill(kind, target_id):
            if target_id == 101:
                raise RetryableTaskError("不是同阴司玩家")
            return await original(kind, target_id)
        game.tomb_fill = fill
        result = await make_task(game, "fill")(context(mode="fill"))
        assert result.status == "success"
        # 101 被拒绝后换 102；102 可重复填，直到次数用完。
        assert [call[2] for call in game.calls if call[0] == "fill"] == [102, 102]
        assert game.calls[-1] == ("home", None)
    asyncio.run(run())


def test_fill_stops_immediately_when_a_receipt_is_unknown():
    async def run():
        game = FakeGame()
        game.receipts["fill"] = {"confirmed": False}
        task = make_task(game, "fill")
        with pytest.raises(ExecutionUncertain):
            await task(context(mode="fill"))
        assert [call[2] for call in game.calls if call[0] == "fill"] == [101]
        before = list(game.calls)
        with pytest.raises(ExecutionUncertain):
            await task(context(mode="fill"))
        assert game.calls == before
    asyncio.run(run())


def test_fill_stops_before_next_target_when_stop_requested():
    async def run():
        game = FakeGame()
        stopped = False
        def on_call(name, *args):
            nonlocal stopped
            if name == "fill":
                stopped = True
        game.after = on_call
        result = await make_task(game, "fill")(context(mode="fill", stop=lambda: stopped))
        assert result.status == "waiting"
        assert [call[2] for call in game.calls if call[0] == "fill"] == [101]
        assert not any(call[0] == "home" for call in game.calls[1:])
    asyncio.run(run())


def test_scan_log_reports_refresh_count_and_best_candidate(caplog):
    async def run():
        game = FakeGame()
        game.targets["sanshi"] = [{"id": 101, "site_num": 12, "name": "甲", "server": "561服"},
                                  {"id": 102, "site_num": 16, "name": "乙", "server": "561服"}]
        with caplog.at_level("INFO", logger="plugin_manager.tombs"):
            await make_task(game, "raid")(context("sanshi", "raid"))
        assert "盗掠扫描" in caplog.text
        assert "乙" in caplog.text and "16" in caplog.text
    asyncio.run(run())


def test_scan_log_without_candidate_name_still_reports_id(caplog):
    async def run():
        game = FakeGame()
        game.targets["sanshi"] = []
        with caplog.at_level("INFO", logger="plugin_manager.tombs"):
            await make_task(game, "raid")(context("sanshi", "raid"))
        assert "无" in caplog.text
    asyncio.run(run())


def test_target_payload_may_carry_scan_counters():
    async def run():
        game = FakeGame()
        game.targets["sanshi"] = {"targets": [{"id": 101, "site_num": 20}], "refresh_count": 7, "new_players": 3}
        result = await make_task(game, "raid")(context("sanshi", "raid"))
        assert result.status == "success"
        # 还有次数就继续，2次机会打满。
        assert [call[2] for call in game.calls if call[0] == "raid"] == [101, 101]
    asyncio.run(run())


def test_raid_stops_when_allowance_is_gone_between_rounds():
    async def run():
        game = FakeGame()
        game.states["sanshi"]["raid_remaining"] = 5
        result = await make_task(game, "raid")(context("sanshi", "raid"))
        assert result.status == "success"
        assert sum(call[0] == "raid" for call in game.calls) == 5
        assert game.states["sanshi"]["raid_remaining"] == 0
        assert "5次" in result.message
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cycle", "raid", "fill"])
def test_stop_at_entry_sends_no_requests(mode):
    async def run():
        game = FakeGame()
        result = await make_task(game, mode).run(context(mode=mode, stop=lambda: True), force_trigger=True)
        assert result.status == "waiting"
        assert not game.calls
    asyncio.run(run())


@pytest.mark.parametrize("mode,after", [("cycle", "state"), ("cycle", "collect"),
                                       ("cycle", "start"), ("raid", "targets"), ("fill", "targets")])
def test_stop_between_actions_does_not_issue_next_request(mode, after):
    async def run():
        game = FakeGame()
        if mode == "cycle":
            game.states["sanshi"].update(finished=True, filling=False)
        stopped = False
        def on_call(name):
            nonlocal stopped
            if name == after:
                stopped = True
        game.after = on_call
        result = await make_task(game, mode)(context(mode=mode, stop=lambda: stopped))
        assert result.status == "waiting"
        assert game.calls[-1][0] == after
        assert not any(call[0] == "home" for call in game.calls[1:])
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cycle", "raid", "fill"])
def test_cancelled_operation_does_not_close_uncertain_ui_or_replay(mode):
    async def run():
        game = FakeGame()
        action = "collect" if mode == "cycle" else mode
        if mode == "cycle":
            game.states["sanshi"].update(finished=True, filling=False)
        game.errors[action] = asyncio.CancelledError()
        task = make_task(game, mode)
        with pytest.raises(asyncio.CancelledError):
            await task(context(mode=mode))
        assert game.calls[-1][0] == action
        before = list(game.calls)
        with pytest.raises(ExecutionUncertain):
            await task(context(mode=mode))
        assert game.calls == before
    asyncio.run(run())


def test_non_cycle_action_logs_include_success_and_loss(caplog):
    async def run():
        game = FakeGame()
        with caplog.at_level("INFO", logger="plugin_manager.tombs"):
            await make_task(game, "raid")(context())
            game.win = False
            await make_task(game, "raid")(context())
        assert "盗掠" in caplog.text
        assert "本轮盗掠完成" in caplog.text
        assert "负" in caplog.text
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["raid", "fill"])
@pytest.mark.parametrize("count", [None, -1, True, "2", 1.5])
def test_invalid_remaining_count_does_not_scan_or_spend(mode, count):
    async def run():
        game = FakeGame()
        game.states["sanshi"][f"{mode}_remaining"] = count
        result = await make_task(game, mode)(context(mode=mode))
        assert result.status == "waiting"
        assert [call[0] for call in game.calls] == ["home", "state", "home"]
    asyncio.run(run())
