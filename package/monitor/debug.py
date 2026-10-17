"""把监控调试日志写入文件。

监控 worker 运行在 pythonw 子进程里，没有控制台，print 不可见，因此统一写文件。
用环境变量 E0E1_MONITOR_DEBUG=0 可以关闭。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_ENABLED = os.environ.get("E0E1_MONITOR_DEBUG", "1").strip().lower() not in {"0", "false", "no", "off"}
_log_path: Path | None = None


def debug_enabled() -> bool:
    """返回调试日志是否开启。"""
    return _ENABLED


def configure_debug_log(path: Path | str) -> Path:
    """设置调试日志文件路径。"""
    global _log_path
    _log_path = Path(path).expanduser()
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    return _log_path


def debug_log(message: str) -> None:
    """追加一行带时间戳的调试日志。"""
    if not _ENABLED or _log_path is None:
        return
    try:
        with _log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except OSError:
        pass
