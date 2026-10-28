"""Use only the native free summon button after its server-clock cooldown."""
from .scheduler import TaskResult, ExecutionUncertain


class FreeSummonTask:
    def __init__(self, game):
        self.game = game

    async def run(self, ctx, *, force_trigger=False):
        if ctx.stop_requested():
            return TaskResult('waiting', '已请求停止')
        info = await self.game.free_summon_state()
        remaining = info.get('remaining_seconds')
        if type(remaining) not in (int, float) or not 0 <= remaining <= 604800:
            raise ExecutionUncertain('免费召唤冷却状态未确认')
        if remaining > 0:
            return TaskResult('waiting', f'免费召唤冷却中，{remaining:.0f}秒后再检查', max(1, remaining))
        if ctx.stop_requested():
            return TaskResult('waiting', '已请求停止')
        await self.game.home()
        receipt = await self.game.free_summon()
        if not isinstance(receipt, dict) or receipt.get('confirmed') is not True:
            raise ExecutionUncertain('免费召唤结果未确认，不重复执行')
        await self.game.home()
        return TaskResult('success', '免费召唤已完成', max(1, receipt['cooldown_seconds']))
