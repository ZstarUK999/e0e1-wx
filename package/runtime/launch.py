"""GUI 进程统一启动入口：多进程准备 + QApplication/qasync 事件循环。"""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Callable

from PySide6.QtWidgets import QMainWindow

WindowFactory = Callable[[], QMainWindow]


def run_gui(window_factory: WindowFactory, *, app_name: str, organization: str = "e0e1") -> int:
    """准备子进程环境后，以 qasync 事件循环托管主窗口。"""
    mp.freeze_support()
    from package.runtime.process_bootstrap import configure_multiprocessing_for_gui_subprocesses

    configure_multiprocessing_for_gui_subprocesses()
    from package.runtime.async_app import run_qasync_window

    return run_qasync_window(window_factory, app_name=app_name, organization=organization)
