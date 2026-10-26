"""游戏客户区持续纯白/纯黑确认，连接仍存活时也能恢复。"""
from __future__ import annotations

import asyncio
import logging
import time

LOG = logging.getLogger('plugin_manager')
RESTART_MAX_RETRIES = 10
RESTART_RETRY_SECONDS = 20.0


class BlankScreenRecovery:
    def __init__(self, *, clock=time.monotonic, capture=None, restart=None, sleep=asyncio.sleep):
        self.clock = clock
        self.capture = capture or self._capture
        self.restart = restart
        self.sleep = sleep
        self.last_active = None
        self.candidate = None
        self.since = 0
        self.samples = 0
        self.next_check = 0
        self.next_restart = 0
        self.restarting = False
        self.disconnected = False

    async def _capture(self):
        from .wechat_image_launch import WechatImageLauncher
        return await asyncio.to_thread(lambda: WechatImageLauncher().blank_screen(focus=self.disconnected))

    def observe(self, active):
        if active:
            self.last_active = self.clock()

    async def poll(self, *, active, disconnected, kicked, closing):
        self.observe(active)
        now = self.clock()
        eligible = active or self.last_active is not None and now-self.last_active <= 120
        if closing or kicked or not eligible:
            self.candidate = None
            self.samples = 0
            return
        if self.restarting or now < self.next_check or now < self.next_restart:
            return
        self.next_check = now + 5
        self.disconnected = disconnected
        try:
            result = await self.capture()
        except Exception:
            self.candidate, self.samples = None, 0
            raise
        now = self.clock()
        if not result:
            self.candidate = None
            self.samples = 0
            return
        if result != self.candidate:
            self.candidate, self.since, self.samples = result, now, 1
            LOG.info('检测到游戏客户区纯%s，开始连续15秒确认：窗口=%s，断线=%s',
                     {'white': '白', 'black': '黑'}.get(result[1], result[1]), result[0], disconnected)
            return
        self.samples += 1
        if self.samples < 3 or now-self.since < 15:
            return
        # 同一轮恢复失败后继续完整重开，不依赖已消失的旧窗口再次触发。
        self.candidate, self.samples = None, 0
        self.restarting = True
        try:
            LOG.warning('游戏客户区持续纯%s %.1f秒，开始图像重开：窗口=%s，断线=%s',
                        {'white': '白', 'black': '黑'}.get(result[1], result[1]), now-self.since, result[0], disconnected)
            for attempt in range(RESTART_MAX_RETRIES + 1):
                try:
                    await self.restart()
                    return
                except Exception as exc:
                    if attempt >= RESTART_MAX_RETRIES:
                        LOG.error('图像重开已用尽%d次重试：%s', RESTART_MAX_RETRIES, exc)
                        raise
                    LOG.warning('图像重开失败：%s；%.0f秒后重试（第%d/%d次）',
                                exc, RESTART_RETRY_SECONDS, attempt + 1, RESTART_MAX_RETRIES)
                    await self.sleep(RESTART_RETRY_SECONDS)
        finally:
            # 整轮结束后再冷却，避免长时间重试耗尽原来的冷却时间。
            self.next_restart = self.clock() + 300
            self.restarting = False
