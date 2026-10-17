"""版本发布与增量 diff。

diff 以服务器清单为准：本地多出来的文件会被要求删除，所以"回滚"就是把旧版本
重新启用，插件下次 diff 自然把文件改回去。
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from ..db.models import Release, ReleaseFile
from ..settings import settings

# 这些不属于发布内容：license 是每个人自己的身份，staging/logs 是运行时产物。
# 少了这条，diff 会把玩家本地的 license.bin 当成"多余文件"删掉。
EXCLUDED_PREFIXES = ("_staging/", "logs/")
EXCLUDED_NAMES = ("license.bin",)


def is_managed(path: str) -> bool:
    """该文件是否纳入发布清单管理。"""
    normalized = str(path).replace("\\", "/").lstrip("./")
    if normalized.startswith(EXCLUDED_PREFIXES):
        return False
    return normalized.split("/")[-1] not in EXCLUDED_NAMES


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def release_root(version: str) -> Path:
    return settings.data_dir / "releases" / version


def import_release(
    session: Session,
    *,
    archive: bytes,
    version: str,
    changelog: str,
    mandatory: bool,
) -> Release:
    """解开发布包，递归算 sha256 落清单。版本已存在就先清掉旧的。"""
    if session.query(Release).filter(Release.version == version).one_or_none() is not None:
        delete_release(session, version)

    root = release_root(version)
    root.mkdir(parents=True, exist_ok=True)
    release = Release(
        version=version,
        changelog=changelog or "",
        mandatory=bool(mandatory),
        enabled=False,
    )
    session.add(release)
    session.flush()

    total, count = 0, 0
    with zipfile.ZipFile(io.BytesIO(archive)) as archive_file:
        for member in archive_file.infolist():
            if member.is_dir():
                continue
            relative = member.filename.replace("\\", "/")
            # 允许 zip 里带一层顶层目录，剥掉它
            parts = relative.split("/")
            if len(parts) > 1 and parts[0] == "e0e1-wx-plugins":
                relative = "/".join(parts[1:])
            if not relative or not is_managed(relative):
                continue
            data = archive_file.read(member)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            session.add(
                ReleaseFile(
                    release_id=release.id,
                    path=relative,
                    sha256=sha256_of(data),
                    size=len(data),
                )
            )
            total += len(data)
            count += 1

    release.file_count = count
    release.total_size = total
    return release


def delete_release(session: Session, version: str) -> None:
    """删除版本记录与落盘文件。"""
    release = session.query(Release).filter(Release.version == version).one_or_none()
    if release is None:
        return
    session.query(ReleaseFile).filter(ReleaseFile.release_id == release.id).delete()
    session.delete(release)
    session.flush()
    import shutil

    shutil.rmtree(release_root(version), ignore_errors=True)


def publish(session: Session, version: str) -> Release:
    """启用某版本；同一时刻只保留一个生效版本。"""
    release = session.query(Release).filter(Release.version == version).one_or_none()
    if release is None:
        raise ValueError(f"版本不存在：{version}")
    for other in session.query(Release).all():
        other.enabled = other.id == release.id
    return release


def current_release(session: Session) -> Release | None:
    return session.query(Release).filter(Release.enabled.is_(True)).one_or_none()


def manifest(session: Session, release: Release) -> dict[str, tuple[str, int]]:
    """版本的 path -> (sha256, size)。"""
    files = session.query(ReleaseFile).filter(ReleaseFile.release_id == release.id).all()
    return {item.path: (item.sha256, item.size) for item in files}


def diff(session: Session, release: Release, local: dict[str, str]) -> tuple[list[dict], list[str]]:
    """比对本地 hash 清单，返回 (需要下载的文件, 需要删除的路径)。"""
    remote = manifest(session, release)
    changed = [
        {"path": path, "sha256": digest, "size": size, "url": file_url(release.version, path)}
        for path, (digest, size) in sorted(remote.items())
        if local.get(path) != digest
    ]
    removed = sorted(path for path in local if path not in remote and is_managed(path))
    return changed, removed


def file_url(version: str, path: str) -> str:
    """带票据的下载地址；票据在 accounts 里签发，这里只拼路径。"""
    from .accounts import create_download_ticket

    ticket = create_download_ticket(version)
    return f"{settings.public_base_url.rstrip('/')}/api/releases/{version}/files/{path}?ticket={ticket}"


def file_path(version: str, path: str) -> Path:
    """落盘路径；拒绝越权读取版本目录之外的文件。"""
    root = release_root(version).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("非法的文件路径")
    return target
