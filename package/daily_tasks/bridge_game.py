"""通过现有常驻CDP桥执行自身正常UI操作，不新建游戏WebSocket。"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from .scheduler import ExecutionUncertain, RetryableTaskError

RUNTIME_PATH = Path(__file__).with_name("sweep_runtime.js")
DEFAULT_BRIDGE_SESSION = Path(__file__).resolve().parents[2] / "logs" / "cdp_bridge.json"
TRANSACTION_DIR = DEFAULT_BRIDGE_SESSION.parent


class BridgeGame:
    def __init__(self, session_file: Path = DEFAULT_BRIDGE_SESSION, *, client: httpx.AsyncClient | None = None) -> None:
        self.session_file = Path(session_file)
        self.client = client
        self.owns_client = client is None

    async def close(self) -> None:
        if self.owns_client and self.client is not None:
            await self.client.aclose()
            self.client = None

    @asynccontextmanager
    async def transaction(self, journal_path: Path):
        try:
            state = json.loads(self.session_file.read_text(encoding="utf-8"))
            port = state.get("port")
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("调试桥端口无效")
        except (OSError, ValueError) as exc:
            raise RetryableTaskError(f"无法开始扫荡轮次，尚未修改配置：{exc}") from exc
        # 与用户选择的配置/恢复文件无关：同一常驻桥整轮排他。
        lock = TRANSACTION_DIR / f"energy.{port}.transaction.json"
        record = {"pid": os.getpid(), "journal": str(Path(journal_path).absolute())}
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            try:
                old = json.loads(lock.read_text(encoding="utf-8"))
                journal = Path(old["journal"])
            except (OSError, ValueError, KeyError):
                raise ExecutionUncertain(f"存在无法确认的扫荡轮次记录 {lock}") from exc
            if journal.exists():
                raise ExecutionUncertain(f"存在未恢复的账号轮次 {lock}，禁止另配置重复操作") from exc
            raise RetryableTaskError(f"账号已有扫荡轮次占用 {lock}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(record, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        uncertain = False
        try:
            yield
        except ExecutionUncertain:
            uncertain = True
            raise
        finally:
            if not uncertain and not Path(journal_path).exists():
                if json.loads(lock.read_text(encoding="utf-8")) != record:
                    raise ExecutionUncertain("账号轮次记录被修改，不能释放锁")
                lock.unlink()

    async def _request(self, op: str, payload: dict | None = None):
        mutating = op not in {"inspect", "catalog", "capture"}
        try:
            state = json.loads(self.session_file.read_text(encoding="utf-8"))
            port, token = state.get("port"), state.get("token")
            if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str) or not token:
                raise ValueError("调试桥会话文件无效")
            source = RUNTIME_PATH.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            raise RetryableTaskError(f"无法读取调试桥会话/运行脚本，尚未发请求：{exc}") from exc
        expression = f"(async () => {{\n{source}\nreturn await createEnergyRuntime(globalThis).dispatch({json.dumps(op)}, {json.dumps(payload or {}, ensure_ascii=False, allow_nan=False)});\n}})()"
        if self.client is None:
            self.client = httpx.AsyncClient(trust_env=False, timeout=20)
        job = asyncio.create_task(self.client.post(
            f"http://127.0.0.1:{port}/eval", headers={"Authorization": "Bearer " + token},
            json={"expression": expression, "context": "game", "timeout_ms": 15000}))
        # 取消调度不能在外部JS仍执行时抢先恢复；等待本次请求确认后再传播取消。
        cancelled = False
        try:
            try:
                response = await asyncio.shield(job)
            except asyncio.CancelledError:
                cancelled = True
                response = await asyncio.shield(job)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                if body.get("execution_may_have_run") is False:
                    raise RetryableTaskError(f"JS尚未执行：{body.get('error')}")
                raise ExecutionUncertain("CDP执行失败/超时，操作结果未知，不重放")
            receipt = body.get("result", {}).get("value")
            if not isinstance(receipt, dict):
                raise ExecutionUncertain("CDP未返回正常操作回执")
            if receipt.get("status") in {"rejected", "unavailable"}:
                raise RetryableTaskError(receipt.get("message", "正常UI操作未获准"))
            if receipt.get("status") != "ok":
                raise ExecutionUncertain(receipt.get("message", "正常UI操作结果未知"))
            if cancelled:
                raise asyncio.CancelledError
            return receipt.get("value")
        except (httpx.HTTPError, ValueError) as exc:
            if mutating:
                raise ExecutionUncertain(f"请求已发送但未确认：{exc}") from exc
            raise RetryableTaskError(f"只读检查失败：{exc}") from exc

    async def inspect(self):
        return await self._request("inspect")

    async def catalog(self, name: str):
        return await self._request("catalog", {"name": name})

    async def capture(self):
        return await self._request("capture")

    async def set_eye(self, eye: int):
        return await self._request("eye", {"eye": eye})

    async def select(self, choice: dict):
        return await self._request("select", choice)

    async def home(self):
        return await self._request("home")

    async def quote(self):
        return await self._request("quote")

    async def sweep(self):
        return await self._request("sweep")

    async def restore(self, original: dict):
        return await self._request("restore", {"original": original})
