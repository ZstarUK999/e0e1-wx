"""通过已建立的 CDP 会话注入 tools/js 下的脚本（等价于 GUI 里的「注入」按钮）。

用法：
    python tools/cdp_inject.py --port 62000 tools/js/player_info_dump.js
    python tools/cdp_inject.py --port 62000 tools/js/legion_members_dump.js tools/js/treasure_map_dump.js

走的是 package.js_injection.runtime 里 GUI 同一套包装逻辑（once / 手动注入模式），
所以脚本里的 __e0e1JsInjectionReport 可用，返回值会解析成 ok / message / log。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cdp_probe  # noqa: E402
from package.devtools.constants import CDP_PORT_END, CDP_PORT_START  # noqa: E402
from package.js_injection.runtime import (  # noqa: E402
    build_injection_expression,
    parse_injection_response,
)
from package.js_injection.runtime_toggle import enable_runtime_js_file  # noqa: E402


class _SessionBridge:
    """把 CdpSession 适配成 runtime_toggle 需要的 bridge 接口。"""

    def __init__(self, session: cdp_probe.CdpSession) -> None:
        self.session = session

    async def send_cdp_command(self, method, params=None, timeout=5.0):
        msg_id = await self.session.send(method, params or {})
        responses = await self.session.drain(timeout)
        return responses.get(msg_id) or {}


async def inject_one(session: cdp_probe.CdpSession, script_path: Path) -> dict:
    """注入单个脚本文件并返回解析后的结果。"""
    source = script_path.read_text(encoding="utf-8")
    script = {
        "id": hashlib.sha1(str(script_path.resolve()).casefold().encode("utf-8")).hexdigest(),
        "name": script_path.stem,
        "path": str(script_path.resolve()),
    }
    content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    expression = build_injection_expression(script, source, content_hash, automatic=False)
    msg_id = await session.send(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "includeCommandLineAPI": True,
        },
    )
    responses = await session.drain(15.0)
    raw = responses.get(msg_id) or {}
    if not raw:
        raise RuntimeError("CDP 无响应（小程序可能未回连）")
    return parse_injection_response(raw)


async def main() -> int:
    parser = argparse.ArgumentParser(description="通过 CDP 注入 JS 脚本")
    parser.add_argument("scripts", nargs="+", help="tools/js 下的 .js 文件路径")
    parser.add_argument("--port", type=int, default=0, help=f"CDP 端口，默认扫描 {CDP_PORT_START}-{CDP_PORT_END}")
    parser.add_argument(
        "--toggle",
        action="store_true",
        help="按长期脚本模式启用（每个新 document 自动注入，上下文重建后依然生效）",
    )
    args = parser.parse_args()

    ports = [args.port] if args.port else await cdp_probe.scan_ports(CDP_PORT_START, CDP_PORT_END)
    if not ports:
        print("未发现可用的 CDP 端口，请先开启调试并等待小程序回连")
        return 1

    port = ports[0]
    print(f"===== CDP 端口 {port} =====")
    async with cdp_probe.CdpSession(f"ws://127.0.0.1:{port}") as session:
        for raw_path in args.scripts:
            path = Path(raw_path)
            if not path.exists():
                print(f"\n[{path.name}] 文件不存在")
                continue
            print(f"\n----- {path.name} -----")
            try:
                if args.toggle:
                    script = {
                        "id": hashlib.sha1(str(path.resolve()).casefold().encode("utf-8")).hexdigest(),
                        "name": path.stem,
                        "path": str(path.resolve()),
                    }
                    result = await enable_runtime_js_file(_SessionBridge(session), script)
                else:
                    result = await inject_one(session, path)
            except Exception as exc:
                print(f"注入失败：{exc}")
                continue
            print("ok:", result.get("ok"), "| skipped:", result.get("skipped"))
            print("enabled:", result.get("enabled"))
            print("message:", result.get("message"))
            if result.get("persistent_identifier"):
                print("persistent:", result["persistent_identifier"])
            if result.get("log"):
                print("log:\n" + result["log"])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
