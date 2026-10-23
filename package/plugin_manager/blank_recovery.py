"""长期任务断线后的纯白/纯黑确认，不把普通断线当作重启理由。"""
from __future__ import annotations

import asyncio
import logging
import time

LOG = logging.getLogger('plugin_manager')


class BlankScreenRecovery:
    def __init__(self, *, clock=time.monotonic, capture=None, restart=None):
        self.clock = clock
        self.capture = capture or self._capture
        self.restart = restart
        self.last_active = None
        self.candidate = None
        self.since = 0
        self.samples = 0
        self.next_check = 0
        self.next_restart = 0
        self.restarting = False

    @staticmethod
    async def _capture():
        from .wechat_image_launch import WechatImageLauncher
        return await asyncio.to_thread(lambda: WechatImageLauncher().blank_screen())

    def observe(self, active):
        if active:
            self.last_active = self.clock()

    async def poll(self, *, active, disconnected, kicked, closing):
        self.observe(active)
        now = self.clock()
        eligible = active or self.last_active is not None and now-self.last_active <= 120
        if closing or kicked or not eligible or not disconnected:
            self.candidate = None
            self.samples = 0
            return
        if self.restarting or now < self.next_check or now < self.next_restart:
            return
        self.next_check = now + 5
        result = await self.capture()
        if not result:
            self.candidate = None
            self.samples = 0
            return
        if result != self.candidate:
            self.candidate, self.since, self.samples = result, now, 1
            return
        self.samples += 1
        if self.samples < 3 or now-self.since < 15:
            return
        # 一次失败至少冷却五分钟；不对同一次启动反复点击。
        self.next_restart = now + 300
        self.candidate, self.samples = None, 0
        self.restarting = True
        try:
            LOG.warning('长期任务断线且游戏客户区持续纯%s，开始图像重开', result[1])
            await self.restart()
        finally:
            self.restarting = False
