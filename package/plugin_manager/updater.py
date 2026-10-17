"""更新：上报本地清单 → 下载变动文件到 staging → 校验 → 生成应用脚本。

exe 运行时不能覆盖自己，所以落地交给 apply_update.cmd：插件退出后由它把
staging 覆盖到 app 目录再重新拉起。license.bin 不在清单里，永远不会被覆盖。
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path
import sys

from . import server_client
from .build_info import current as build_info

LOG = logging.getLogger('plugin_manager.updater')

STAGING_DIR_NAME = "_staging"
APPLY_SCRIPT_NAME = "apply_update.cmd"
# 不纳入清单：license 是玩家身份，staging/logs 是运行时产物
EXCLUDED_NAMES = {"license.bin", APPLY_SCRIPT_NAME}
EXCLUDED_PREFIXES = (STAGING_DIR_NAME + os.sep, "logs" + os.sep)


def app_root() -> Path:
    """被更新管理的目录：冻结后是 exe 所在目录（_internal 的父目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2] / "dist" / "e0e1-wx-plugins"


def _is_managed(relative: str) -> bool:
    return not relative.startswith(EXCLUDED_PREFIXES) and relative.split(os.sep)[-1] not in EXCLUDED_NAMES


def local_manifest() -> dict[str, str]:
    """扫描 app 目录，算每个文件的 sha256。"""
    root = app_root()
    manifest: dict[str, str] = {}
    if not root.is_dir():
        return manifest
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not _is_managed(relative):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        manifest[relative] = digest.hexdigest()
    return manifest


def _download(url: str, target: Path, ca_path: Path) -> None:
    import httpx

    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, verify=str(ca_path), timeout=60.0, follow_redirects=True) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for block in response.iter_bytes(1024 * 256):
                handle.write(block)


def prepare(plan: dict) -> Path | None:
    """按清单下载到 staging 并逐个校验；全部通过才写应用脚本。"""
    version = plan["version"]
    staging = app_root() / STAGING_DIR_NAME / version
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    ca_path = server_client.cert_dir() / "ca.pem"
    for item in plan["changed"]:
        target = staging / Path(item["path"]).as_posix()
        _download(item["url"], target, ca_path)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise RuntimeError(f"文件校验失败：{item['path']}")
    LOG.info('更新包已就绪：%s，变动 %d 个文件', version, len(plan["changed"]))

    return write_apply_script(version, [item["path"] for item in plan["changed"]], plan["removed"])


def write_apply_script(version: str, changed: list[str], removed: list[str]) -> Path:
    """生成 cmd：等插件退出后覆盖文件，再重新拉起。"""
    root = app_root()
    staging = root / STAGING_DIR_NAME / version
    script = root / APPLY_SCRIPT_NAME
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        f"set APP={root}",
        f"set STAGE={staging}",
        "timeout /t 2 /nobreak >nul",
    ]
    for path in removed:
        lines.append(f'del /f /q "%APP%\\{path}" 2>nul')
    for path in changed:
        target = Path(path).as_posix()
        lines.append(f'if not exist "%APP%\\{target}\\.." mkdir "%APP%\\{target}\\.." 2>nul')
        lines.append(f'copy /y "%STAGE%\\{target}" "%APP%\\{target}" >nul')
    lines += [
        f'rmdir /s /q "%STAGE%" 2>nul',
        f'del /f /q "%APP%\\{APPLY_SCRIPT_NAME}" 2>nul',
        f'start "" "%APP%\\{Path(sys.executable).name}"',
        "exit /b 0",
    ]
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return script


def pending_update() -> Path | None:
    """是否已经有下好待应用的更新。"""
    script = app_root() / APPLY_SCRIPT_NAME
    return script if script.is_file() else None


def check(*, player_id: str) -> dict | None:
    """检查更新并返回结果；调试版直接返回 None。"""
    info = build_info()
    if not info.is_release:
        return None
    return server_client.check_update(local_manifest(), player_id=player_id)
