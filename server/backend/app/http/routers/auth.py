"""管理端登录。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...domain.accounts import create_token, verify_password
from ..deps import db_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(db_session)) -> LoginResponse:
    from ...db.models import Admin

    admin = session.query(Admin).filter(Admin.username == payload.username).one_or_none()
    if admin is None or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    return LoginResponse(token=create_token(admin.username))
