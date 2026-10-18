"""gRPC 服务实现：握手裁决与更新 diff。

数据库操作是同步的，这里用 to_thread 丢出去，避免阻塞 gRPC 的事件循环。
"""

from __future__ import annotations

import asyncio
import time

import grpc

from ..db.session import session_scope
from ..domain import auth as auth_domain
from ..domain import updates as updates_domain
from . import plugin_pb2, plugin_pb2_grpc


def _license_from(request) -> dict | None:
    license_message = request.license
    if not license_message.license_id:
        return None
    payload = {
        "license_id": license_message.license_id,
        "player_id": license_message.player_id,
        "issued_at": license_message.issued_at,
        "nonce": license_message.nonce,
        "signature": license_message.signature,
    }

    if license_message.player_ids:
        payload["player_ids"] = list(license_message.player_ids)
    return payload


class PluginServicer(plugin_pb2_grpc.PluginServiceServicer):
    def __init__(self, peer_resolver=None) -> None:
        self._peer_resolver = peer_resolver

    async def Handshake(self, request, context):
        payload = _license_from(request)
        verdict, bound = auth_domain.evaluate(
            license_payload=payload,
            login_player_id=request.login_player_id,
        )
        # 只记录验签通过的包绑定，不能信任无效授权文件声称的归属。
        package_ids = (auth_domain.license_module.player_ids(payload)
                       if payload and (verdict is None or verdict.reason != auth_domain.REASON_BAD_LICENSE) else [])
        remote = _peer(context)

        def decide():
            with session_scope() as session:
                if verdict is None:
                    final = auth_domain.check_whitelist(session, bound)
                else:
                    final = verdict
                auth_domain.record(
                    session,
                    verdict=final,
                    bound_player_id=package_ids[0] if package_ids else bound,
                    bound_player_ids=package_ids,
                    guild=request.guild_name,
                    client_version=request.client_version,
                    remote=remote,
                    player_name=request.player_name,
                    login_player_id=request.login_player_id,
                )
                release = updates_domain.current_release(session)
                latest = release.version if release is not None else ""
                mandatory = bool(release.mandatory) if release is not None else False
                return final, latest, mandatory

        final, latest, mandatory = await asyncio.to_thread(decide)
        return plugin_pb2.HandshakeResponse(
            allowed=final.allowed,
            reason=final.reason,
            message=final.message,
            server_time=int(time.time()),
            latest_version=latest,
            # 强制更新只看开关：勾了就必须更新才能继续用
            update_required=bool(latest) and mandatory,
        )

    async def CheckUpdate(self, request, context):
        local = {item.path: item.sha256 for item in request.files if item.path}

        def compute():
            with session_scope() as session:
                release = updates_domain.current_release(session)
                if release is None:
                    return None
                changed, removed = updates_domain.diff(session, release, local)
                return release, changed, removed

        result = await asyncio.to_thread(compute)
        if result is None:
            return plugin_pb2.UpdateResponse(version="", mandatory=False, changelog="")
        release, changed, removed = result
        return plugin_pb2.UpdateResponse(
            version=release.version,
            mandatory=bool(release.mandatory),
            changelog=release.changelog,
            changed=[
                plugin_pb2.FileEntry(
                    path=item["path"], sha256=item["sha256"], size=item["size"], url=item["url"]
                )
                for item in changed
            ],
            removed=removed,
        )


def _peer(context) -> str:
    """取对端地址用于审计；取不到就留空。"""
    try:
        return str(context.peer() or "")
    except Exception:
        return ""


def register(server: grpc.aio.Server) -> None:
    plugin_pb2_grpc.add_PluginServiceServicer_to_server(PluginServicer(), server)
