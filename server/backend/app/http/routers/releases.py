"""版本发布：上传构建产物、生成清单、启用/停用、文件下载。"""

from __future__ import annotations

import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import Release, ReleaseFile
from ...domain import accounts, updates
from ..deps import current_admin, db_session

router = APIRouter(prefix="/api/releases", tags=["releases"])


class ReleaseOut(BaseModel):
    id: int
    version: str
    changelog: str
    mandatory: bool
    enabled: bool
    file_count: int
    total_size: int

    @classmethod
    def from_model(cls, release: Release) -> "ReleaseOut":
        return cls(
            id=release.id,
            version=release.version,
            changelog=release.changelog or "",
            mandatory=bool(release.mandatory),
            enabled=bool(release.enabled),
            file_count=release.file_count,
            total_size=release.total_size,
        )


@router.get("", response_model=list[ReleaseOut])
def list_releases(
    session: Session = Depends(db_session), _admin: str = Depends(current_admin)
) -> list[ReleaseOut]:
    releases = session.query(Release).order_by(Release.id.desc()).all()
    return [ReleaseOut.from_model(item) for item in releases]


@router.post("/upload", response_model=ReleaseOut, status_code=status.HTTP_201_CREATED)
def upload_release(
    archive: UploadFile = File(...),
    version: str = Form(...),
    changelog: str = Form(""),
    mandatory: bool = Form(False),
    session: Session = Depends(db_session),
    _admin: str = Depends(current_admin),
) -> ReleaseOut:
    """上传构建产物 zip；新版本默认不启用，确认无误再点发布。"""
    payload = archive.file.read()
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传内容为空")
    try:
        release = updates.import_release(
            session, archive=payload, version=version.strip(), changelog=changelog,
            mandatory=mandatory,
        )
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"不是有效的zip：{exc}")
    return ReleaseOut.from_model(release)


@router.post("/{version}/publish", response_model=ReleaseOut)
def publish_release(
    version: str, session: Session = Depends(db_session), _admin: str = Depends(current_admin)
) -> ReleaseOut:
    try:
        release = updates.publish(session, version)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return ReleaseOut.from_model(release)


@router.patch("/{version}", response_model=ReleaseOut)
def patch_release(
    version: str,
    mandatory: bool | None = None,
    enabled: bool | None = None,
    session: Session = Depends(db_session),
    _admin: str = Depends(current_admin),
) -> ReleaseOut:
    release = session.query(Release).filter(Release.version == version).one_or_none()
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    if mandatory is not None:
        release.mandatory = mandatory
    if enabled:
        # 启用走 publish，保证同一时刻只有一个生效版本
        release = updates.publish(session, version)
    elif enabled is False:
        release.enabled = False
    return ReleaseOut.from_model(release)


@router.delete("/{version}", status_code=status.HTTP_204_NO_CONTENT)
def delete_release(
    version: str, session: Session = Depends(db_session), _admin: str = Depends(current_admin)
) -> Response:
    updates.delete_release(session, version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{version}/files/{path:path}")
def download_file(version: str, path: str, ticket: str = ""):
    """插件下载更新文件：票据必须与该版本匹配。"""
    if accounts.read_download_ticket(ticket) != version:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="下载票据无效或已过期")
    try:
        target = updates.file_path(version, path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    return FileResponse(target)


@router.get("/{version}/files")
def list_files(
    version: str, session: Session = Depends(db_session), _admin: str = Depends(current_admin)
) -> list[dict]:
    release = session.query(Release).filter(Release.version == version).one_or_none()
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    files = session.query(ReleaseFile).filter(ReleaseFile.release_id == release.id).all()
    return [{"path": item.path, "sha256": item.sha256, "size": item.size} for item in files]
