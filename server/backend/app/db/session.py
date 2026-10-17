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


def _add_missing_columns() -> None:
    """给旧库补列：create_all 只建新表，不会 ALTER。

    服务器已经跑过一阵子的话，加字段必须走这一步，否则查询会报 no such column。
    """
    from sqlalchemy import text

    with _engine.connect() as connection:
        for table, columns in _EXTRA_COLUMNS.items():
            existing = {
                row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))
            }
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(
                        text(f'ALTER TABLE {table} ADD COLUMN "{column}" {definition}')
                    )
            connection.commit()


# 只列后加的列；建表时已有的不用管
_EXTRA_COLUMNS = {
    "players": {"role_name": "VARCHAR(64) DEFAULT ''"},
    "handshake_logs": {"player_name": "VARCHAR(64) DEFAULT ''"},
}


def init_db() -> None:
    """建表、补列、写入初始管理员。"""
    Base.metadata.create_all(_engine)
    _add_missing_columns()
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
