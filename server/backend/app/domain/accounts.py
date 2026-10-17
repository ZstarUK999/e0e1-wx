"""管理员账号：bcrypt 存密码，JWT 做管理端会话。"""

from __future__ import annotations

import datetime as dt

import bcrypt
import jwt

from ..db.models import Admin
from ..settings import settings


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, AttributeError):
        return False


def ensure_default_admin(session) -> None:
    """首次启动时按配置写入管理员；已存在则不动。"""
    if session.query(Admin).count():
        return
    session.add(
        Admin(username=settings.admin_username, password_hash=hash_password(settings.admin_password))
    )


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return str(payload.get("sub") or "") or None


def create_download_ticket(version: str) -> str:
    """更新文件的下载票据：绑定版本，短时效。"""
    payload = {
        "dl": version,
        "exp": dt.datetime.now(dt.timezone.utc)
        + dt.timedelta(minutes=settings.download_ticket_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def read_download_ticket(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return str(payload.get("dl") or "") or None
