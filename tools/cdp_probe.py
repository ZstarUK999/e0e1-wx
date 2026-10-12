"""探测 e0e1-wx DevTools CDP 端点上到底有哪些执行上下文，并逐个确认哪个是游戏主域。

用法（调试会话已连上时）：
    python tools/cdp_probe.py                 # 自动扫描 62000-65535
    python tools/cdp_probe.py --port 62000    # 指定 CDP 端口

会依次输出：
  1. /json/version 与 /json/list 的 target 列表
  2. Runtime.enable 后收到的 Runtime.executionContextCreated 事件（含 contextId / name / origin）
  3. 对每个 contextId 执行探测表达式，看里面有没有 UIManager / TREASURE
  4. 试探 Target.getTargets 是否可用
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


import websockets

# 以脚本方式运行时把项目根目录加进模块搜索路径。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from package.devtools.constants import CDP_PORT_END, CDP_PORT_START  # noqa: E402

FRAME_SCAN_EXPRESSION = """
JSON.stringify((function () {
  var out = { frameCount: -1, iframes: [], frames: [] };
  try { out.frameCount = window.frames ? window.frames.length : -1; } catch (e) { out.frameCount = String(e); }
  try {
    Array.prototype.slice.call(document.querySelectorAll("iframe,embed,object")).forEach(function (el, i) {
      var w = null;
      try { w = el.contentWindow; } catch (e) { w = null; }
      out.iframes.push({
        i: i,
        tag: el.tagName,
        name: el.getAttribute ? el.getAttribute("name") : null,
        src: el.getAttribute ? String(el.getAttribute("src") || "").slice(0, 120) : null,
        reachable: !!w,
        UIManager: w ? typeof w.UIManager : "n/a",
        TREASURE: w ? typeof w.TREASURE : "n/a",
        wx: w ? typeof w.wx : "n/a",
        keys: w ? Object.keys(w).length : -1
      });
    });
  } catch (e) { out.iframes.push({ error: String(e) }); }
  try {
    for (var j = 0; j < window.frames.length; j++) {
      var fw = window.frames[j];
      out.frames.push({ j: j, UIManager: typeof fw.UIManager, TREASURE: typeof fw.TREASURE, keys: Object.keys(fw).length });
    }
  } catch (e) { out.frames.push(String(e)); }
  return out;
})())
""".strip()

PROBE_EXPRESSION = """
JSON.stringify({
  keys: Object.keys(globalThis).length,
  isGameGlobal: (function () {
    try { return globalThis === GameGlobal; } catch (e) { return "no-GameGlobal"; }
  })(),
  wx: typeof wx,
  UIManager: typeof globalThis.UIManager,
  TREASURE: typeof globalThis.TREASURE,
  dumpLegionMembers: typeof globalThis.dumpLegionMembers,
  sample: Object.keys(globalThis).slice(0, 40)
})
""".strip()


async def scan_ports(start: int, end: int) -> list[int]:
    """并发扫描候选端口：工具的 CDP 端点是纯 WebSocket，只能靠握手探测。"""
    semaphore = asyncio.Semaphore(200)

    async def probe(port: int) -> int | None:
        async with semaphore:
            try:
                async with websockets.connect(
                    f"ws://127.0.0.1:{port}", max_size=None, open_timeout=0.5
                ) as ws:
                    await ws.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))
                    await asyncio.wait_for(ws.recv(), timeout=0.8)
                return port
            except Exception:
                return None

    results = await asyncio.gather(*(probe(port) for port in range(start, end + 1)))
    return sorted(port for port in results if port)


class CdpSession:
    """最小 CDP 客户端：发命令、收响应、收集事件。"""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0

    async def __aenter__(self):
        self.ws = await websockets.connect(self.ws_url, max_size=None, open_timeout=5.0)
        return self

    async def __aexit__(self, *exc):
        if self.ws is not None:
            await self.ws.close()

    async def send(self, method: str, params: dict | None = None) -> int:
        self._msg_id += 1
        await self.ws.send(json.dumps({"id": self._msg_id, "method": method, "params": params or {}}))
        return self._msg_id

    async def drain(self, seconds: float, on_event=None) -> dict:
        """在指定时间内收取消息，事件交给回调，返回最后收到的响应。"""
        deadline = time.monotonic() + seconds
        responses: dict = {}
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=max(0.05, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("id") is not None:
                responses[int(data["id"])] = data
            elif on_event and data.get("method"):
                on_event(data)
        return responses

    async def evaluate(self, expression: str, context_id: int | None = None, timeout: float = 5.0):
        """执行表达式，可指定 contextId 打到特定执行上下文。"""
        params = {"expression": expression, "returnByValue": True, "awaitPromise": True}
        if context_id is not None:
            params["contextId"] = context_id
        msg_id = await self.send("Runtime.evaluate", params)
        responses = await self.drain(timeout)
        message = responses.get(msg_id) or {}
        result = message.get("result") or {}
        remote = result.get("result") or {}
        if remote.get("value") is not None:
            return remote["value"]
        details = result.get("exceptionDetails") or {}
        return {"error": details.get("text") or str(result.get("error") or message)}


def render(label: str, value) -> None:
    """格式化输出探测结果。"""
    if value is None:
        print(f"    {label}: 无返回")
        return
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        parsed = value
    text = json.dumps(parsed, ensure_ascii=False, indent=2)
    print(f"    {label}:")
    print("\n".join("      " + line for line in text.splitlines()))


async def probe_target(ws_url: str) -> None:
    """探测单个 target：枚举执行上下文并逐个探测。"""
    async with CdpSession(ws_url) as session:
        contexts: list[dict] = []

        def collect(message: dict) -> None:
            if message.get("method") == "Runtime.executionContextCreated":
                contexts.append((message.get("params") or {}).get("context") or {})

        await session.send("Runtime.enable")
        await session.drain(2.0, on_event=collect)

        if not contexts:
            print("    未收到 Runtime.executionContextCreated（端点不推送上下文事件）")
            render("默认上下文探测", await session.evaluate(PROBE_EXPRESSION))

            # 有 DOM 就说明可能是 iframe 结构，从当前页面往子框架里找游戏。
            print("\n    --- iframe / frames 扫描（当前上下文内）---")
            render("结果", await session.evaluate(FRAME_SCAN_EXPRESSION))

            # 拿不到上下文列表就直接暴力试 contextId，看端点认不认这个参数。
            print("\n    --- 暴力试 contextId 1..24 ---")
            for context_id in range(1, 25):
                value = await session.evaluate(PROBE_EXPRESSION, context_id=context_id, timeout=1.5)
                if value is None:
                    continue
                try:
                    parsed = json.loads(value) if isinstance(value, str) else value
                except json.JSONDecodeError:
                    parsed = value
                if isinstance(parsed, dict) and parsed.get("error"):
                    print(f"      contextId={context_id}: {str(parsed.get('error'))[:90]}")
                    continue
                marker = "UIManager=" + str((parsed or {}).get("UIManager"))
                print(f"      contextId={context_id}: {marker} keys={(parsed or {}).get('keys')}")
            return

        print(f"    发现 {len(contexts)} 个执行上下文：")
        for context in contexts:
            print(
                "      id={id} name={name!r} origin={origin!r} frameId={frame}".format(
                    id=context.get("id"),
                    name=str(context.get("name") or ""),
                    origin=str(context.get("origin") or ""),
                    frame=(context.get("auxData") or {}).get("frameId"),
                )
            )

        for context in contexts:
            context_id = context.get("id")
            name = str(context.get("name") or context_id)
            print(f"\n    --- contextId={context_id} name={name!r} ---")
            render("结果", await session.evaluate(PROBE_EXPRESSION, context_id=context_id))

        try:
            await session.send("Target.getTargets")
            responses = await session.drain(2.0)
            for message in responses.values():
                print("\n    [Target.getTargets] " + json.dumps(message, ensure_ascii=False)[:1200])
        except Exception as exc:
            print(f"\n    [Target.getTargets] 失败：{exc}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="探测 e0e1-wx 的 CDP 执行上下文")
    parser.add_argument("--port", type=int, default=0, help=f"CDP 端口，默认扫描 {CDP_PORT_START}-{CDP_PORT_END}")
    args = parser.parse_args()

    ports = [args.port] if args.port else await scan_ports(CDP_PORT_START, CDP_PORT_END)
    if not ports:
        print("未发现可用的 CDP 端口，请先开启调试并等待小程序回连")
        return 1

    for port in ports:
        print(f"\n===== CDP 端口 {port} =====")
        try:
            await probe_target(f"ws://127.0.0.1:{port}")
        except Exception as exc:
            print(f"    探测失败：{exc}")

    print("\n判读：UIManager / TREASURE 为 object 的那个 contextId 才是游戏主域（gameContext）。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
