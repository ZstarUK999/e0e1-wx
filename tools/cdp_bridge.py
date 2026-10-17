"""单连接常驻 CDP 调试桥，只开放本机、带令牌的 JS 求值接口。

启动：python tools/cdp_bridge.py serve --cdp-port 62000
求值：python tools/cdp_bridge.py eval --code "1+1"
游戏：python tools/cdp_bridge.py eval --context game --code "typeof UIManager"
文件：python tools/cdp_bridge.py eval --context game --file tools/js/example.js
状态／停止：python tools/cdp_bridge.py status / stop

会话令牌保存在 logs/cdp_bridge.json；日志用系统本地时间。
超时不代表 JS 已停止，工具绝不自动重放表达式。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import secrets
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from package.mcp_control.cdp_client import LocalCdpClient

MAX_BODY_BYTES = 1024 * 1024
DEFAULT_SESSION_FILE = Path(__file__).resolve().parents[1] / "logs" / "cdp_bridge.json"
LOG = logging.getLogger("cdp_bridge")
GAME_CONTEXT_PROBE = "typeof globalThis.UIManager !== 'undefined' && typeof globalThis.ROLE !== 'undefined'"


class DebugBridge:
    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.cdp = LocalCdpClient(max_events=100)
        self.execution_lock = asyncio.Lock()
        self.request_count = 0
        self.contexts: dict[int, dict] = {}
        self.game_context_id: int | None = None
        self.cdp.on("Runtime.executionContextCreated", self._context_created)
        self.cdp.on("Runtime.executionContextDestroyed", self._context_destroyed)
        self.cdp.on("Runtime.executionContextsCleared", self._contexts_cleared)

    def _context_created(self, event: dict) -> None:
        context = event.get("params", {}).get("context", {})
        if type(context.get("id")) is int:
            self.contexts[context["id"]] = context

    def _context_destroyed(self, event: dict) -> None:
        context_id = event.get("params", {}).get("executionContextId")
        self.contexts.pop(context_id, None)
        if context_id == self.game_context_id:
            self.game_context_id = None

    def _contexts_cleared(self, event: dict) -> None:
        self.contexts.clear()
        self.game_context_id = None

    async def connect(self) -> None:
        await self.cdp.connect(self.ws_url)
        await self.cdp.send("Runtime.enable", timeout_ms=5000)
        result = await self.evaluate("1+1", timeout_ms=5000)
        if not result["ok"] or result.get("result", {}).get("value") != 2:
            raise RuntimeError("CDP 判活失败：1+1 未返回 2，请确认小程序已回连")

    async def _find_game_context(self) -> int:
        if not self.contexts:
            await self.cdp.send("Runtime.enable", timeout_ms=5000)
        contexts = sorted(self.contexts.values(), key=lambda item: item.get("name") != "gameContext")
        candidates = ([self.game_context_id] if self.game_context_id is not None else []) + [item["id"] for item in contexts]
        # WMPF可能不推送context事件；只读探测有限ID范围，不硬编码当前游戏ID。
        if not self.contexts:
            candidates += list(range(1, 65))
        for context_id in dict.fromkeys(candidates):
            try:
                response = await self.cdp.send("Runtime.evaluate", {"expression": GAME_CONTEXT_PROBE, "returnByValue": True, "contextId": context_id}, timeout_ms=200)
            except (RuntimeError, asyncio.TimeoutError):
                if not self.cdp.is_connected():
                    raise
                continue
            if response.get("result", {}).get("result", {}).get("value") is True:
                self.game_context_id = context_id
                return context_id
        self.game_context_id = None
        raise RuntimeError("未发现 gameContext；请确认游戏已加载，未推送context事件时仅探测ID 1–64")

    async def evaluate(self, expression: str, *, context: str = "top", timeout_ms: int = 15000) -> dict:
        self.request_count += 1
        request_id = self.request_count
        acquired = False
        sent = False
        try:
            # 排队、上下文定位和CDP响应共用一个截止时间，过期请求不迟发。
            async with asyncio.timeout(timeout_ms / 1000.0):
                await self.execution_lock.acquire()
                acquired = True
                params = {"expression": expression, "returnByValue": True, "awaitPromise": True, "includeCommandLineAPI": True}
                if context == "game":
                    params["contextId"] = await self._find_game_context()
                sent = True
                response = await self.cdp.send("Runtime.evaluate", params, timeout_ms=timeout_ms)
            root = response.get("result", {})
            result = {"ok": not bool(root.get("exceptionDetails")), "request_id": request_id, "result": root.get("result", {})}
            if root.get("exceptionDetails"):
                result["exception"] = root["exceptionDetails"]
            return result
        except asyncio.TimeoutError:
            LOG.warning("求值 #%s 超时；已发送=%s，不重放", request_id, sent)
            return {"ok": False, "request_id": request_id, "error": {"kind": "timeout" if sent else "queue_timeout", "message": "请求已超时；已发出的 JS 可能仍在执行，不会自动重放" if sent else "请求排队或定位上下文时超时，未发送用户 JS"}, "execution_may_have_run": sent}
        except Exception as exc:
            LOG.warning("求值 #%s 失败：%s", request_id, exc)
            return {"ok": False, "request_id": request_id, "error": {"kind": "cdp_error", "message": str(exc)}, "execution_may_have_run": sent}
        finally:
            if acquired:
                self.execution_lock.release()

    async def close(self) -> None:
        # 现有客户端拥有独立重连任务，停止桥时也要终止该任务。
        reconnect = self.cdp.reconnect_task
        if reconnect is not None and not reconnect.done():
            reconnect.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reconnect
        await self.cdp.close()


class LocalAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, token: str) -> None:
        super().__init__(app)
        self.authorization = ("Bearer " + token).encode("utf-8")

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        if request.headers.get("origin") is not None or host not in {"127.0.0.1", "localhost"}:
            return JSONResponse({"ok": False, "error": "仅允许本机非浏览器请求"}, status_code=403)
        supplied = request.headers.get("authorization", "").encode("utf-8")
        if not secrets.compare_digest(supplied, self.authorization):
            return JSONResponse({"ok": False, "error": "访问令牌缺失或无效"}, status_code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response


def create_app(bridge: DebugBridge, token: str, stopping: asyncio.Event) -> Starlette:
    async def status(request: Request):
        return JSONResponse({"ok": True, "pid": os.getpid(), "requests": bridge.request_count, "cdp": bridge.cdp.status(), "contexts": list(bridge.contexts.values()), "game_context_id": bridge.game_context_id})

    async def evaluate(request: Request):
        if stopping.is_set():
            return JSONResponse({"ok": False, "error": "调试桥正在停止"}, status_code=503)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse({"ok": False, "error": "请求必须使用 application/json"}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return JSONResponse({"ok": False, "error": "请求超过 1 MiB"}, status_code=413)
            body.extend(chunk)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            return JSONResponse({"ok": False, "error": "请求不是有效 JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "error": "请求必须是 JSON 对象"}, status_code=400)
        expression = payload.get("expression")
        context = payload.get("context", "top")
        timeout = payload.get("timeout_ms", 15000)
        if not isinstance(expression, str) or not expression.strip():
            return JSONResponse({"ok": False, "error": "expression 必须是非空字符串"}, status_code=400)
        if context not in ("top", "game") or type(timeout) is not int or not 100 <= timeout <= 60000:
            return JSONResponse({"ok": False, "error": "context 只能是 top/game；timeout_ms 必须是 100–60000 的整数"}, status_code=400)
        return JSONResponse(await bridge.evaluate(expression, context=context, timeout_ms=timeout))

    async def stop(request: Request):
        stopping.set()
        return JSONResponse({"ok": True, "message": "调试桥正在停止"})

    return Starlette(
        routes=[Route("/status", status), Route("/eval", evaluate, methods=["POST"]), Route("/stop", stop, methods=["POST"])],
        middleware=[Middleware(LocalAccessMiddleware, token=token)],
    )


def _create_private_file(path: Path) -> int:
    if os.name != "nt":
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", wintypes.LPVOID), ("inherit", wintypes.BOOL)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    descriptor = wintypes.LPVOID()
    # 受保护DACL，只允许文件所有者；创建前生效，避免写token后再改权限的窗口。
    if not convert("D:P(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    try:
        handle = create(str(path), 0x40000000, 0, ctypes.byref(attributes), 1, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in (80, 183):
                raise FileExistsError(error, "会话文件已存在", str(path))
            raise ctypes.WinError(error)
        try:
            return msvcrt.open_osfhandle(handle, os.O_WRONLY)
        except Exception:
            kernel.CloseHandle(handle)
            raise
    finally:
        kernel.LocalFree(descriptor)


def write_session_file(path: Path, state: dict) -> None:
    with os.fdopen(_create_private_file(path), "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


async def serve(args) -> int:
    path = args.session_file.absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"会话文件已存在：{path}；请先 status/stop 核对，不会覆盖")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"会话文件父目录不存在：{path.parent}；请指定已有目录")
    bridge = DebugBridge(f"ws://127.0.0.1:{args.cdp_port}")
    stopping = asyncio.Event()
    state = {"port": args.listen_port, "token": secrets.token_urlsafe(32), "pid": os.getpid(), "cdp_port": args.cdp_port}
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    watcher = None
    owns_file = False
    try:
        sock.bind(("127.0.0.1", args.listen_port))
        sock.listen(128)
        sock.setblocking(False)
        await bridge.connect()
        state["port"] = sock.getsockname()[1]
        app = create_app(bridge, state["token"], stopping)
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning", lifespan="off", timeout_graceful_shutdown=5))
        write_session_file(path, state)
        owns_file = True

        async def wait_for_stop():
            await stopping.wait()
            server.should_exit = True

        watcher = asyncio.create_task(wait_for_stop())
        LOG.info("CDP 已判活，调试桥端口 %s，PID %s，会话文件 %s", state["port"], state["pid"], path)
        await server.serve(sockets=[sock])
        return 0
    finally:
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        await bridge.close()
        sock.close()
        if owns_file:
            try:
                if json.loads(path.read_text(encoding="utf-8")) == state:
                    path.unlink()
            except (OSError, ValueError):
                LOG.warning("会话文件未清理，请核对 %s", path)
        LOG.info("调试桥已停止")


def request_from_cli(args) -> dict:
    state = json.loads(args.session_file.read_text(encoding="utf-8"))
    port = state.get("port")
    token = state.get("token")
    if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str) or not token:
        raise ValueError("会话文件中 port/token 无效")
    payload = None
    timeout = 5.0
    if args.command == "eval":
        source = args.code if args.code is not None else args.file.read_text(encoding="utf-8-sig")
        payload = {"expression": source, "context": args.context, "timeout_ms": args.timeout_ms}
        timeout = args.timeout_ms / 1000.0 + 5
    with httpx.Client(trust_env=False, timeout=timeout) as client:
        response = client.request(
            "GET" if args.command == "status" else "POST",
            f"http://127.0.0.1:{port}/{args.command}",
            headers={"Authorization": "Bearer " + token},
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须介于 1–65535")
    return port


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="常驻本机 CDP 调试桥，单连接执行 JS 并返回 JSON")
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve", help="启动常驻桥（前台运行）")
    server.add_argument("--cdp-port", type=port_number, default=62000)
    server.add_argument("--listen-port", type=port_number, default=61999)
    evaluate = commands.add_parser("eval", help="通过常驻桥执行 JS，不新建 CDP 连接")
    source = evaluate.add_mutually_exclusive_group(required=True)
    source.add_argument("--code", help="JS 控制台表达式或语句")
    source.add_argument("--file", type=Path, help="UTF-8 JS 文件")
    evaluate.add_argument("--context", choices=("top", "game"), default="top")
    evaluate.add_argument("--timeout-ms", type=int, default=15000)
    status = commands.add_parser("status", help="查询常驻连接状态")
    stop = commands.add_parser("stop", help="关闭常驻桥及其 CDP 连接")
    for command in (server, evaluate, status, stop):
        command.add_argument("--session-file", type=Path, default=DEFAULT_SESSION_FILE)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    try:
        if args.command == "serve":
            return asyncio.run(serve(args))
        result = request_from_cli(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
