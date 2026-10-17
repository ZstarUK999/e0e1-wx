"""后台连接：mTLS gRPC，只在 release 构建里启用。

调试版（或源码运行）一律不连后台，handshake 直接返回"调试版，跳过鉴权"。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
import sys

from . import license as license_module
from .build_info import current as build_info

LOG = logging.getLogger('plugin_manager.server')

CERT_DIR_NAME = "certs"


class ServerUnavailable(RuntimeError):
    """连不上后台：证书缺失、gRPC 未打包或网络不通。"""


@dataclass(frozen=True)
class HandshakeResult:
    allowed: bool
    reason: str
    message: str
    latest_version: str
    update_required: bool
    skipped: bool = False   # 调试版：没连后台
    offline: bool = False   # 后台连不上，走了本地比对

    @classmethod
    def debug_skip(cls) -> "HandshakeResult":
        return cls(True, "debug", "调试版：未启用后台鉴权", "", False, skipped=True)


def cert_dir() -> Path:
    """证书目录：冻结后在 _internal/certs，源码下用仓库里的服务端证书目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "_internal" / CERT_DIR_NAME
    return Path(__file__).resolve().parents[2] / "server" / "backend" / "certs" / "client"


def _channel_credentials():
    import grpc

    directory = cert_dir()
    ca = (directory / "ca.pem").read_bytes()
    key = (directory / "client.key").read_bytes()
    cert = (directory / "client.pem").read_bytes()
    return grpc.ssl_channel_credentials(root_certificates=ca, private_key=key, certificate_chain=cert)


def _stub(target: str):
    import grpc

    from .grpc_stub import plugin_pb2_grpc

    channel = grpc.secure_channel(target, _channel_credentials())
    return plugin_pb2_grpc.PluginServiceStub(channel), channel


def handshake(*, player_id: str, legion_name: str, player_name: str = "") -> HandshakeResult:
    """启动时的一次性鉴权。

    后台连得上就以后台裁决为准（白名单生效）；连不上则退化为本地比对——
    包里绑定的 id 与游戏登录 id 一致就放行，保证服务器挂了也能离线用。
    """
    info = build_info()
    if not info.is_release:
        LOG.info('调试版构建：跳过后台鉴权')
        return HandshakeResult.debug_skip()

    payload = license_module.load()
    if payload is None:
        return HandshakeResult(False, "no_license", "缺少授权文件 license.bin", "", False)

    try:
        return _rpc_handshake(payload, player_id, legion_name, info, player_name)
    except Exception as exc:
        LOG.warning('后台不可用，转本地校验：%s', exc)
        return _offline_verdict(payload, player_id)


def _offline_verdict(payload: dict, player_id: str) -> HandshakeResult:
    """服务器没了也要能用：先验签，再比对绑定 id 与登录 id。

    少了验签这一步，别人拿到包把 player_id 改成自己的号就能离线白用。
    """
    bound, reason = license_module.bound_player_id(payload)
    if bound is None:
        return HandshakeResult(
            False,
            "invalid_license",
            reason,
            "",
            False,
            offline=True,
        )
    if bound == str(player_id or ""):
        return HandshakeResult(
            True, "offline_ok", "后台不可用，已按本地绑定放行", "", False, offline=True
        )
    return HandshakeResult(
        False, "player_id_mismatch", "当前登录的账号与插件绑定的账号不一致", "", False, offline=True
    )


def _rpc_handshake(
    payload: dict, player_id: str, legion_name: str, info, player_name: str = ""
) -> HandshakeResult:
    try:
        stub, channel = _stub(info.target)
    except ImportError as exc:
        raise ServerUnavailable(f"该构建未包含后台连接模块：{exc}") from exc
    except (OSError, ValueError) as exc:
        raise ServerUnavailable(f"证书不可用：{exc}") from exc

    try:
        from .grpc_stub import plugin_pb2

        request = plugin_pb2.HandshakeRequest(
            license=plugin_pb2.License(
                license_id=str(payload.get("license_id") or ""),
                player_id=str(payload.get("player_id") or ""),
                issued_at=str(payload.get("issued_at") or ""),
                nonce=str(payload.get("nonce") or ""),
                signature=str(payload.get("signature") or ""),
            ),
            login_player_id=str(player_id or ""),
            guild_name=str(legion_name or ""),
            player_name=str(player_name or ""),
            client_version=info.version,
        )
        response = stub.Handshake(request, timeout=15)
    except Exception as exc:  # gRPC 的各种异常都归为"连不上"
        raise ServerUnavailable(f"无法连接后台：{exc}") from exc
    finally:
        channel.close()

    return HandshakeResult(
        allowed=bool(response.allowed),
        reason=str(response.reason or ""),
        message=str(response.message or ""),
        latest_version=str(response.latest_version or ""),
        update_required=bool(response.update_required),
    )


def check_update(local_manifest: dict[str, str], *, player_id: str) -> dict | None:
    """上报本地文件 hash 清单，取回需要下载/删除的文件；没有生效版本返回 None。"""
    info = build_info()
    if not info.is_release:
        return None
    try:
        stub, channel = _stub(info.target)
    except Exception as exc:
        raise ServerUnavailable(f"无法连接后台：{exc}") from exc

    try:
        from .grpc_stub import plugin_pb2

        request = plugin_pb2.UpdateRequest(
            client_version=info.version,
            player_id=str(player_id or ""),
            files=[
                plugin_pb2.FileEntry(path=path, sha256=digest)
                for path, digest in sorted(local_manifest.items())
            ],
        )
        response = stub.CheckUpdate(request, timeout=30)
    except Exception as exc:
        raise ServerUnavailable(f"更新检查失败：{exc}") from exc
    finally:
        channel.close()

    if not response.version:
        return None
    return {
        "version": response.version,
        "mandatory": bool(response.mandatory),
        "changelog": response.changelog,
        "changed": [
            {"path": item.path, "sha256": item.sha256, "size": item.size, "url": item.url}
            for item in response.changed
        ],
        "removed": list(response.removed),
    }
