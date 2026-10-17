"""单实例锁：同一份配置只允许一个进程持有。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


class InstanceGuard:
    def __init__(self, path: Path):
        self.lock = QLockFile(str(path))
        self.lock.setStaleLockTime(0)

    def acquire(self) -> bool:
        return self.lock.tryLock(0)

    def release(self) -> None:
        self.lock.unlock()
