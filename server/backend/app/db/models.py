"""数据库模型：玩家白名单、握手日志、发布版本与文件清单。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Player(Base):
    """有权限的玩家；停用它就等于吊销该玩家的插件使用权。"""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")   # 管理员自己填的备注
    # 下面两个由客户端上报自动刷新，管理员不用填
    role_name: Mapped[str] = mapped_column(String(64), default="")  # 游戏角色名（昵称）
    guild: Mapped[str] = mapped_column(String(64), default="")      # 最近一次上报的阴司名
    note: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HandshakeLog(Base):
    """每次握手的审计记录：谁、什么时候、从哪来、放没放行。"""

    __tablename__ = "handshake_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    bound_player_id: Mapped[str] = mapped_column(String(64), default="")
    player_name: Mapped[str] = mapped_column(String(64), default="")  # 上报时的角色名
    guild: Mapped[str] = mapped_column(String(64), default="")
    client_version: Mapped[str] = mapped_column(String(32), default="")
    remote: Mapped[str] = mapped_column(String(64), default="")
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Release(Base):
    """一个发布版本；同一时刻只有一个 enabled 的版本对外生效。"""

    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(32), unique=True)
    changelog: Mapped[str] = mapped_column(Text, default="")
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    total_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReleaseFile(Base):
    """版本内的文件清单，插件靠它做增量 diff。"""

    __tablename__ = "release_files"
    __table_args__ = (UniqueConstraint("release_id", "path", name="uq_release_file"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(512), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
