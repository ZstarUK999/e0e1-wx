"""license 读取与离线校验：exe 同级的 license.bin。

文件内容是明文 JSON，但改任何字段都会让签名对不上。离线时客户端也必须验签
（否则拿到别人的包、把 player_id 改成自己的号就能离线白用），所以这里内置
公钥 + 一份纯 Python 的 Ed25519 验签，不引入任何依赖。

公钥写成代码里的常量而不是数据文件：改 JSON 比改代码容易太多。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

from . import ed25519

LICENSE_FILE_NAME = "license.bin"

# 部署公钥（Ed25519 裸 32 字节）；换密钥时用 server/backend/tools/show_pubkey.py 取新值
LICENSE_PUBLIC_KEY = bytes.fromhex(
    "d50d263c36b1c026432a077abf14bec97c17b6c9c5ff31944e936f916e9d7aa6"
)

# 必须与服务端 domain/license.py 的 canonical_payload 完全一致
SIGN_FIELDS = ("license_id", "player_id", "issued_at", "nonce")


def license_path() -> Path:
    """冻结后与 exe 同级；源码模式下取仓库根目录（开发用）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / LICENSE_FILE_NAME
    return Path(__file__).resolve().parents[2] / LICENSE_FILE_NAME


def load() -> dict | None:
    """读 license；文件缺失或不是合法 JSON 都返回 None。"""
    path = license_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def verify(payload: dict | None) -> bool:
    """本地验签：确认这份 license 确实是持有私钥的一方签的。"""
    if not isinstance(payload, dict):
        return False
    try:
        signature = base64.b64decode(payload["signature"], validate=True)
        message = "|".join(str(payload[field]) for field in SIGN_FIELDS).encode("utf-8")
    except (KeyError, TypeError, ValueError):
        return False
    return ed25519.verify(LICENSE_PUBLIC_KEY, signature, message)
