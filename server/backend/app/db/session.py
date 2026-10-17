"""同步 SQLAlchemy 会话：管理端请求量少，同步够用且比异步栈简单。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..settings import settings
from .models import Base

_engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db() -> None:
    """建表并写入初始管理员。"""
    Base.metadata.create_all(_engine)
    from ..domain.accounts import ensure_default_admin

    with session_scope() as session:
        ensure_default_admin(session)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
