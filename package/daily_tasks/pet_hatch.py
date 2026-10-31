"""Fill incubators and the unlocked waiting queue in descending item quality."""
from .scheduler import TaskResult, ExecutionUncertain

PET_EGGS = (
    (400001, '凡俗阴契'), (400002, '稀有阴契'), (400003, '珍宝阴契'), (400004, '绝世阴契'),
    (400005, '限定·冥河阴契'), (400006, '限定·画皮阴契'), (400007, '限定·春节阴契'),
    (400008, '限定·捞尸阴契'), (400009, '限定·端午阴契'), (400010, '限定·周年阴契'),
    (400011, '限定·木偶阴契'), (400012, '限定·织魂阴契'),
)


class PetHatchTask:
    def __init__(self, game):
        self.game = game

    @staticmethod
    def configuration_issue(params):
        return '' if params.get('item_ids') else '请先选择要自动解封的阴契'

    async def run(self, ctx, *, force_trigger=False):
        selected = ctx.task.params.get('item_ids', [])
        issue = self.configuration_issue(ctx.task.params)
        if issue:
            return TaskResult('waiting', issue)
        if ctx.stop_requested():
            return TaskResult('waiting', '已请求停止')
        placed = claimed = 0
        opened = False
        info = {}
        for _ in range(24):
            if ctx.stop_requested():
                break
            info = await self.game.pet_hatch_state(selected)
            actionable = info.get('claim_slot') or info.get('item_id') and info.get('can_place')
            if actionable and not opened:
                await self.game.home()
                opened = True
            if info.get('claim_slot'):
                result = await self.game.pet_hatch_claim(info['claim_slot'])
                claimed += 1
            elif info.get('item_id') and info.get('can_place'):
                result = await self.game.pet_hatch_start(info['item_id'])
                placed += 1
            else:
                break
            if not isinstance(result, dict) or result.get('confirmed') is not True:
                raise ExecutionUncertain('阴契解封操作结果未确认，不重复执行')
        if opened:
            await self.game.home()
        # Bag/slot reads are passive. Wake for completed slots rather than reopening
        # the pet page every minute; inventory can be replenished between runs.
        remaining = info.get('remaining_seconds')
        delay = max(1, remaining) if isinstance(remaining, (int, float)) and remaining > 0 else 1800
        if not info.get('item_id'):
            delay = min(delay, 1800)
        message = (f'阴契：已领取{claimed}次，已放入解封槽或队列{placed}个' if placed or claimed else
                   '所选阴契不足，暂不解封' if not info.get('item_id') else '等待解封槽／队列空位')
        return TaskResult('success' if placed or claimed else 'waiting', message, delay)
