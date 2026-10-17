"""license 的签发与校验：Ed25519，私钥只在服务器。

签名的覆盖范围必须包含 player_id，否则玩家改个 id 就能冒充别人。
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..settings import settings

LICENSE_FILE_NAME = "license.bin"


def _private_key() -> Ed25519PrivateKey:
    """读私钥，没有就生成一把并存盘。"""
    path = settings.license_key_path
    if path.is_file():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError("license 私钥不是 Ed25519")
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return key


def public_key_pem() -> str:
    """导出公钥 PEM，便于核对插件侧配置。"""
    return _private_key().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def canonical_payload(*, license_id: str, player_id: str, issued_at: str, nonce: str) -> bytes:
    """参与签名的字段串；改任何一项都会导致验签失败。"""
    return f"{license_id}|{player_id}|{issued_at}|{nonce}".encode("utf-8")


def issue(player_id: str) -> dict:
    """为玩家签发一份 license。"""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "license_id": uuid.uuid4().hex[:16],
        "player_id": str(player_id),
        "issued_at": now,
        "nonce": uuid.uuid4().hex[:16],
    }
    signature = _private_key().sign(canonical_payload(**payload))
    payload["signature"] = base64.b64encode(signature).decode("ascii")
    return payload


def verify(payload: dict) -> bool:
    """校验一份 license 的签名；字段缺失一律算失败。"""
    try:
        signature = base64.b64decode(payload["signature"], validate=True)
        message = canonical_payload(
            license_id=payload["license_id"],
            player_id=payload["player_id"],
            issued_at=payload["issued_at"],
            nonce=payload["nonce"],
        )
    except (KeyError, TypeError, ValueError):
        return False
    try:
        _private_key().public_key().verify(signature, message)
    except Exception:
        return False
    return True


def dumps(payload: dict) -> bytes:
    """license.bin 的文件内容。"""
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def loads(raw: bytes | str) -> dict | None:
    """解析 license.bin；内容不是合法 JSON 时返回 None。"""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None
