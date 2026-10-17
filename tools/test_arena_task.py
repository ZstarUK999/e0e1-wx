"""斗法任务离线测试：仅使用正常 UI 接口的 fake，不连接游戏。"""

import asyncio
import copy
import importlib
import logging
from datetime import datetime, timezone

import pytest

from package.daily_tasks.config import load_config, parse_config
from package.daily_tasks.scheduler import BEIJING, ExecutionUncertain, RetryableTaskError, TaskContext


def arena_module():
    try:
        return importlib.import_module("package.daily_tasks.arena")
    except ModuleNotFoundError:
        pytest.fail("ArenaTask 尚未实现")


def moment(hour=10, minute=28, second=0):
    return datetime(2026, 10, 14, hour, minute, second, tzinfo=BEIJING)


def context(*, excluded=(), continuous=True, stop=lambda: False, window_end=None):
    raw = load_config().raw
    raw["tasks"]["arena"]["params"].update(
        excluded_player_ids=list(excluded), continuous=continuous
    )
    task = parse_config(raw).tasks["arena"]
    return TaskContext(task, window_end or moment(10, 30), stop)


def target(player_id, rank=None):
    result = {"id": player_id}
    if rank is not None:
        result["rank"] = rank
    return result


class FakeGame:
    def __init__(self, *, targets=None, tickets=1, refresh_remaining=0):
        self.targets = copy.deepcopy(targets if targets is not None else [target(1, 10)])
        self.tickets = tickets
        self.refresh_remaining = refresh_remaining
        self.refresh_states = []
        self.replies = []
        self.calls = []
        self.challenge_consumes = True
        self.refresh_consumes = True
        self.failure = None
        self.on_state = None
        self.on_refresh = None
        self.on_challenge = None
        self.state_reads = 0

    def snapshot(self):
        return {"targets": copy.deepcopy(self.targets), "tickets": self.tickets,
                "refresh_remaining": self.refresh_remaining}

    async def home(self):
        self.calls.append(("home", None))
        if self.failure == "home_reject":
            raise RetryableTaskError("战斗界面不能强退")
        return True

    async def arena_state(self):
        self.calls.append(("state", None))
        self.state_reads += 1
        if self.failure == "state_reject":
            raise RetryableTaskError("界面尚未就绪")
        if self.on_state:
            self.on_state(self)
        return self.snapshot()

    async def arena_refresh(self):
        self.calls.append(("refresh", None))
        if self.failure == "refresh_reject":
            raise RetryableTaskError("刷新次数不足")
        if self.failure == "refresh_unknown":
            raise ExecutionUncertain("刷新回执未知")
        if self.refresh_consumes:
            self.refresh_remaining -= 1
        if self.refresh_states:
            updated = self.refresh_states.pop(0)
            self.targets = copy.deepcopy(updated["targets"])
            self.refresh_remaining = updated.get("refresh_remaining", self.refresh_remaining)
            self.tickets = updated.get("tickets", self.tickets)
        if self.on_refresh:
            self.on_refresh(self)
        return self.snapshot()

    async def arena_challenge(self, player_id):
        self.calls.append(("challenge", player_id))
        if self.failure == "challenge_reject":
            raise RetryableTaskError("挑战券不足")
        if self.failure == "challenge_unknown":
            raise ExecutionUncertain("挑战回执未知")
        if self.failure == "challenge_exception":
            raise RuntimeError("响应断开")
        if self.challenge_consumes:
            self.tickets -= 1
        reply = self.replies.pop(0) if self.replies else {"confirmed": True, "win": True}
        if self.on_challenge:
            self.on_challenge(self)
        return reply

    def mutations(self):
        return [(name, value) for name, value in self.calls if name not in ("state", "home")]


def execute(game, ctx=None, *, now=None, force=False):
    handler = arena_module().ArenaTask(game, now=now or (lambda: moment()))
    return asyncio.run(handler.run(ctx or context(), force_trigger=force))


def test_callable_runs_at_1028_and_sorts_current_targets():
    async def run():
        game = FakeGame(targets=[target(3, 30), target(2, 2), target(1, 11)])
        result = await arena_module().ArenaTask(game, now=lambda: moment())(context())
        assert result.status == "success"
        assert game.mutations() == [("challenge", 2)]
        assert game.state_reads == 2
        assert game.tickets == 0
    asyncio.run(run())


@pytest.mark.parametrize("now", [moment(10, 27, 59), moment(10, 30), moment(10, 31)])
def test_formal_run_outside_window_stays_waiting(now):
    game = FakeGame()
    assert execute(game, now=lambda: now).status == "waiting"
    assert not game.calls


def test_utc_clock_uses_beijing_window():
    game = FakeGame()
    utc_now = moment().astimezone(timezone.utc)
    assert execute(game, now=lambda: utc_now).status == "success"
    assert game.mutations() == [("challenge", 1)]


def test_naive_clock_is_rejected_before_ui_operations():
    game = FakeGame()
    with pytest.raises(ValueError, match="时区"):
        execute(game, now=lambda: moment().replace(tzinfo=None))
    assert not game.calls


def test_context_deadline_takes_precedence_over_later_schedule_end():
    game = FakeGame()
    ctx = context(window_end=moment(10, 28, 30))
    assert execute(game, ctx, now=lambda: moment(10, 28, 30)).status == "waiting"
    assert not game.calls


def test_schedule_end_still_applies_if_context_deadline_is_later():
    game = FakeGame()
    ctx = context(window_end=moment(10, 31))
    assert execute(game, ctx, now=lambda: moment(10, 30)).status == "waiting"
    assert not game.calls


def test_force_only_bypasses_time_window():
    game = FakeGame()
    assert execute(game, now=lambda: moment(12, 0), force=True).status == "success"
    assert game.mutations() == [("challenge", 1)]
    empty = FakeGame(tickets=0, refresh_remaining=3)
    assert execute(empty, context(excluded=[1]), now=lambda: moment(12, 0), force=True).status == "waiting"
    assert not empty.mutations()


def test_config_normalizes_hash_ids_and_current_target_exclusion():
    ctx = context(excluded=["测试甲#0002", 2, " #1 "])
    assert ctx.task.params["excluded_player_ids"] == [2, 1]
    game = FakeGame(targets=[target(2, 1), target(1, 2), target(3, 3)])
    assert execute(game, ctx).status == "success"
    assert game.mutations() == [("challenge", 3)]


@pytest.mark.parametrize("unranked", [None, 0, -1, False, "1"])
def test_missing_or_nonpositive_rank_sorts_last(unranked):
    game = FakeGame(targets=[target(1, unranked), target(2, 100)])
    execute(game)
    assert game.mutations() == [("challenge", 2)]


def test_unranked_target_remains_eligible_after_ranked_targets_excluded():
    game = FakeGame(targets=[target(1), target(2, 1)])
    execute(game, context(excluded=[2]))
    assert game.mutations() == [("challenge", 1)]


def test_refreshes_only_if_current_highest_two_are_both_excluded():
    game = FakeGame(targets=[target(3, 3), target(2, 2), target(1, 1)], refresh_remaining=2)
    game.refresh_states = [
        {"targets": [target(2, 1), target(1, 2), target(4, 4)]},
        {"targets": [target(5, 1), target(1, 2), target(2, 3)]},
    ]
    result = execute(game, context(excluded=["甲#1", "乙#2"]))
    assert result.status == "success"
    assert game.mutations() == [("refresh", None), ("refresh", None), ("challenge", 5)]
    assert game.refresh_remaining == 0
    assert game.tickets == 0


def test_refresh_stops_when_either_highest_target_is_not_excluded():
    game = FakeGame(targets=[target(1, 1), target(2, 2)], refresh_remaining=3)
    game.refresh_states = [{"targets": [target(1, 1), target(3, 2), target(4, 3)]}]
    execute(game, context(excluded=[1, 2]))
    assert game.mutations() == [("refresh", None), ("challenge", 3)]
    assert game.refresh_remaining == 2


def test_one_excluded_highest_never_triggers_refresh():
    game = FakeGame(targets=[target(1, 1), target(2, 2)], refresh_remaining=2)
    execute(game, context(excluded=[1]))
    assert game.mutations() == [("challenge", 2)]
    assert game.refresh_remaining == 2


def test_single_excluded_candidate_does_not_count_as_highest_two():
    game = FakeGame(refresh_remaining=2)
    assert execute(game, context(excluded=[1])).status == "waiting"
    assert not game.mutations()


def test_when_refresh_is_exhausted_selects_best_remaining_target():
    game = FakeGame(targets=[target(4, 4), target(1, 1), target(3, 3), target(2, 2)])
    execute(game, context(excluded=[1, 2]))
    assert game.mutations() == [("challenge", 3)]


def test_refresh_exhaustion_falls_back_to_current_remaining_target():
    game = FakeGame(targets=[target(1, 1), target(2, 2), target(3, 3)], refresh_remaining=1)
    game.refresh_states = [{"targets": [target(1, 1), target(2, 2), target(4, 4)]}]
    execute(game, context(excluded=[1, 2]))
    assert game.mutations() == [("refresh", None), ("challenge", 4)]


@pytest.mark.parametrize("targets,excluded", [([], []), ([target(1), target(2)], [1, 2])])
def test_no_eligible_target_waits_without_challenging(targets, excluded):
    game = FakeGame(targets=targets)
    assert execute(game, context(excluded=excluded)).status == "waiting"
    assert not game.mutations()


def test_no_tickets_never_refreshes_or_challenges():
    game = FakeGame(targets=[target(1, 1), target(2, 2)], tickets=0, refresh_remaining=10)
    assert execute(game, context(excluded=[1, 2])).status == "waiting"
    assert not game.mutations()


def test_continuous_rereads_current_targets_and_stops_when_tickets_end():
    game = FakeGame(tickets=3)
    def after(game):
        next_id = 4 - game.tickets
        game.targets = [target(next_id, 1)]
    game.on_challenge = after
    assert execute(game).status == "success"
    assert game.mutations() == [("challenge", 1), ("challenge", 2), ("challenge", 3)]
    assert game.state_reads == 4
    assert game.tickets == 0


def test_continuous_false_stops_after_one_verified_challenge():
    game = FakeGame(tickets=3)
    assert execute(game, context(continuous=False)).status == "success"
    assert game.mutations() == [("challenge", 1)]
    assert game.state_reads == 2
    assert game.tickets == 2


def test_failed_target_is_excluded_for_this_round_but_not_persisted():
    async def run():
        game = FakeGame(targets=[target(1, 1), target(2, 2)], tickets=2)
        game.replies = [{"confirmed": True, "win": False}, {"confirmed": True, "win": True}]
        ctx = context()
        handler = arena_module().ArenaTask(game, now=lambda: moment())
        assert (await handler(ctx)).status == "success"
        assert game.mutations() == [("challenge", 1), ("challenge", 2)]
        assert ctx.task.params["excluded_player_ids"] == []
        game.tickets = 1
        await handler(ctx)
        assert game.mutations()[-1] == ("challenge", 1)
    asyncio.run(run())


@pytest.mark.parametrize("reply", [{"confirmed": False, "win": True}, {"win": True},
                                    {"confirmed": 1, "win": True}, {"confirmed": True},
                                    {"confirmed": True, "win": "false"}, None])
def test_unknown_receipt_is_not_retried_in_this_handler(reply):
    async def run():
        game = FakeGame(tickets=2)
        game.replies = [reply]
        handler = arena_module().ArenaTask(game, now=lambda: moment())
        with pytest.raises(ExecutionUncertain):
            await handler(context())
        assert game.mutations() == [("challenge", 1)]
        before = list(game.calls)
        with pytest.raises(ExecutionUncertain):
            await handler(context())
        assert game.calls == before
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["challenge_unknown", "refresh_unknown", "challenge_exception"])
def test_unknown_ui_execution_never_retries(failure):
    async def run():
        game = FakeGame(targets=[target(1, 1), target(2, 2)], tickets=2, refresh_remaining=2)
        game.failure = failure
        ctx = context(excluded=[1, 2] if failure == "refresh_unknown" else [])
        handler = arena_module().ArenaTask(game, now=lambda: moment())
        with pytest.raises(ExecutionUncertain):
            await handler(ctx)
        assert len(game.mutations()) == 1
        previous = list(game.calls)
        with pytest.raises(ExecutionUncertain):
            await handler(ctx)
        assert game.calls == previous
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["state_reject", "challenge_reject", "refresh_reject"])
def test_explicit_rejection_returns_waiting_without_repeating(failure):
    game = FakeGame(targets=[target(1, 1), target(2, 2)], refresh_remaining=2)
    game.failure = failure
    ctx = context(excluded=[1, 2] if failure == "refresh_reject" else [])
    assert execute(game, ctx).status == "waiting"
    assert len(game.mutations()) <= 1


def test_challenge_ticket_count_must_decrease_even_if_not_continuous():
    game = FakeGame(tickets=2)
    game.challenge_consumes = False
    with pytest.raises(ExecutionUncertain, match="挑战券"):
        execute(game, context(continuous=False))
    assert game.mutations() == [("challenge", 1)]


def test_refresh_count_must_decrease_before_any_challenge():
    game = FakeGame(targets=[target(1, 1), target(2, 2)], refresh_remaining=2)
    game.refresh_consumes = False
    game.refresh_states = [{"targets": [target(3, 1)]}]
    with pytest.raises(ExecutionUncertain, match="刷新"):
        execute(game, context(excluded=[1, 2]))
    assert game.mutations() == [("refresh", None)]


def test_run_starts_and_ends_in_hall():
    async def run():
        game = FakeGame()
        await arena_module().ArenaTask(game, now=lambda: moment())(context())
        assert game.calls[0] == ("home", None)
        assert game.calls[-1] == ("home", None)
    asyncio.run(run())


def test_home_refusal_before_challenge_waits_without_attacking():
    async def run():
        game = FakeGame()
        game.failure = "home_reject"
        assert (await arena_module().ArenaTask(game, now=lambda: moment())(context())).status == "waiting"
        assert not game.mutations()
    asyncio.run(run())


def test_stop_before_run_prevents_all_ui_operations_even_for_force():
    game = FakeGame()
    assert execute(game, context(stop=lambda: True), force=True).status == "waiting"
    assert not game.calls


@pytest.mark.parametrize("operation", ["state", "refresh", "challenge"])
def test_stop_is_checked_again_before_each_new_mutation(operation):
    game = FakeGame(targets=[target(1, 1), target(2, 2), target(3, 3)], tickets=3,
                    refresh_remaining=2)
    stopped = False
    def request_stop(game):
        nonlocal stopped
        stopped = True
    setattr(game, "on_" + operation, request_stop)
    ctx = context(excluded=[1, 2] if operation == "refresh" else [], stop=lambda: stopped)
    assert execute(game, ctx).status == "waiting"
    expected = [] if operation == "state" else [(operation, None if operation == "refresh" else 1)]
    assert game.mutations() == expected
    if operation == "challenge":
        assert game.state_reads == 2


@pytest.mark.parametrize("operation", ["state", "refresh", "challenge"])
def test_1030_is_checked_after_state_refresh_and_challenge(operation):
    game = FakeGame(targets=[target(1, 1), target(2, 2), target(3, 3)], tickets=3,
                    refresh_remaining=2)
    now = moment(10, 29, 59)
    def end_window(game):
        nonlocal now
        now = moment(10, 30)
    setattr(game, "on_" + operation, end_window)
    ctx = context(excluded=[1, 2] if operation == "refresh" else [])
    assert execute(game, ctx, now=lambda: now).status == "waiting"
    expected = [] if operation == "state" else [(operation, None if operation == "refresh" else 1)]
    assert game.mutations() == expected


def test_step_limit_bounds_run_despite_resource_replenishment():
    game = FakeGame(targets=[target(1, 1), target(2, 2), target(3, 3)], tickets=3,
                    refresh_remaining=1)
    def replenish_refresh(game):
        game.refresh_remaining = 1
        game.targets = [target(1, 1), target(2, 2), target(3, 3)]
    def present_eligible(game):
        game.targets = [target(3, 1)]
    game.on_challenge = replenish_refresh
    game.on_refresh = present_eligible
    handler = arena_module().ArenaTask(game, now=lambda: moment())
    handler.MAX_STEPS = 3
    result = asyncio.run(handler(context(excluded=[1, 2])))
    assert result.status == "waiting"
    assert game.mutations() == [("refresh", None), ("challenge", 3), ("refresh", None)]


def test_missing_continuous_param_defaults_to_all_available_tickets():
    raw = load_config().raw
    raw["tasks"]["arena"]["params"].pop("continuous", None)
    ctx = TaskContext(parse_config(raw).tasks["arena"], moment(10, 30), lambda: False)
    game = FakeGame(tickets=2)
    assert execute(game, ctx).status == "success"
    assert game.mutations() == [("challenge", 1), ("challenge", 1)]
    assert game.tickets == 0


def test_all_targets_failed_stops_without_retrying_the_same_player():
    game = FakeGame(tickets=2)
    game.replies = [{"confirmed": True, "win": False}]
    assert execute(game).status == "waiting"
    assert game.mutations() == [("challenge", 1)]
    assert game.tickets == 1


@pytest.mark.parametrize("operation", ["refresh", "challenge"])
def test_cancel_during_ui_operation_blocks_direct_handler_reuse(operation):
    async def run():
        entered = asyncio.Event()
        game = FakeGame(targets=[target(1, 1), target(2, 2)], tickets=2, refresh_remaining=2)
        original = getattr(game, "arena_" + operation)
        async def pending(*args):
            await original(*args)
            entered.set()
            await asyncio.Event().wait()
        setattr(game, "arena_" + operation, pending)
        ctx = context(excluded=[1, 2] if operation == "refresh" else [])
        handler = arena_module().ArenaTask(game, now=lambda: moment())
        job = asyncio.create_task(handler(ctx))
        await entered.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        setattr(game, "arena_" + operation, original)
        previous = list(game.calls)
        with pytest.raises(ExecutionUncertain):
            await handler(ctx)
        assert game.calls == previous
    asyncio.run(run())


def test_post_challenge_rejected_state_read_is_uncertain_not_waiting():
    game = FakeGame(tickets=2)
    def reject_read(game):
        game.failure = "state_reject"
    game.on_challenge = reject_read
    with pytest.raises(ExecutionUncertain):
        execute(game)
    assert game.mutations() == [("challenge", 1)]


@pytest.mark.parametrize("field,bad", [("tickets", None), ("tickets", -1), ("tickets", True),
                                       ("refresh_remaining", None), ("refresh_remaining", -1)])
def test_unconfirmed_initial_resource_counts_wait_before_mutating(field, bad):
    game = FakeGame()
    setattr(game, field, bad)
    assert execute(game).status == "waiting"
    assert not game.mutations()


def test_business_logs_actions_and_errors_without_candidate_dump(caplog):
    game = FakeGame(targets=[dict(target(1, 1), private_name="不应记录的候选名称")])
    with caplog.at_level(logging.INFO, logger="plugin_manager.arena"):
        execute(game)
    entries = [entry for entry in caplog.records if entry.name == "plugin_manager.arena"]
    assert entries
    assert "挑战" in caplog.text
    assert "不应记录的候选名称" not in caplog.text
    caplog.clear()
    game = FakeGame()
    game.replies = [{"confirmed": False}]
    with caplog.at_level(logging.INFO, logger="plugin_manager.arena"):
        with pytest.raises(ExecutionUncertain):
            execute(game)
    assert any(entry.levelno >= logging.ERROR and entry.name == "plugin_manager.arena"
               for entry in caplog.records)
