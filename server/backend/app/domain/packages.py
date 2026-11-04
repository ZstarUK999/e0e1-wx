"""按玩家生成完整分发包：通用 app 文件 + 该玩家的 license。

app 文件对所有玩家都一样，所以这里不跑 PyInstaller，只是把已发布版本的文件
重新压一份，再把新签的 license.bin 塞进去。
"""

from __future__ import annotations

import zipfile
import uuid
import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from ..db.models import Release
from ..settings import settings
from . import license as license_module
from . import updates

# 解压后是一个干净目录，和 build_exe.py --package 的产物保持一致
PACKAGE_ROOT = "e0e1-wx-plugins"
LICENSE_FILE_NAME = "license.bin"
PACKAGE_RETENTION_SECONDS = 24 * 60 * 60
LOG = logging.getLogger(__name__)


def cleanup_expired_packages() -> int:
    """只清理玩家包目录中超过 24 小时的 ZIP，保留新包和其他数据。"""
    directory = settings.data_dir / "packages"
    if not directory.is_dir():
        return 0
    cutoff = time.time() - PACKAGE_RETENTION_SECONDS
    removed = 0
    for path in directory.glob(f"{PACKAGE_ROOT}-*.zip"):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_mtime > cutoff:
                continue
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass  # 另一个请求或清理进程已删除。
        except OSError:
            LOG.exception("无法清理过期玩家包：%s", path.name)
    if removed:
        LOG.info("已清理 %d 个超过 24 小时的玩家包", removed)
    return removed


def package_dir() -> Path:
    directory = settings.data_dir / "packages"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def build_player_package(
    session: Session, player_id: str | list[str], version: str | None = None
) -> tuple[Path, str]:
    """生成分发包，返回 (文件路径, 版本号)。

    不传 version 就用当前生效版本；没有生效版本直接报错。
    """
    release = (
        session.query(Release).filter(Release.version == version).one_or_none()
        if version
        else updates.current_release(session)
    )
    if release is None:
        raise ValueError("还没有生效版本，先上传构建产物并点发布")

    root = updates.release_root(release.version)
    if not root.is_dir():
        raise ValueError(f"版本文件缺失：{release.version}")

    payload = license_module.issue(player_id)
    count = len(license_module.player_ids(payload))
    target = package_dir() / f"{PACKAGE_ROOT}-{release.version}-{count}players-{uuid.uuid4().hex[:12]}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{PACKAGE_ROOT}/{LICENSE_FILE_NAME}", license_module.dumps(payload)
        )
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.relative_to(root).as_posix() != LICENSE_FILE_NAME:
                archive.write(path, f"{PACKAGE_ROOT}/{path.relative_to(root).as_posix()}")
    return target, release.version
