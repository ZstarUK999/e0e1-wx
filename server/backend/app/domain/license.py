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


def player_ids(payload: dict) -> list[str]:
    if "player_ids" not in payload:
        value = payload.get("player_id")
        return [value] if isinstance(value, str) and value else []
    values = payload["player_ids"]
    if not isinstance(values, list) or not 1 <= len(values) <= 500:
        return []
    if any(not isinstance(value, str) or not value.strip() or len(value) > 128 for value in values):
        return []
    if len(set(values)) != len(values) or payload.get("player_id") != values[0]:
        return []
    return values


def canonical_payload(*, license_id: str, player_id: str, issued_at: str, nonce: str, player_ids=None) -> bytes:
    if player_ids is None:
        return f"{license_id}|{player_id}|{issued_at}|{nonce}".encode("utf-8")
    return ("v2|" + json.dumps([license_id, player_id, issued_at, nonce, player_ids], ensure_ascii=False, separators=(",", ":"))).encode("utf-8")


def issue(player_id: str | list[str]) -> dict:
    values = [player_id] if isinstance(player_id, str) else list(player_id)
    if not values or any(not isinstance(value, str) or not value.strip() or len(value) > 128 for value in values):
        raise ValueError("玩家ID不能为空且长度不能超过128")
    values = list(dict.fromkeys(value.strip() for value in values))
    if len(values) > 500:
        raise ValueError("一个包最多授权500名玩家")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {"license_id": uuid.uuid4().hex[:16], "player_id": values[0], "issued_at": now, "nonce": uuid.uuid4().hex[:16]}
    if len(values) > 1:
        payload["player_ids"] = values
    payload["signature"] = base64.b64encode(_private_key().sign(canonical_payload(**payload))).decode("ascii")
    return payload


def verify(payload: dict) -> bool:
    if not isinstance(payload, dict) or not player_ids(payload):
        return False
    try:
        fields = {key: payload[key] for key in ("license_id", "player_id", "issued_at", "nonce")}
        if "player_ids" in payload:
            fields["player_ids"] = payload["player_ids"]
        signature = base64.b64decode(payload["signature"], validate=True)
        _private_key().public_key().verify(signature, canonical_payload(**fields))
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
