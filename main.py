"""程序启动入口，仅负责多进程准备和 GUI 事件循环调度。"""

from __future__ import annotations


def main() -> int:
    """程序主入口，只负责启动 qasync 与主窗口。"""
    from package.runtime.launch import run_gui
    from package.ui.main_window import MainWindow

    return run_gui(MainWindow, app_name="e0e1-wx-gui")


if __name__ == "__main__":
    raise SystemExit(main())
