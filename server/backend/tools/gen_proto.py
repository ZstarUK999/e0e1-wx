"""从 plugin.proto 生成服务端与客户端的 pb2 代码。

protoc 生成的是顶层 import，两个生成物都放在子包里，必须改成相对导入。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo/server/backend/tools -> repo
PROTO = ROOT / "server" / "backend" / "app" / "grpc" / "plugin.proto"
TARGETS = (
    ROOT / "server" / "backend" / "app" / "grpc",
    ROOT / "package" / "plugin_manager" / "grpc_stub",
)


def main() -> None:
    for directory in TARGETS:
        directory.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                f"-I{PROTO.parent}",
                f"--python_out={directory}",
                f"--grpc_python_out={directory}",
                str(PROTO),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit(f"生成失败（{directory}）：{result.stderr}")
        generated = directory / "plugin_pb2_grpc.py"
        generated.write_text(
            generated.read_text(encoding="utf-8").replace(
                "import plugin_pb2 as", "from . import plugin_pb2 as"
            ),
            encoding="utf-8",
        )
        print(f"已生成：{directory}")
    init = TARGETS[1] / "__init__.py"
    if not init.exists():
        init.write_text('"""由 plugin.proto 生成，用 tools/gen_proto.py 重新生成。"""\n', encoding="utf-8")


if __name__ == "__main__":
    main()
