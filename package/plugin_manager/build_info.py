"""构建信息：模式、版本、后台地址，来自打包时写进产物的 build.json。

源码运行和调试版都没有这个文件，一律按"调试版"处理——不连后台。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

BUILD_FILE_NAME = "build.json"
MODE_DEBUG = "debug"
MODE_RELEASE = "release"


@dataclass(frozen=True)
class BuildInfo:
    mode: str
    version: str
    target: str  # 后台 gRPC 地址 host:port

    @property
    def is_release(self) -> bool:
        return self.mode == MODE_RELEASE


def build_file_path() -> Path:
    """冻结后落在 _internal，源码模式下指向仓库根目录（不存在）。"""
    return Path(__file__).resolve().parents[2] / BUILD_FILE_NAME


def load() -> BuildInfo:
    """读构建信息；缺失或坏文件都按调试版处理。"""
    path = build_file_path()
    if not path.is_file():
        return BuildInfo(MODE_DEBUG, "0.0.0-dev", "")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return BuildInfo(MODE_DEBUG, "0.0.0-dev", "")
    if not isinstance(raw, dict):
        return BuildInfo(MODE_DEBUG, "0.0.0-dev", "")
    mode = raw.get("mode")
    return BuildInfo(
        mode=mode if mode in (MODE_DEBUG, MODE_RELEASE) else MODE_DEBUG,
        version=str(raw.get("version") or "0.0.0"),
        target=str(raw.get("target") or ""),
    )


_CACHED: BuildInfo | None = None


def current() -> BuildInfo:
    """进程内只读一次。"""
    global _CACHED
    if _CACHED is None:
        _CACHED = load()
    return _CACHED


def reset_cache() -> None:
    """测试用：丢弃缓存重新读文件。"""
    global _CACHED
    _CACHED = None
