"""插件管理器的本地路径：配置、单实例锁与日志都放在同一目录下。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

CONFIG_DIR_NAME = "e0e1-wx-plugins"
CONFIG_FILE_NAME = "plugins.json"
LOCK_FILE_NAME = "plugin-manager.lock"
LOG_FILE_NAME = "plugin_manager.log"


def config_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.GenericConfigLocation)
    if not base:
        raise RuntimeError("无法确定用户配置目录")
    return Path(base) / "e0e1" / CONFIG_DIR_NAME


def default_config_path() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def lock_path(config_path: Path) -> Path:
    """单实例锁与配置同目录：换配置目录就等于换一个实例。"""
    return Path(config_path).with_name(LOCK_FILE_NAME)


def log_path(config_path: Path) -> Path:
    return Path(config_path).parent / "logs" / LOG_FILE_NAME
