"""管理员下载用于客户端发行包的 mTLS 凭据。"""
from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Response

from ...settings import settings
from ..deps import current_admin

router = APIRouter(prefix="/api/certificates", tags=["certificates"])
CLIENT_FILES = ("ca.pem", "client.pem", "client.key")


@router.get("/client.zip")
def download_client_certificates(_admin: str = Depends(current_admin)):
    directory = settings.certs_dir / "client"
    missing = [name for name in CLIENT_FILES if not (directory / name).is_file()]
    if missing:
        raise HTTPException(status_code=404, detail="客户端证书不完整：" + "、".join(missing))
    payload = io.BytesIO()
    try:
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in CLIENT_FILES:
                content = (directory / name).read_bytes()
                if not content:
                    raise HTTPException(status_code=503, detail=f"客户端证书文件为空：{name}")
                archive.writestr("client/" + name, content)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="无法读取客户端证书，请检查服务端文件权限") from exc
    return Response(payload.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="e0e1-client-certs.zip"',
        "Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
    })
