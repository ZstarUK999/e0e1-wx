"""构建期功能开关：读打包进产物的 features.json，文件缺失即全部开启。

开关由 tools/build_exe.py 按 build/features.json 写进 _internal；源码运行和老产物
都不会有这个文件，所以行为保持"全部开启"不变。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FEATURES_FILE_NAME = "features.json"


@dataclass(frozen=True)
class Features:
    """一份构建期开关快照；没写到的项一律视为开启。"""

    tasks: dict[str, bool]
    panels: dict[str, bool]

    def task_enabled(self, task_id: str) -> bool:
        """任务是否被打包进本次构建。"""
        return bool(self.tasks.get(task_id, True))

    def panel_enabled(self, key: str) -> bool:
        """面板是否被打包进本次构建。"""
        return bool(self.panels.get(key, True))


def features_path() -> Path:
    """开关文件路径：冻结后落在 _internal，源码模式下指向仓库根目录（不存在）。"""
    return Path(__file__).resolve().parents[2] / FEATURES_FILE_NAME


def load() -> Features:
    """读取开关文件；缺失、坏文件、类型不对都按全部开启处理。"""
    path = features_path()
    if not path.is_file():
        return Features({}, {})
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Features({}, {})
    if not isinstance(raw, dict):
        return Features({}, {})
    tasks = raw.get("tasks")
    panels = raw.get("panels")
    return Features(
        dict(tasks) if isinstance(tasks, dict) else {},
        dict(panels) if isinstance(panels, dict) else {},
    )


_CACHED: Features | None = None


def current() -> Features:
    """进程内只解析一次。"""
    global _CACHED
    if _CACHED is None:
        _CACHED = load()
    return _CACHED


def reset_cache() -> None:
    """丢弃缓存重新读取，仅供测试使用。"""
    global _CACHED
    _CACHED = None


def task_enabled(task_id: str) -> bool:
    return current().task_enabled(task_id)


def panel_enabled(key: str) -> bool:
    return current().panel_enabled(key)
