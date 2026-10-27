"""微信图像导航：每一步确认选中状态，只在微信主窗口内匹配。"""
from __future__ import annotations

import ctypes
import logging
from pathlib import Path
import time
import threading
import psutil

LOG = logging.getLogger('plugin_manager')
IMAGES = Path(__file__).with_name('wechat_images')
TEMPLATES = ('sidebar_active', 'sidebar_inactive', 'miniapps_active', 'miniapps_inactive', 'game',
             'sidebar_active_red_dot', 'sidebar_inactive_red_dot')


def desktop():
    # 与 PlayBot 一致，在导入截图库前启用 DPI 感知。
    ctypes.windll.user32.SetProcessDPIAware()
    import pyautogui
    import cv2  # confidence 匹配必须有 OpenCV；缺依赖时在关闭游戏前失败。
    pyautogui.FAILSAFE = True
    return pyautogui


def process_name(window):
    import psutil
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(window._hWnd), ctypes.byref(pid))
    return psutil.Process(pid.value)


class WechatImageLauncher:
    images = IMAGES
    template_names = TEMPLATES
    navigation = (("sidebar_active", "sidebar_inactive", "小程序入口"),
                  ("miniapps_active", "miniapps_inactive", "小程序页面"))

    def __init__(self, gui=None, *, clock=time.monotonic, sleep=time.sleep, cancel=None):
        self.gui = gui or desktop()
        self.clock, self.sleep = clock, sleep
        self.cancel = cancel or threading.Event()
        self.templates = {}
        self._scaled_templates = {}
        from PIL import Image
        for name in self.template_names:
            with Image.open(self.images / (name + '.png')) as image:
                self.templates[name] = image.convert('RGB')

    def main_window(self):
        self.check_cancel()
        windows = []
        for window in self.gui.getAllWindows():
            if window.title not in ('微信', 'WeChat', 'Weixin'):
                continue
            try:
                if process_name(window).name().lower() in ('weixin.exe', 'wechat.exe'):
                    windows.append(window)
            except (psutil.Error, OSError, RuntimeError):
                continue
        if len(windows) != 1:
            raise RuntimeError('无法唯一识别微信主窗口，请保持微信已登录且只有一个主窗口')
        return windows[0]

    def prepare(self):
        self.main_window()
        LOG.info('微信图像重开预检查通过：普通及红点模板、桌面依赖已就绪')

    def game_windows(self):
        windows = []
        for window in self.gui.getWindowsWithTitle('遗弃之地'):
            try:
                proc = process_name(window)
                path = proc.exe().lower()
                if proc.name().lower() == 'wechatappex.exe' and 'radiumwmpf' in path and 'wxwork' not in path:
                    windows.append(window)
            except (psutil.Error, OSError, RuntimeError):
                continue
        return windows

    def close_game(self):
        self.check_cancel()
        windows = self.game_windows()
        if len(windows) > 1:
            raise RuntimeError('检测到多个遗弃之地窗口，无法确定要关闭的实例')
        if windows:
            windows[0].close()
        deadline = self.clock() + 15
        while self.game_windows():
            self.check_cancel()
            if self.clock() >= deadline:
                raise RuntimeError('游戏窗口关闭超时，停止重开')
            self.sleep(.25)
        LOG.info('微信旧游戏窗口已关闭')

    def focus(self, window):
        self.check_cancel()
        if window.isMinimized:
            window.restore()
        if not window.isActive:
            window.activate()
            self.sleep(.3)
        if not window.isActive:
            raise RuntimeError('微信窗口无法置前，停止图像点击')

    def locate(self, name, window):
        return self.locate_many((name,), window).get(name)

    def locate_many(self, names, window):
        """Compare navigation states on one frame, at each DPI scale together."""
        self.focus(window)
        region = (window.left, window.top, window.width, window.height)
        shot = self.gui.screenshot(region=region)
        variants = [(name, variant) for name in names
                    for variant in (name, name + '_red_dot') if variant in self.templates]
        for scale in (1, .8, 1.25, 1.5, 2, 2/3):
            self.check_cancel()
            matches = {}
            for name, variant in variants:
                if name in matches:
                    continue
                key = (variant, scale)
                if key not in self._scaled_templates:
                    image = self.templates[variant]
                    self._scaled_templates[key] = image if scale == 1 else image.resize(
                        (round(image.width * scale), round(image.height * scale)))
                point = self._match_template(self._scaled_templates[key], shot, window)
                if point:
                    matches[name] = point
            if matches:
                return matches
        return {}

    def _match_template(self, template, shot, window):
        if template.width > shot.width or template.height > shot.height:
            return None
        try:
            box = self.gui.locate(template, shot, confidence=.94, grayscale=False)
        except self.gui.ImageNotFoundException:
            box = None
        if box is not None:
            return (window.left + box.left + box.width//2, window.top + box.top + box.height//2)
        return None

    def _locate_image(self, image, shot, window):
        # 模板来自用户截图，同时兼容常见 DPI 缩放；保留彩色区分灰色和绿色。
        for scale in (1, .8, 1.25, 1.5, 2, 2/3):
            template = image if scale == 1 else image.resize((round(image.width*scale), round(image.height*scale)))
            if template.width > shot.width or template.height > shot.height:
                continue
            try:
                box = self.gui.locate(template, shot, confidence=.94, grayscale=False)
            except self.gui.ImageNotFoundException:
                box = None
            if box is not None:
                return (window.left + box.left + box.width//2, window.top + box.top + box.height//2)
        return None

    def select(self, window, active, inactive, label):
        deadline, clicked = self.clock() + 12, False
        while self.clock() < deadline:
            self.check_cancel()
            matches = self.locate_many((active,) if clicked else (active, inactive), window)
            if matches.get(active):
                LOG.info('微信图像导航已确认：%s', label)
                return
            if not clicked:
                point = matches.get(inactive)
                if point:
                    self.focus(window)
                    self.gui.click(*point)
                    clicked = True
            self.sleep(.3)
        raise RuntimeError(f'未检测到{label}绿色选中图标，停止重开')

    def open_game(self):
        window = self.main_window()
        for active, inactive, label in self.navigation:
            self.select(window, active, inactive, label)
        deadline = self.clock() + 12
        while self.clock() < deadline:
            self.check_cancel()
            point = self.locate('game', window)
            if point:
                self.focus(window)
                self.gui.click(*point)
                break
            self.sleep(.3)
        else:
            raise RuntimeError('小程序页面未找到遗弃之地图标，停止重开')
        # 只点击一次，窗口出现后由原有会话流程确认大厅加载。
        deadline = self.clock() + 20
        while self.clock() < deadline:
            self.check_cancel()
            if self.game_windows():
                LOG.info('已通过微信图片入口打开遗弃之地，等待大厅确认')
                return
            self.sleep(.3)
        raise RuntimeError('已点击遗弃之地，但未确认新游戏窗口；不会重复点击')

    def check_cancel(self):
        if self.cancel.is_set():
            raise RuntimeError('桌面重开已取消')

    def blank_screen(self, *, focus=True):
        windows = self.game_windows()
        if len(windows) != 1 or windows[0].isMinimized:
            return None
        window = windows[0]
        from ctypes import wintypes as W
        rect, point = W.RECT(), W.POINT()
        user = ctypes.windll.user32
        handle = ctypes.c_void_p(window._hWnd)
        if focus:
            self.focus(window)
        else:
            foreground = user.GetForegroundWindow
            foreground.restype = W.HWND
            if foreground() != window._hWnd:
                # A screenshot of an obscured window cannot prove a blank game.
                return None
        if not user.GetClientRect(handle, ctypes.byref(rect)) or not user.ClientToScreen(handle, ctypes.byref(point)):
            return None
        if rect.right < 200 or rect.bottom < 200:
            return None
        shot = self.gui.screenshot(region=(point.x, point.y, rect.right, rect.bottom))
        kind = classify_blank(shot)
        if kind:
            folder = Path('logs') / 'recovery'
            folder.mkdir(parents=True, exist_ok=True)
            shot.save(folder / ('blank_' + kind + '.png'))
        return (window._hWnd, kind) if kind else None


def classify_blank(image):
    """客户区至少 99% 像素近白/近黑才算纯色；排除标题栏。"""
    import numpy as np
    pixels = np.asarray(image.convert('RGB'))
    if (pixels.min(axis=2) >= 248).mean() >= .99:
        return 'white'
    if (pixels.max(axis=2) <= 7).mean() >= .99:
        return 'black'
    return None


def run_stage(mode, cancel=None):
    launcher = WechatImageLauncher(cancel=cancel)
    {'Prepare': launcher.prepare, 'WaitClosed': launcher.close_game, 'Open': launcher.open_game}[mode]()
