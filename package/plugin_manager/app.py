"""插件管理器装配：路径、单实例、日志与窗口／运行服务的接线。

入口脚本只负责调用 main()；这里决定"怎么把各部件装起来"。
"""

from __future__ import annotations

import logging
import faulthandler
from .native_diagnostics import checkpoint, set_stream
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer

from package.runtime.instance_guard import InstanceGuard
from package.runtime.launch import run_gui

from .background import BackgroundExecutor
from . import updater
from . import runtime as runtime_module
from . import window as window_module
from .build_info import current as build_info
from .logging_setup import configure_logging
from .paths import default_config_path, lock_path, log_path
from .store import PluginConfigStore

LOG = logging.getLogger('plugin_manager')
APP_NAME = "e0e1-wx-plugins"


class PluginApplication:
    """插件管理器的一次运行：持有配置路径、单实例锁与文件日志。"""

    def __init__(self, config_path: Path | None = None, *, platform: str | None = 'wechat') -> None:
        if platform not in (None, 'wechat', 'douyin', 'androws'):
            raise ValueError('未知游戏平台')
        self.platform = platform
        self.config_path = Path(config_path) if config_path is not None else default_config_path()
        self.log_file = log_path(self.config_path)
        self._guard = InstanceGuard(lock_path(self.config_path))
        self._file_logging = None
        self._crash_log = None

    def run(self) -> int:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._guard.acquire():
            self._notify("插件管理器已运行", "已有一个插件管理器实例正在运行，请使用现有窗口。")
            return 0
        update_launched = False
        try:
            self._file_logging = configure_logging(self.log_file)
            self._crash_log = self.log_file.with_name('plugin_native_crash.log').open('a',encoding='utf-8')
            set_stream(self._crash_log)
            faulthandler.enable(file=self._crash_log,all_threads=True)
            checkpoint('application-start native-stack-capture=enabled')
            LOG.info('原生崩溃堆栈及同步检查点：%s',self._crash_log.name)
            info = build_info()
            LOG.info('插件管理器启动，版本：%s；构建模式：%s；运行方式：%s；配置：%s；日志：%s',
                     info.version, info.mode, '打包程序' if getattr(sys, 'frozen', False) else 'Python源码',
                     self.config_path, self.log_file)
            failed = updater.app_root() / '_staging' / 'failed.json'
            if failed.is_file():
                self._notify('上次更新未完成', '更新安装失败，请查看安装目录下的 _staging/update.log。\n更新文件与备份已保留。')
                failed.replace(failed.with_name('last-failure.json'))
            if updater.pending_update() is not None:
                try:
                    if updater.launch_pending():
                        update_launched = True
                        return 0
                except Exception as exc:
                    LOG.warning('待安装更新校验失败，继续运行当前版本：%s', exc)
            return run_gui(self._create_window, app_name=APP_NAME, executor_factory=BackgroundExecutor)
        except (OSError, ValueError) as exc:
            LOG.exception('插件管理器启动失败')
            self._notify("插件配置加载失败", f"{exc}\n\n不会覆盖现有配置，请检查：{self.config_path}", critical=True)
            return 1
        finally:
            if self._crash_log is not None:
                checkpoint('application-normal-exit')
                faulthandler.disable()
                set_stream(None)
                self._crash_log.close()
                self._crash_log=None
            if self._file_logging is not None:
                LOG.info('插件管理器退出')
                self._file_logging.close()
            self._guard.release()
            if not update_launched:
                try:
                    updater.launch_pending()
                except Exception as exc:
                    # Keep ready metadata so the next launch can retry safely.
                    self._notify('更新暂未安装', f'更新安装未能启动：{exc}\n更新文件已保留，请稍后重试。', critical=True)

    def _create_window(self):
        """装配窗口与运行服务；运行服务自己登记到窗口，入口不再挂属性。"""
        store = PluginConfigStore(self.config_path)
        window = window_module.PluginWindow(store)
        LOG.info('插件主窗口已创建，准备显示平台选择或功能界面')
        # Old updaters may launch us with STARTUPINFO/SW_HIDE. Qt's first
        # show can inherit that flag, so restore our own top-level window once
        # the event loop has processed its initial show event.
        QTimer.singleShot(0, lambda: ensure_window_visible(window))
        # 通过模块属性解析，保证测试替换 PluginRuntime / PluginWindow 与导入顺序无关。
        def connect(platform):
            LOG.info('选择游戏平台：%s',platform)
            self.platform = platform
            if not build_info().is_release:
                window.show_main_ui()
            window.setWindowTitle('遗弃之地 · 插件管理器 · ' + {'douyin':'抖音 PC', 'wechat':'微信', 'androws':'应用宝'}[platform] + ' · ' + window.version_text)
            if platform == 'douyin':
                from .douyin import DouyinCache, DouyinService, DouyinTransport, douyin_ready
                cache = DouyinCache(self.config_path.parent)
                service = DouyinService(cache, window)
                # Display is independent from authorization; only the Douyin branch subscribes.
                service.player_id_changed.connect(window.set_bound_player_id)
                runtime_module.PluginRuntime(window, service=service,
                    transport=DouyinTransport(cache), process_ready=douyin_ready).start()
            elif platform == 'androws':
                from .androws import AndrowsTransport, androws_ready
                runtime_module.PluginRuntime(window, transport=AndrowsTransport(), process_ready=androws_ready).start()
            else:
                runtime_module.PluginRuntime(window).start()
        if self.platform is None:
            window.select_platform(connect)
        else:
            connect(self.platform)
        return window

    @staticmethod
    def _notify(title: str, text: str, *, critical: bool = False) -> None:
        QApplication.instance() or QApplication([])
        if critical:
            QMessageBox.critical(None, title, text)
        else:
            QMessageBox.information(None, title, text)


def ensure_window_visible(window):
    """Recover our interactive window even when an old updater used SW_HIDE."""
    if getattr(window,'_closing',False):
        return
    window.showNormal()
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        user32=ctypes.WinDLL('user32',use_last_error=True)
        user32.IsWindowVisible.argtypes=[wintypes.HWND]
        user32.IsWindowVisible.restype=wintypes.BOOL
        user32.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
        user32.ShowWindow.restype=wintypes.BOOL
        handle=int(window.winId())
        if not user32.IsWindowVisible(handle):
            user32.ShowWindow(handle,1)  # SW_SHOWNORMAL: only our own window.
        LOG.info('插件主窗口显示检查：visible=%s',bool(user32.IsWindowVisible(handle)))
    window.raise_()
    window.activateWindow()


def main(config_path: Path | None = None, *, platform: str | None = None) -> int:
    """插件管理器入口；config_path 用于测试指定配置位置。"""
    # Explicit config_path keeps embedded/test callers' existing WeChat default.
    selected = platform if platform is not None else ('wechat' if config_path is not None else None)
    return PluginApplication(config_path, platform=selected).run()
