"""握手日志：谁在什么时候用过插件，放没放行。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import HandshakeLog, Player
from ..deps import current_admin, db_session

router = APIRouter(prefix="/api/logs", tags=["logs"])


class BoundPlayerOut(BaseModel):
    player_id: str
    nickname: str


class LogOut(BaseModel):
    id: int
    player_id: str
    bound_player_id: str
    bound_player_nickname: str
    bound_players: list[BoundPlayerOut]
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
    def bindings(item):
        try:
            ids = json.loads(item.bound_player_ids or "[]")
        except (ValueError, TypeError):
            ids = []
        if not isinstance(ids, list):
            ids = []
        return list(dict.fromkeys(str(value) for value in ids if isinstance(value, str) and value)) or ([item.bound_player_id] if item.bound_player_id else [])

    bindings_by_log = {item.id: bindings(item) for item in rows}
    ids = {value for values in bindings_by_log.values() for value in values}
    # 批量查询备注，避免每条日志、每个绑定玩家单独查询。
    names = dict(session.query(Player.player_id, Player.nickname).filter(Player.player_id.in_(ids)).all()) if ids else {}
    return [
        LogOut(
            id=item.id,
            player_id=item.player_id or "",
            bound_player_id=item.bound_player_id or "",
            bound_player_nickname=names.get(item.bound_player_id) or "",
            bound_players=[BoundPlayerOut(player_id=value, nickname=names.get(value) or "") for value in bindings_by_log[item.id]],
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
