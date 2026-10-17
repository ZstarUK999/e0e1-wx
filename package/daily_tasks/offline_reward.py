"""挂机收益：只按正常UI领取，收益与贪财无关，不动三尸/鬼仆/法器。"""

from __future__ import annotations

import json
from pathlib import Path

from .energy import EnergyTask, _finite_number
from .scheduler import ExecutionUncertain, RetryableTaskError, TaskContext, TaskResult


class OfflineRewardTask(EnergyTask):
    def __init__(self, game, journal_path: Path | None = None) -> None:
        super().__init__(game, journal_path)
        self.uncertain = ""

    async def __call__(self, ctx: TaskContext) -> TaskResult:
        return await self.run(ctx)

    async def run(self, ctx: TaskContext, *, force_trigger: bool = False) -> TaskResult:
        if self.uncertain:
            raise ExecutionUncertain(self.uncertain)
        if self.pending_original is not None or (self.journal_path is not None and
                (self.journal_path.exists() or self.journal_path.is_symlink())):
            raise ExecutionUncertain("存在未确认的领取记录，先核对当前会话，不自动重试")
        info = await self.game.reward_info()
        elapsed = _finite_number(info["elapsed"], "挂机累计时间")
        minimum = _finite_number(info["minimum"], "挂机领取最低时间")
        if elapsed < 0 or minimum < 0:
            raise RetryableTaskError("挂机累计时间或最低时间无效")
        threshold = minimum if force_trigger else max(ctx.task.params.get("claim_interval_seconds", 3600), minimum)
        if elapsed < threshold:
            # 没到阈值就按「还差多久」安排下次检查，不再每分钟空跑一次。
            remaining = min(max(threshold - elapsed, 60.0), 3600.0)
            return TaskResult(
                "waiting",
                f"挂机累计{elapsed:g}秒，未达领取阈值{threshold:g}秒，{remaining:g}秒后再检查",
                remaining,
            )
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        # 领取与贪财无关：不切三尸/法器，也不换阵眼，只回大厅后领取。
        async with self.game.transaction(self.journal_path):
            try:
                await self.game.home()
            except RetryableTaskError as exc:
                return TaskResult("waiting", str(exc), ctx.task.retry_seconds)
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            try:
                return await self.perform(ctx, 0)
            except RetryableTaskError as exc:
                return TaskResult("waiting", str(exc), ctx.task.retry_seconds)

    async def _block_repeat(self, reason: str) -> ExecutionUncertain:
        """领取结果未知时留下记录：重启也不重复领取。"""
        self.uncertain = reason
        if self.journal_path is not None and not (self.journal_path.exists() or self.journal_path.is_symlink()):
            record = {"reason": reason, "selection": await self.game.capture()}
            with open(self.journal_path, "w", encoding="utf-8") as file:
                json.dump(record, file, ensure_ascii=False)
        return ExecutionUncertain(reason)

    async def perform(self, ctx: TaskContext, best_score: float) -> TaskResult:
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        try:
            receipt = await self.game.claim_reward()
        except RetryableTaskError:
            raise  # 明确拒绝：等待下次，不算未知
        except ExecutionUncertain as exc:
            raise await self._block_repeat(str(exc)) from exc
        except Exception as exc:
            raise await self._block_repeat(f"领取结果未确认：{exc}") from exc
        if not isinstance(receipt, dict) or receipt.get("claimed") is not True:
            raise await self._block_repeat("挂机收益领取未获得明确成功回执，不重复调用")
        return TaskResult("success", "挂机收益已领取")
