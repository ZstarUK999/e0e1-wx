"""玩家白名单与 license 签发。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import Player
from ...domain import license as license_module
from ..deps import current_admin, db_session

router = APIRouter(prefix="/api/players", tags=["players"])


class PlayerIn(BaseModel):
    player_id: str
    nickname: str = ""
    note: str = ""


class PlayerPatch(BaseModel):
    nickname: str | None = None
    note: str | None = None
    enabled: bool | None = None


class PlayerOut(BaseModel):
    id: int
    player_id: str
    nickname: str
    role_name: str   # 客户端上报的游戏角色名
    guild: str
    note: str
    enabled: bool

    @classmethod
    def from_model(cls, player: Player) -> "PlayerOut":
        return cls(
            id=player.id,
            player_id=player.player_id,
            nickname=player.nickname or "",
            role_name=player.role_name or "",
            guild=player.guild or "",
            note=player.note or "",
            enabled=bool(player.enabled),
        )


@router.get("", response_model=list[PlayerOut])
def list_players(
    session: Session = Depends(db_session), _admin: str = Depends(current_admin)
) -> list[PlayerOut]:
    players = session.query(Player).order_by(Player.id.desc()).all()
    return [PlayerOut.from_model(item) for item in players]


@router.post("", response_model=PlayerOut, status_code=status.HTTP_201_CREATED)
def create_player(
    payload: PlayerIn, session: Session = Depends(db_session), _admin: str = Depends(current_admin)
) -> PlayerOut:
    player_id = payload.player_id.strip()
    if not player_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="玩家ID不能为空")
    if session.query(Player).filter(Player.player_id == player_id).one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该玩家已在白名单中")
    player = Player(player_id=player_id, nickname=payload.nickname, note=payload.note)
    session.add(player)
    session.flush()
    return PlayerOut.from_model(player)


@router.patch("/{player_id}", response_model=PlayerOut)
def patch_player(
    player_id: str,
    payload: PlayerPatch,
    session: Session = Depends(db_session),
    _admin: str = Depends(current_admin),
) -> PlayerOut:
    player = session.query(Player).filter(Player.player_id == player_id).one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="玩家不存在")
    if payload.nickname is not None:
        player.nickname = payload.nickname
    if payload.note is not None:
        player.note = payload.note
    if payload.enabled is not None:
        player.enabled = payload.enabled  # 停用即吊销
    return PlayerOut.from_model(player)


@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_player(
    player_id: str, session: Session = Depends(db_session), _admin: str = Depends(current_admin)
) -> Response:
    player = session.query(Player).filter(Player.player_id == player_id).one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="玩家不存在")
    session.delete(player)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PackageIn(BaseModel):
    player_ids: list[str]
    version: str | None = None


@router.post("/package")
def download_selected_package(payload: PackageIn, session: Session = Depends(db_session), _admin: str = Depends(current_admin)):
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask
    from ...domain import packages

    ids = list(dict.fromkeys(value.strip() for value in payload.player_ids))
    if not ids or len(ids) > 500 or any(not value or len(value) > 128 for value in ids):
        raise HTTPException(status_code=400, detail="请选择1至500名玩家")
    players = session.query(Player).filter(Player.player_id.in_(ids)).all()
    if len(players) != len(ids):
        raise HTTPException(status_code=400, detail="部分玩家不存在，请刷新列表")
    if any(not player.enabled for player in players):
        raise HTTPException(status_code=400, detail="选中玩家包含已停用账号，请取消勾选")
    try:
        target, version = packages.build_player_package(session, ids, payload.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FileResponse(target, filename=f"e0e1-wx-plugins-{version}-{len(ids)}players.zip", media_type="application/zip", background=BackgroundTask(target.unlink, missing_ok=True))


@router.get("/{player_id}/package")
def download_package(
    player_id: str,
    version: str | None = None,
    session: Session = Depends(db_session),
    _admin: str = Depends(current_admin),
):
    """一键出包：当前生效版本的文件 + 该玩家的 license，下载即可发给玩家。"""
    from fastapi.responses import FileResponse

    from ...domain import packages

    player = session.query(Player).filter(Player.player_id == player_id).one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="玩家不存在")
    try:
        target, used_version = packages.build_player_package(session, player.player_id, version)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return FileResponse(
        target,
        filename=target.name,
        media_type="application/zip",
    )


@router.post("/{player_id}/license")
def issue_license(
    player_id: str, session: Session = Depends(db_session), _admin: str = Depends(current_admin)
) -> dict:
    """签发 license 并返回内容；前端可据此下载成 license.bin。"""
    player = session.query(Player).filter(Player.player_id == player_id).one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="玩家不存在")
    return license_module.issue(player.player_id)
