"""挂机收益处理器测试；仅使用内存游戏替身，不连接真实游戏。"""

import asyncio
import copy
import importlib
import json
from contextlib import asynccontextmanager

import pytest

from package.daily_tasks.config import Schedule, TaskConfig
from package.daily_tasks.scheduler import ExecutionUncertain, RetryableTaskError, TaskContext


def reward_module():
    try:
        return importlib.import_module("package.daily_tasks.offline_reward")
    except ModuleNotFoundError as exc:
        if exc.name != "package.daily_tasks.offline_reward":
            raise
        pytest.fail("OfflineRewardTask尚未实现")


def context(stop=lambda: False, params=None):
    task = TaskConfig("offline_reward", "挂机收益", True, 1, 120, 30,
                      Schedule("interval", 3600), params or {})
    return TaskContext(task, None, stop)


class FakeGame:
    def __init__(self, elapsed=3600, minimum=60):
        self.elapsed, self.minimum = elapsed, minimum
        self.selection = {"sanshi": 0, "artifact": 201, "plan": 1, "eye": 10}
        self.slots = [10, 11, 0, 0]
        self.original = self.snapshot()
        self.calls = []
        self.in_transaction = False
        self.failure = None
        self.claim_reply = {"claimed": True}
        self.on_select = None

    def snapshot(self):
        return {"role_id": 12345, "selection": copy.deepcopy(self.selection),
                "slots": self.slots[:], "formation": 1}

    @asynccontextmanager
    async def transaction(self, journal):
        assert not self.in_transaction
        self.in_transaction = True
        self.calls.append(("transaction", journal))
        try:
            yield
        finally:
            self.in_transaction = False

    async def reward_info(self):
        self.calls.append(("reward_info", None))
        if self.failure == "info":
            raise RetryableTaskError("挂机时间读取失败")
        return {"elapsed": self.elapsed, "minimum": self.minimum}

    async def inspect(self):
        self.calls.append(("inspect", None))
        return {"energy": 0, "maximum": 100, "safe": True}

    async def home(self):
        assert self.in_transaction
        self.calls.append(("home", None))
        if self.failure == "home":
            raise RetryableTaskError("战斗进行中，不能返回主界面")

    async def catalog(self, name):
        assert self.in_transaction
        self.calls.append(("catalog", name))
        return {"sanshi": [0, 1], "magic": [{"artifact": 201, "plan": 1},
                {"artifact": 201, "plan": 2}], "eye": 11}

    async def capture(self):
        assert self.in_transaction
        self.calls.append(("capture", None))
        return self.snapshot()

    async def set_eye(self, eye):
        assert self.in_transaction
        self.calls.append(("eye", eye))
        self.selection["eye"] = eye
        self.slots = [eye, 10, 0, 0]

    async def optimize(self):
        """驻留脚本按数据选方案：模拟选中贪财最高的已有组合。"""
        assert self.in_transaction
        self.calls.append(("optimize", None))
        choice = {"sanshi": 1, "artifact": 201, "plan": 2}
        self.selection.update(choice)
        if self.on_select:
            await self.on_select(choice)
        return {"choice": dict(choice), "gold": 100 * choice["sanshi"] + 10 * choice["plan"],
                "scores": [], "measured": []}

    async def select(self, choice):
        assert self.in_transaction
        self.calls.append(("select", copy.deepcopy(choice)))
        self.selection.update(choice)
        if self.on_select:
            await self.on_select(choice)
        return 100 * self.selection["sanshi"] + 10 * self.selection["plan"]

    async def claim_reward(self):
        assert self.in_transaction
        self.calls.append(("claim_reward", self.snapshot()))
        if self.failure == "unknown":
            raise ExecutionUncertain("领取响应丢失")
        if self.failure == "reject":
            raise RetryableTaskError("服务器明确拒绝领取")
        if self.failure == "exception":
            raise RuntimeError("领取响应解析失败")
        return self.claim_reply

    async def restore(self, original):
        assert self.in_transaction
        self.calls.append(("restore", copy.deepcopy(original)))
        if self.failure == "restore":
            raise ExecutionUncertain("恢复失败")
        self.selection = copy.deepcopy(original["selection"])
        self.slots = original["slots"][:]
        return self.snapshot()


@pytest.mark.parametrize("elapsed", [0, 3599])
def test_default_hour_threshold_never_switches_or_claims(elapsed):
    async def run():
        game = FakeGame(elapsed=elapsed)
        result = await reward_module().OfflineRewardTask(game)(context())
        assert result.status == "waiting"
        assert game.calls == [("reward_info", None)]
    asyncio.run(run())


def test_waiting_schedules_next_check_at_the_threshold_not_every_minute():
    """没到领取阈值时按剩余时间安排下次检查，不再每分钟空跑。"""
    async def run():
        game = FakeGame(elapsed=600)
        result = await reward_module().OfflineRewardTask(game)(context())
        assert result.status == "waiting"
        assert result.next_delay_seconds == 3000.0  # 3600 - 600
    asyncio.run(run())


def test_waiting_delay_is_clamped_so_it_never_tightens_or_exceeds_an_hour():
    async def run():
        near = await reward_module().OfflineRewardTask(FakeGame(elapsed=3599))(context())
        assert near.next_delay_seconds == 60.0
        far = await reward_module().OfflineRewardTask(FakeGame(elapsed=0))(
            context(params={"claim_interval_seconds": 7200})
        )
        assert far.next_delay_seconds == 3600.0
    asyncio.run(run())


@pytest.mark.parametrize("elapsed,minimum,interval", [(7199, 60, 7200), (4999, 5000, 3600)])
def test_threshold_is_larger_of_configured_interval_and_game_minimum(elapsed, minimum, interval):
    async def run():
        game = FakeGame(elapsed, minimum)
        result = await reward_module().OfflineRewardTask(game)(context(params={"claim_interval_seconds": interval}))
        assert result.status == "waiting"
        assert game.calls == [("reward_info", None)]
    asyncio.run(run())


@pytest.mark.parametrize("elapsed,minimum,force", [(3600, 60, False), (60, 60, True)])
def test_due_or_force_claims_once_without_touching_plans(elapsed, minimum, force):
    async def run():
        game = FakeGame(elapsed, minimum)
        handler = reward_module().OfflineRewardTask(game)
        result = await handler.run(context(), force_trigger=force)
        assert result.status == "success"
        assert result.message == "挂机收益已领取"
        claims = [value for name, value in game.calls if name == "claim_reward"]
        assert len(claims) == 1
        # 领取与贪财无关：三尸/法器/阵眼保持原样，用原配置直接领取。
        assert claims[0]["selection"] == game.original["selection"]
        assert claims[0]["slots"] == game.original["slots"]
        names = [name for name, _ in game.calls]
        assert names == ["reward_info", "transaction", "home", "claim_reward"]
        assert game.snapshot() == game.original
    asyncio.run(run())


def test_force_still_waits_for_game_minimum():
    async def run():
        game = FakeGame(elapsed=59, minimum=60)
        result = await reward_module().OfflineRewardTask(game).run(context(), force_trigger=True)
        assert result.status == "waiting"
        assert game.calls == [("reward_info", None)]
    asyncio.run(run())


def test_reward_info_read_failure_propagates_without_guessing():
    async def run():
        game = FakeGame()
        game.failure = "info"
        with pytest.raises(RetryableTaskError, match="挂机时间读取失败"):
            await reward_module().OfflineRewardTask(game)(context())
        assert game.calls == [("reward_info", None)]
    asyncio.run(run())


@pytest.mark.parametrize("elapsed,minimum", [(float("nan"), 60), (3600, float("inf")),
                                           (-1, 60), (3600, -1), ("3600", 60), (True, 60)])
def test_invalid_reward_clock_is_retryable_and_never_claims(elapsed, minimum):
    async def run():
        game = FakeGame(elapsed, minimum)
        with pytest.raises(RetryableTaskError):
            await reward_module().OfflineRewardTask(game)(context())
        assert game.calls == [("reward_info", None)]
    asyncio.run(run())


@pytest.mark.parametrize("reply", [{"claimed": False}, {}, None, {"claimed": 1}])
def test_missing_positive_claim_receipt_preserves_original_and_blocks_repeat(reply):
    async def run():
        game = FakeGame()
        game.claim_reply = reply
        handler = reward_module().OfflineRewardTask(game)
        with pytest.raises(ExecutionUncertain):
            await handler(context())
        assert handler.uncertain
        assert sum(name == "claim_reward" for name, _ in game.calls) == 1
        assert not any(name == "restore" for name, _ in game.calls)
        old_calls = copy.deepcopy(game.calls)
        with pytest.raises(ExecutionUncertain):
            await handler(context())
        assert game.calls == old_calls
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["unknown", "exception"])
def test_unknown_claim_preserves_journal_and_blocks_new_instance(tmp_path, failure):
    async def run():
        game = FakeGame()
        game.failure = failure
        path = tmp_path / "restore.json"
        handler = reward_module().OfflineRewardTask(game, path)
        with pytest.raises(ExecutionUncertain):
            await handler(context())
        assert json.loads(path.read_text(encoding="utf-8"))["reason"]
        assert not any(name == "capture" for name, _ in game.calls)
        assert sum(name == "claim_reward" for name, _ in game.calls) == 1
        assert not any(name == "restore" for name, _ in game.calls)
        old_calls = copy.deepcopy(game.calls)
        with pytest.raises(ExecutionUncertain):
            await reward_module().OfflineRewardTask(game, path)(context())
        assert game.calls == old_calls
    asyncio.run(run())


def test_confirmed_rejection_waits_without_changing_anything():
    async def run():
        game = FakeGame()
        game.failure = "reject"
        handler = reward_module().OfflineRewardTask(game)
        result = await handler(context())
        assert result.status == "waiting"
        assert "拒绝" in result.message
        assert game.snapshot() == game.original
        assert not handler.uncertain
    asyncio.run(run())


def test_blocked_home_never_switches_or_claims():
    async def run():
        game = FakeGame()
        game.failure = "home"
        result = await reward_module().OfflineRewardTask(game)(context())
        assert result.status == "waiting"
        assert not any(name in {"eye", "select", "claim_reward", "restore"} for name, _ in game.calls)
    asyncio.run(run())


def test_stop_before_transaction_never_switches_or_claims():
    async def run():
        game = FakeGame()
        result = await reward_module().OfflineRewardTask(game)(context(stop=lambda: True))
        assert result.status == "waiting"
        assert not any(name in {"transaction", "eye", "select", "claim_reward"} for name, _ in game.calls)
    asyncio.run(run())


def test_stop_after_home_never_claims():
    async def run():
        game = FakeGame()
        stopped = False
        original_home = game.home
        async def home():
            nonlocal stopped
            await original_home()
            stopped = True
        game.home = home
        handler = reward_module().OfflineRewardTask(game)
        result = await handler(context(stop=lambda: stopped))
        assert result.status == "waiting"
        assert not any(name == "claim_reward" for name, _ in game.calls)
        assert game.snapshot() == game.original
    asyncio.run(run())


def test_cancel_during_claim_leaves_no_repeat_and_no_journal(tmp_path):
    async def run():
        game = FakeGame()
        entered = asyncio.Event()
        original_claim = game.claim_reward
        async def claim():
            entered.set()
            await asyncio.Event().wait()
            return await original_claim()
        game.claim_reward = claim
        handler = reward_module().OfflineRewardTask(game, tmp_path / "restore.json")
        job = asyncio.create_task(handler(context()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert game.snapshot() == game.original
        assert not (tmp_path / "restore.json").exists()
    asyncio.run(run())
