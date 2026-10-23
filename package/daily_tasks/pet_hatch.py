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

    async def run(self, ctx, *, force_trigger=False):
        selected = ctx.task.params.get('item_ids', [])
        if not selected:
            return TaskResult('waiting', '请先选择要自动解封的阴契')
        if ctx.stop_requested():
            return TaskResult('waiting', '已请求停止')
        await self.game.home()
        placed = claimed = 0
        info = {}
        for _ in range(24):
            if ctx.stop_requested():
                break
            info = await self.game.pet_hatch_state(selected)
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
        await self.game.home()
        delay = max(1, min(60, info.get('remaining_seconds') or 60))
        return TaskResult('success' if placed or claimed else 'waiting',
                          f'阴契：已领取{claimed}次，已放入解封槽或队列{placed}个' if placed or claimed else '等待所选阴契或解封槽／队列空位', delay)
