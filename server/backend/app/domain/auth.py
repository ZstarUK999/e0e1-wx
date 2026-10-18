"""握手裁决：包里绑定的 id、游戏里登录的 id、白名单三者必须对上。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..db.models import HandshakeLog, Player
from . import license as license_module

# 拒绝原因码：写进日志，也回给客户端显示。
REASON_OK = "ok"
REASON_BAD_LICENSE = "invalid_license"
REASON_ID_MISMATCH = "player_id_mismatch"
REASON_NOT_ALLOWED = "player_not_allowed"

REASON_MESSAGES = {
    REASON_BAD_LICENSE: "授权文件无效或已被篡改",
    REASON_ID_MISMATCH: "当前登录的账号与插件绑定的账号不一致",
    REASON_NOT_ALLOWED: "该账号未获得插件使用权限",
}


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str
    message: str
    player_id: str = ""

    @classmethod
    def ok(cls, player_id: str) -> "Verdict":
        return cls(True, REASON_OK, "", player_id)

    @classmethod
    def denied(cls, reason: str) -> "Verdict":
        return cls(False, reason, REASON_MESSAGES.get(reason, reason))


def evaluate(*, license_payload: dict | None, login_player_id: str) -> tuple[Verdict | None, str]:
    """纯校验部分：先验签，再比对绑定 id 与登录 id。返回 (裁决, player_id)。

    裁决为 None 表示还需要查白名单。
    """
    if not license_payload or not license_module.verify(license_payload):
        return Verdict.denied(REASON_BAD_LICENSE), ""
    bound = str(license_payload.get("player_id") or "")
    if str(login_player_id or "") not in license_module.player_ids(license_payload):
        return Verdict.denied(REASON_ID_MISMATCH), bound
    return None, str(login_player_id)


def check_whitelist(session: Session, player_id: str) -> Verdict:
    """白名单裁决。"""
    player = session.query(Player).filter(Player.player_id == player_id).one_or_none()
    if player is None or not player.enabled:
        return Verdict.denied(REASON_NOT_ALLOWED)
    return Verdict.ok(player_id)


def record(
    session: Session,
    *,
    verdict: Verdict,
    bound_player_id: str,
    guild: str,
    client_version: str,
    remote: str,
    player_name: str = "",
    login_player_id: str = "",
) -> None:
    """落审计日志；公会名和角色名只记录不校验。"""
    session.add(
        HandshakeLog(
            player_id=login_player_id or verdict.player_id or bound_player_id,
            bound_player_id=bound_player_id,
            player_name=player_name or "",
            guild=guild or "",
            client_version=client_version or "",
            remote=remote or "",
            allowed=verdict.allowed,
            reason=verdict.reason,
        )
    )
    if verdict.allowed:
        player = session.query(Player).filter(Player.player_id == verdict.player_id).one_or_none()
        if player is not None:
            if guild:
                player.guild = guild
            if player_name:
                player.role_name = player_name
