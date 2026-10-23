"""选择平台后的单次游戏启动，复用重开游戏的图片导航。"""
from __future__ import annotations

import asyncio
import logging
import threading

import psutil

from .wechat_image_launch import WechatImageLauncher, process_name

LOG = logging.getLogger('plugin_manager')


class DouyinImageLauncher(WechatImageLauncher):
    images = WechatImageLauncher.images.with_name('douyin_images')
    template_names = ('miniapps_active', 'miniapps_inactive', 'game')
    navigation = (('miniapps_active', 'miniapps_inactive', '小游戏入口'),)

    def select(self, window, active, inactive, label):
        super().select(window, active, inactive, label)
        # 小游戏页面需要时间加载，等待完成后再查找并点击游戏图标。
        deadline = self.clock() + 5
        while self.clock() < deadline:
            self.check_cancel()
            self.sleep(min(.1, deadline - self.clock()))

    def prepare(self):
        self.main_window()
        LOG.info('抖音图像启动预检查通过：小游戏入口和游戏图标已就绪')

    def main_window(self):
        self.check_cancel()
        windows = []
        for window in self.gui.getAllWindows():
            if window.title not in ('抖音', '抖音电脑版', 'Douyin'):
                continue
            try:
                if process_name(window).name().lower() == 'douyin.exe':
                    windows.append(window)
            except (psutil.Error, OSError, RuntimeError):
                continue
        if len(windows) != 1:
            raise RuntimeError('无法唯一识别抖音主窗口，请保持抖音已登录且只有一个主窗口')
        return windows[0]

    def game_windows(self):
        windows = []
        for window in self.gui.getWindowsWithTitle('遗弃之地'):
            try:
                proc = process_name(window)
                if proc.name().lower() == 'douyin.exe' or 'douyin' in proc.exe().lower():
                    windows.append(window)
            except (psutil.Error, OSError, RuntimeError):
                continue
        return windows


async def ensure_game_started(platform, *, before_open=None, factory=None):
    """已有目标游戏窗口则保留；缺失时准备监听后只点击一次入口。"""
    factory = factory or (WechatImageLauncher if platform == '微信' else DouyinImageLauncher)
    cancel = threading.Event()
    launcher = await asyncio.to_thread(factory, cancel=cancel)
    if await asyncio.to_thread(launcher.game_windows):
        return False
    await asyncio.to_thread(launcher.prepare)
    if before_open:
        await before_open()

    def open_if_missing():
        if not launcher.game_windows():
            launcher.open_game()

    task = asyncio.create_task(asyncio.to_thread(open_if_missing))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        try:
            await task
        except Exception:
            pass
        raise
    LOG.info('%s启动检查完成，等待游戏连接', platform)
    return True
