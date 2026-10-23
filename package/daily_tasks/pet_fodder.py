"""Merge unprotected fodder through Human Realm using confirmed native UI actions."""
from .scheduler import ExecutionUncertain, TaskResult

REALMS = {2: '畜生道', 3: '饿鬼道', 4: '人道'}


def next_fodder_merge(pets):
    """Two zeroes -> two ones -> feed an unfinished seven -> two threes."""
    for quality in REALMS:
        group = sorted((p for p in pets if p.get('eligible') is True and p.get('quality') == quality
                        and type(p.get('progress')) is int and p['progress'] >= 0), key=lambda p: str(p['id']))
        by_progress = {n: [p for p in group if p['progress'] == n] for n in (0, 1, 3)}
        pair = None
        for n in (0, 1):
            if len(by_progress[n]) >= 2:
                pair = by_progress[n][:2]
                break
        if pair is None:
            unfinished = [p for p in group if p['progress'] >= 7]
            if unfinished and by_progress[3]:
                pair = [unfinished[0], by_progress[3][0]]
            elif len(by_progress[3]) >= 2:
                pair = by_progress[3][:2]
        if pair:
            return {'target_id': pair[0]['id'], 'material_id': pair[1]['id'], 'quality': quality,
                    'target_progress': pair[0]['progress'], 'material_progress': pair[1]['progress']}
    return None


class PetFodderTask:
    def __init__(self, game):
        self.game = game

    async def run(self, ctx, *, force_trigger=False):
        if ctx.stop_requested():
            return TaskResult('waiting', '已请求停止')
        await self.game.home()
        merged = advanced = 0
        while not ctx.stop_requested():
            snapshot = await self.game.pet_fodder_state()
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get('pets'), list):
                raise ExecutionUncertain('鬼仆合成状态未确认')
            pair = next_fodder_merge(snapshot['pets'])
            if pair is None:
                break
            if ctx.stop_requested():
                break
            result = await self.game.pet_fodder_merge(pair)
            if not isinstance(result, dict) or result.get('confirmed') is not True or type(result.get('advanced')) is not bool:
                raise ExecutionUncertain('鬼仆献祭结果未确认，停止自动合成，不重复执行')
            merged += 1
            advanced += result['advanced']
        await self.game.home()
        return TaskResult('success' if merged else 'waiting',
                          f'狗粮合成{merged}次，进阶{advanced}次；' + ('已停止' if ctx.stop_requested() else '畜生道至人道已处理完成'))
