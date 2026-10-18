"""插件管理器装配：路径、单实例、日志与窗口／运行服务的接线。

入口脚本只负责调用 main()；这里决定"怎么把各部件装起来"。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from package.runtime.instance_guard import InstanceGuard
from package.runtime.launch import run_gui

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
        if platform not in (None, 'wechat', 'douyin'):
            raise ValueError('未知游戏平台')
        self.platform = platform
        self.config_path = Path(config_path) if config_path is not None else default_config_path()
        self.log_file = log_path(self.config_path)
        self._guard = InstanceGuard(lock_path(self.config_path))
        self._file_logging = None

    def run(self) -> int:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._guard.acquire():
            self._notify("插件管理器已运行", "已有一个插件管理器实例正在运行，请使用现有窗口。")
            return 0
        try:
            self._file_logging = configure_logging(self.log_file)
            LOG.info('插件管理器启动，配置：%s；日志：%s', self.config_path, self.log_file)
            return run_gui(self._create_window, app_name=APP_NAME)
        except (OSError, ValueError) as exc:
            LOG.exception('插件管理器启动失败')
            self._notify("插件配置加载失败", f"{exc}\n\n不会覆盖现有配置，请检查：{self.config_path}", critical=True)
            return 1
        finally:
            if self._file_logging is not None:
                LOG.info('插件管理器退出')
                self._file_logging.close()
            self._guard.release()

    def _create_window(self):
        """装配窗口与运行服务；运行服务自己登记到窗口，入口不再挂属性。"""
        store = PluginConfigStore(self.config_path)
        window = window_module.PluginWindow(store)
        # 通过模块属性解析，保证测试替换 PluginRuntime / PluginWindow 与导入顺序无关。
        def connect(platform):
            self.platform = platform
            if not build_info().is_release:
                window.show_main_ui()
            window.setWindowTitle('遗弃之地 · 插件管理器 · ' + ('抖音 PC' if platform == 'douyin' else '微信'))
            if platform == 'douyin':
                from .douyin import DouyinCache, DouyinService, DouyinTransport, douyin_ready
                cache = DouyinCache(self.config_path.parent)
                service = DouyinService(cache, window)
                # Display is independent from authorization; only the Douyin branch subscribes.
                service.player_id_changed.connect(window.set_bound_player_id)
                runtime_module.PluginRuntime(window, service=service,
                    transport=DouyinTransport(cache), process_ready=douyin_ready).start()
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


def main(config_path: Path | None = None, *, platform: str | None = None) -> int:
    """插件管理器入口；config_path 用于测试指定配置位置。"""
    # Explicit config_path keeps embedded/test callers' existing WeChat default.
    selected = platform if platform is not None else ('wechat' if config_path is not None else None)
    return PluginApplication(config_path, platform=selected).run()
