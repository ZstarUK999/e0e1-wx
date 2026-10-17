"""打印部署公钥，用于把值填进 package/plugin_manager/license.py 的 LICENSE_PUBLIC_KEY。

用法::

    python tools/show_pubkey.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives import serialization  # noqa: E402

from app.domain import license as license_module  # noqa: E402
from app.settings import settings  # noqa: E402

PUBLIC_KEY_CONST = "package/plugin_manager/license.py"


def main() -> int:
    key = license_module._private_key()
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    print(f"私钥文件：{settings.license_key_path}")
    print(f"公钥 hex：{raw.hex()}")
    print(f"\n把它替换到 {PUBLIC_KEY_CONST} 的 LICENSE_PUBLIC_KEY 里，然后重新构建客户端。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
