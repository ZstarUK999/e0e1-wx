"""斗法日常：按当前界面排名挑选，逐次确认刷新和挑战券消耗。"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import replace
from datetime import datetime

from .scheduler import BEIJING, ExecutionUncertain, RetryableTaskError, TaskContext, TaskResult

LOG = logging.getLogger("plugin_manager.arena")


def _state(value) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("targets"), list):
        raise RetryableTaskError("斗法候选界面尚未就绪")
    for name, label in (("tickets", "挑战券"), ("refresh_remaining", "刷新次数")):
        if type(value.get(name)) is not int or value[name] < 0:
            raise RetryableTaskError(f"斗法{label}未确认")
    return value


def _rank(target):
    rank = target.get("rank")
    return rank if type(rank) in (int, float) and rank > 0 and math.isfinite(rank) else math.inf


class ArenaTask:
    MAX_STEPS = 100

    def __init__(self, game, *, now=lambda: datetime.now(BEIJING)) -> None:
        self.game = game
        self.now = now
        self.blocked_reason = ""

    def _boundary(self, ctx: TaskContext, force_trigger: bool) -> TaskResult | None:
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止，未发起后续斗法操作")
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("斗法任务时钟必须包含时区")
        if force_trigger:
            return None
        now = now.astimezone(BEIJING)
        schedule = ctx.task.schedule
        if schedule.kind == "daily_window":
            start = datetime.combine(now.date(), schedule.start, BEIJING)
            end = datetime.combine(now.date(), schedule.end, BEIJING)
            if not start <= now < end:
                return TaskResult("waiting", "不在北京时间斗法窗口内")
        if ctx.window_end is not None and now >= ctx.window_end:
            return TaskResult("waiting", "斗法窗口已结束，未发起后续操作")
        return None

    async def __call__(self, ctx: TaskContext) -> TaskResult:
        return await self.run(ctx)

    async def run(self, ctx: TaskContext, *, force_trigger: bool = False) -> TaskResult:
        if self.blocked_reason:
            raise ExecutionUncertain(self.blocked_reason)
        boundary = self._boundary(ctx, force_trigger)
        if boundary is not None:
            return boundary
        try:
            return await self._run(ctx, force_trigger)
        except RetryableTaskError as exc:
            LOG.warning("斗法操作明确未执行，等待下次检查：%s", exc)
            return TaskResult("waiting", str(exc))
        except ExecutionUncertain as exc:
            self.blocked_reason = str(exc) or "斗法执行结果未知，需核对后再运行"
            LOG.error("斗法结果未确认，停止新操作：%s", self.blocked_reason)
            raise
        except asyncio.CancelledError:
            self.blocked_reason = "斗法流程取消，执行结果需核对，不自动重试"
            LOG.error(self.blocked_reason)
            raise
        except Exception as exc:
            self.blocked_reason = "斗法流程异常，执行结果需核对，不自动重试"
            LOG.error(self.blocked_reason)
            raise ExecutionUncertain(self.blocked_reason) from exc

    async def _run(self, ctx: TaskContext, force_trigger: bool) -> TaskResult:
        # 斗法从大厅开始；结束时同样回到大厅，失败只记录不改写结果。
        await self.game.home()
        result = await self._loop(ctx, force_trigger)
        # 只在正常收尾时回大厅；结果未确认的路径不再额外点击。
        try:
            await self.game.home()
        except RetryableTaskError as exc:
            LOG.warning("斗法结束后返回主界面暂不可用：%s", exc)
        else:
            result = replace(result, safe_to_resume=True)
        return result

    async def _loop(self, ctx: TaskContext, force_trigger: bool) -> TaskResult:
        state = _state(await self.game.arena_state())
        excluded = set(ctx.task.params.get("excluded_player_ids", []))
        continuous = ctx.task.params.get("continuous", True)
        budget = min(self.MAX_STEPS, state["tickets"] + state["refresh_remaining"])
        steps = completed = wins = 0
        while True:
            boundary = self._boundary(ctx, force_trigger)
            if boundary is not None:
                return boundary
            if state["tickets"] == 0:
                return TaskResult("success" if completed else "waiting",
                                  f"挑战券已用完；本轮完成{completed}次斗法，胜利{wins}次")
            if steps >= budget:
                return TaskResult("waiting", "本轮达到安全操作上限，等待下次检查")
            targets = sorted((item for item in state["targets"]
                              if isinstance(item, dict) and type(item.get("id")) is int and item["id"] > 0),
                             key=_rank)
            top_two_excluded = len(targets) >= 2 and all(item["id"] in excluded for item in targets[:2])
            if top_two_excluded and state["refresh_remaining"] > 0:
                boundary = self._boundary(ctx, force_trigger)
                if boundary is not None:
                    return boundary
                before = state["refresh_remaining"]
                LOG.info("当前最高两名均排除，发起正常斗法刷新；剩余刷新%d次", before)
                refreshed = await self.game.arena_refresh()
                try:
                    state = _state(refreshed)
                except RetryableTaskError as exc:
                    raise ExecutionUncertain("刷新后的斗法状态未确认，不重复刷新") from exc
                if state["refresh_remaining"] >= before:
                    raise ExecutionUncertain("刷新次数未确认下降，不重复刷新")
                steps += 1
                continue
            eligible = next((item for item in targets if item["id"] not in excluded), None)
            if eligible is None:
                return TaskResult("waiting", "当前没有未排除的斗法目标")
            boundary = self._boundary(ctx, force_trigger)
            if boundary is not None:
                return boundary
            before = state["tickets"]
            LOG.info("发起正常斗法挑战；剩余挑战券%d张", before)
            reply = await self.game.arena_challenge(eligible["id"])
            if (not isinstance(reply, dict) or reply.get("confirmed") is not True
                    or type(reply.get("win")) is not bool):
                raise ExecutionUncertain("斗法挑战结果未确认，不重复挑战")
            try:
                state = _state(await self.game.arena_state())
            except RetryableTaskError as exc:
                raise ExecutionUncertain("挑战后的挑战券状态未确认，不重复挑战") from exc
            if state["tickets"] >= before:
                raise ExecutionUncertain("挑战券未确认下降，不重复挑战")
            steps += 1
            completed += 1
            wins += int(reply["win"])
            if not reply["win"]:
                excluded.add(eligible["id"])
            LOG.info("斗法挑战已确认：%s；本轮完成%d次，剩余挑战券%d张",
                     "胜利" if reply["win"] else "失败，本轮暂排除该目标", completed, state["tickets"])
            boundary = self._boundary(ctx, force_trigger)
            if boundary is not None:
                return boundary
            if not continuous:
                return TaskResult("success", f"完成1次斗法，胜利{wins}次")
