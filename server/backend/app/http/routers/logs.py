"""握手日志：谁在什么时候用过插件，放没放行。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import HandshakeLog
from ..deps import current_admin, db_session

router = APIRouter(prefix="/api/logs", tags=["logs"])


class LogOut(BaseModel):
    id: int
    player_id: str
    bound_player_id: str
    player_name: str
    guild: str
    client_version: str
    remote: str
    allowed: bool
    reason: str
    created_at: str


@router.get("", response_model=list[LogOut])
def list_logs(
    limit: int = 100,
    session: Session = Depends(db_session),
    _admin: str = Depends(current_admin),
) -> list[LogOut]:
    rows = (
        session.query(HandshakeLog)
        .order_by(HandshakeLog.id.desc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    return [
        LogOut(
            id=item.id,
            player_id=item.player_id or "",
            bound_player_id=item.bound_player_id or "",
            player_name=item.player_name or "",
            guild=item.guild or "",
            client_version=item.client_version or "",
            remote=item.remote or "",
            allowed=bool(item.allowed),
            reason=item.reason or "",
            created_at=item.created_at.isoformat(timespec="seconds") if item.created_at else "",
        )
        for item in rows
    ]
