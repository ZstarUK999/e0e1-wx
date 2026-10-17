"""驻留脚本的游戏操作封装：明确未执行的操作可重试，结果未知绝不重试。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from package.daily_tasks.scheduler import RetryableTaskError

LOG = logging.getLogger('plugin_manager')

# UI未获准时的重试次数；都失败就回大厅，让调度器继续下一个任务。
UI_RETRIES = 2
NO_RETRY_OPS = {'inspect', 'capture', 'quote', 'player_information', 'configure', 'stop', 'home', 'reward_info'}


class ResidentGame:
    def __init__(self, transport):
        self.transport = transport

    @asynccontextmanager
    async def transaction(self, journal):
        # 单实例GUI和控制器operation共同覆盖整轮，不创建恢复文件。
        yield

    async def _call(self, op, payload=None):
        """明确未执行/被拒绝的操作重试两次；结果未知(ExecutionUncertain)绝不重试。"""
        attempts = 1 if op in NO_RETRY_OPS else UI_RETRIES + 1
        for attempt in range(attempts):
            try:
                return await self.transport.call(op, payload)
            except RetryableTaskError as exc:
                LOG.warning('UI操作未获准（第%d/%d次）：%s，%s', attempt + 1, attempts, op, exc)
        LOG.error('UI操作连续%d次未执行，返回主界面后结束本轮：%s', attempts, op)
        try:
            await self.transport.call('home')
        except Exception as exc:
            LOG.warning('失败后返回主界面未成功：%s', exc)
        raise RetryableTaskError(f'{op} 连续{attempts}次未获准，已返回主界面')

    async def inspect(self): return await self.transport.call('inspect')
    async def catalog(self, name): return await self._call('catalog', {'name': name})
    async def optimize(self): return await self._call('optimize')
    async def capture(self): return await self.transport.call('capture')
    async def set_eye(self, eye): return await self._call('eye', {'eye': eye})
    async def select(self, choice): return await self._call('select', choice)
    async def home(self): return await self.transport.call('home')
    async def quote(self): return await self.transport.call('quote')
    async def sweep(self): return await self._call('sweep')
    async def restore(self, original): return await self._call('restore', {'original': original})
    async def reward_info(self): return await self.transport.call('reward_info')
    async def claim_reward(self): return await self._call('reward_claim')
    async def arena_state(self): return await self.transport.call('arena_state')
    async def arena_refresh(self): return await self._call('arena_refresh')
    async def arena_challenge(self, id): return await self._call('arena_challenge', {'id': id})
    async def tomb_state(self, kind): return await self.transport.call('tomb_state', {'kind': kind})
    async def tomb_collect(self, kind): return await self._call('tomb_collect', {'kind': kind})
    async def tomb_start(self, kind): return await self._call('tomb_start', {'kind': kind})
    async def tomb_recruit(self, kind): return await self._call('tomb_recruit', {'kind': kind})
    async def tomb_targets(self, kind, mode, refresh=True, minimum=0): return await self._call('tomb_targets', {'kind': kind, 'mode': mode, 'refresh': refresh, 'minimum': minimum})
    async def tomb_raid(self, kind, id): return await self._call('tomb_raid', {'kind': kind, 'id': id})
    async def tomb_fill(self, kind, id): return await self._call('tomb_fill', {'kind': kind, 'id': id})
    # 三尸合成：走 _call（只有"明确未执行/被拒绝"才重试，结果未知绝不重试）。
    # ⚠ desire_compose_once 故意不在这里：_call 失败后会 home()，那会把整批打断；
    #   合成失败该由批次自己决定是换档继续还是收尾，见 features/desire.py。
    async def desire_bag_stats(self): return await self.transport.call('desire_bag_stats')
    async def desire_compose_probe(self): return await self.transport.call('desire_compose_probe')
    async def desire_compose_open(self, kind): return await self._call('desire_compose_open', {'kind': kind})
    async def desire_compose_close(self): return await self._call('desire_compose_close')
