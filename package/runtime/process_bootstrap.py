"""Configure process startup behavior before GUI modules are imported."""

from __future__ import annotations

import multiprocessing as mp
import sys
from pathlib import Path


def pythonw_child_executable() -> Path | None:
    """Return pythonw.exe for Windows source-mode child processes when available.

    虚拟环境里的 pythonw.exe 是 venvwlauncher 启动器，它会再拉起一个真正的解释器，
    multiprocessing 复制给它的信号量/锁句柄传不到孙进程，mp.Queue 会失去同步
    （表现为 get_nowait 抛 ValueError: semaphore or lock released too many times）。
    因此优先使用基础解释器（sys._base_executable）旁边的 pythonw.exe。
    """
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return None

    executables = [Path(getattr(sys, "_base_executable", "") or ""), Path(sys.executable)]
    for executable in executables:
        if not executable.name:
            continue
        if executable.name.casefold() == "pythonw.exe":
            continue
        candidate = executable.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return None


def configure_multiprocessing_for_gui_subprocesses() -> bool:
    """Use a windowless Python executable for multiprocessing children in source mode."""
    child_executable = pythonw_child_executable()
    if child_executable is None:
        return False
    mp.set_executable(str(child_executable))
    return True
