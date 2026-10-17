"""常驻调试桥的本地集成测试，不连接真实游戏。"""

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import websockets


def bridge_module():
    try:
        return importlib.import_module("tools.cdp_bridge")
    except ModuleNotFoundError as exc:
        if exc.name == "tools.cdp_bridge":
            pytest.fail("缺少常驻 CDP 调试桥 tools.cdp_bridge")
        raise


def test_reuses_one_connection_and_preserves_results():
    async def scenario():
        module = bridge_module()
        connections = []
        messages = []

        async def cdp_peer(ws):
            connections.append(ws)
            async for raw in ws:
                message = json.loads(raw)
                messages.append(message)
                if message["method"] == "Runtime.enable":
                    await ws.send(json.dumps({"method": "Runtime.executionContextCreated", "params": {"context": {"id": 7}}}))
                    result = {}
                else:
                    expression = message["params"]["expression"]
                    remote = {
                        "1+1": {"type": "number", "value": 2},
                        "null": {"type": "object", "subtype": "null", "value": None},
                        "undefined": {"type": "undefined"},
                        "NaN": {"type": "number", "unserializableValue": "NaN"},
                        "({name:'测试'})": {"type": "object", "value": {"name": "测试"}},
                    }.get(expression, {"type": "number", "value": 42})
                    result = {"result": remote}
                await ws.send(json.dumps({"id": message["id"], "result": result}, ensure_ascii=False))

        async with websockets.serve(cdp_peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            bridge = module.DebugBridge(f"ws://127.0.0.1:{port}")
            await bridge.connect()
            try:
                app = module.create_app(bridge, "test-secret", asyncio.Event())
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"Authorization": "Bearer test-secret"}) as client:
                    for expression, expected in [("1+1", 2), ("null", None), ("({name:'测试'})", {"name": "测试"})]:
                        response = await client.post("/eval", json={"expression": expression})
                        assert response.status_code == 200
                        assert response.json()["ok"]
                        assert response.json()["result"]["value"] == expected
                    undefined = (await client.post("/eval", json={"expression": "undefined"})).json()
                    assert undefined["result"] == {"type": "undefined"}
                    nan = (await client.post("/eval", json={"expression": "NaN"})).json()
                    assert nan["result"]["unserializableValue"] == "NaN"
                    status = (await client.get("/status")).json()
                    assert status["cdp"]["connected"]
                    assert status["cdp"]["pendingCalls"] == 0
                    assert len(connections) == 1
                    assert len({m["id"] for m in messages}) == len(messages)
            finally:
                await bridge.close()
            assert not bridge.cdp.is_connected()
            assert not bridge.cdp.pending

    asyncio.run(scenario())


def test_rejects_unauthorized_browser_and_invalid_requests():
    async def scenario():
        module = bridge_module()
        bridge = module.DebugBridge("ws://127.0.0.1:62000")
        stopping = asyncio.Event()
        app = module.create_app(bridge, "secret", stopping)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            assert (await client.get("/status")).status_code == 401
            client.headers["Authorization"] = "Bearer wrong"
            assert (await client.post("/stop")).status_code == 401
            client.headers["Authorization"] = "Bearer secret"
            assert (await client.get("/status", headers={"Origin": "https://untrusted.example"})).status_code == 403
            assert (await client.get("/status", headers={"Host": "untrusted.example"})).status_code == 403
            assert (await client.post("/eval", content="{}", headers={"Content-Type": "text/plain"})).status_code == 415
            for payload in [{}, [], {"expression": 3}, {"expression": " "}, {"expression": "1", "context": "unknown"}, {"expression": "1", "timeout_ms": True}, {"expression": "1", "timeout_ms": 0}]:
                assert (await client.post("/eval", json=payload)).status_code == 400
            assert (await client.post("/eval", content="{", headers={"Content-Type": "application/json"})).status_code == 400
            assert (await client.post("/eval", json={"expression": "x" * (module.MAX_BODY_BYTES + 1)})).status_code == 413
            assert (await client.post("/stop")).json()["ok"]
            assert stopping.is_set()

    asyncio.run(scenario())


def test_reports_js_exception_timeout_and_late_reply_without_replay():
    async def scenario():
        module = bridge_module()
        sent = []
        delayed = []
        hold = asyncio.Event()

        async def reply_late(ws, message):
            await hold.wait()
            await ws.send(json.dumps({"id": message["id"], "result": {"result": {"type": "number", "value": 99}}}))

        async def cdp_peer(ws):
            async for raw in ws:
                message = json.loads(raw)
                expression = message.get("params", {}).get("expression", "")
                sent.append(expression)
                if expression == "never()":
                    delayed.append(asyncio.create_task(reply_late(ws, message)))
                    continue
                if expression == "throw new Error('bad')":
                    result = {"result": {"type": "object"}, "exceptionDetails": {"text": "Uncaught", "exception": {"description": "Error: bad"}}}
                elif message["method"] == "Runtime.enable":
                    result = {}
                else:
                    result = {"result": {"type": "number", "value": 2}}
                await ws.send(json.dumps({"id": message["id"], "result": result}))

        async with websockets.serve(cdp_peer, "127.0.0.1", 0) as server:
            bridge = module.DebugBridge(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
            await bridge.connect()
            try:
                exception = await bridge.evaluate("throw new Error('bad')")
                assert not exception["ok"]
                assert exception["exception"]["exception"]["description"] == "Error: bad"
                timeout = await bridge.evaluate("never()", timeout_ms=100)
                assert not timeout["ok"]
                assert timeout["error"]["kind"] == "timeout"
                assert timeout["execution_may_have_run"]
                assert sent.count("never()") == 1
                assert not bridge.cdp.pending
                hold.set()
                await asyncio.gather(*delayed)
                assert (await bridge.evaluate("1+1"))["result"]["value"] == 2
                assert sent.count("never()") == 1
            finally:
                hold.set()
                await bridge.close()

    asyncio.run(scenario())


def test_game_context_is_discovered_without_window_eval_and_recreated():
    async def scenario():
        module = bridge_module()
        chosen = []
        game_context = 71

        async def cdp_peer(ws):
            nonlocal game_context
            async for raw in ws:
                message = json.loads(raw)
                params = message.get("params", {})
                if message["method"] == "Runtime.enable":
                    for context_id, name in [(2, ""), (game_context, "gameContext")]:
                        await ws.send(json.dumps({"method": "Runtime.executionContextCreated", "params": {"context": {"id": context_id, "name": name}}}))
                    result = {}
                elif params.get("expression") == "1+1":
                    result = {"result": {"type": "number", "value": 2}}
                elif params.get("expression") == module.GAME_CONTEXT_PROBE:
                    result = {"result": {"type": "boolean", "value": params.get("contextId") == game_context}}
                else:
                    assert params["expression"] == "typeof UIManager"
                    chosen.append(params.get("contextId"))
                    result = {"result": {"type": "string", "value": "function"}}
                    if game_context == 71:
                        await ws.send(json.dumps({"method": "Runtime.executionContextDestroyed", "params": {"executionContextId": 71}}))
                        game_context = 92
                        await ws.send(json.dumps({"method": "Runtime.executionContextCreated", "params": {"context": {"id": 92, "name": "gameContext"}}}))
                await ws.send(json.dumps({"id": message["id"], "result": result}))

        async with websockets.serve(cdp_peer, "127.0.0.1", 0) as server:
            bridge = module.DebugBridge(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
            await bridge.connect()
            try:
                for _ in range(2):
                    result = await bridge.evaluate("typeof UIManager", context="game")
                    assert result["ok"]
                    assert result["result"]["value"] == "function"
                assert chosen == [71, 92]
            finally:
                await bridge.close()

    asyncio.run(scenario())


def test_game_context_is_discovered_when_endpoint_emits_no_context_events():
    async def scenario():
        module = bridge_module()
        tested = []

        async def cdp_peer(ws):
            async for raw in ws:
                message = json.loads(raw)
                params = message.get("params", {})
                if message["method"] == "Runtime.enable":
                    result = {}
                elif params.get("expression") == module.GAME_CONTEXT_PROBE:
                    tested.append(params.get("contextId"))
                    result = {"result": {"type": "boolean", "value": params.get("contextId") == 37}}
                elif params.get("expression") == "1+1":
                    result = {"result": {"type": "number", "value": 2}}
                else:
                    assert params.get("contextId") == 37
                    result = {"result": {"type": "string", "value": "function"}}
                await ws.send(json.dumps({"id": message["id"], "result": result}))

        async with websockets.serve(cdp_peer, "127.0.0.1", 0) as server:
            bridge = module.DebugBridge(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
            await bridge.connect()
            try:
                assert (await bridge.evaluate("typeof UIManager", context="game"))["result"]["value"] == "function"
                assert bridge.game_context_id == 37
                count = len(tested)
                assert (await bridge.evaluate("typeof UIManager", context="game"))["ok"]
                assert tested[count:] == [37]
            finally:
                await bridge.close()

    asyncio.run(scenario())


def test_queued_request_expires_without_being_sent():
    async def scenario():
        module = bridge_module()
        entered = asyncio.Event()
        release = asyncio.Event()
        sent = []

        async def cdp_peer(ws):
            async for raw in ws:
                message = json.loads(raw)
                expression = message.get("params", {}).get("expression")
                sent.append(expression)
                if expression == "long()":
                    entered.set()
                    await release.wait()
                result = {"result": {"type": "number", "value": 2}} if expression else {}
                await ws.send(json.dumps({"id": message["id"], "result": result}))

        async with websockets.serve(cdp_peer, "127.0.0.1", 0) as server:
            bridge = module.DebugBridge(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
            await bridge.connect()
            first = asyncio.create_task(bridge.evaluate("long()", timeout_ms=1000))
            await entered.wait()
            second = asyncio.create_task(bridge.evaluate("queued()", timeout_ms=100))
            try:
                result = await asyncio.wait_for(asyncio.shield(second), 0.3)
                assert not result["ok"]
                assert result["error"]["kind"] == "queue_timeout"
                assert not result["execution_may_have_run"]
                assert "queued()" not in sent
            finally:
                release.set()
                await asyncio.gather(first, second)
                await bridge.close()

    asyncio.run(scenario())


def test_session_file_is_private_and_does_not_overwrite(tmp_path):
    module = bridge_module()
    path = tmp_path / "bridge.json"
    state = {"port": 61999, "token": "secret", "pid": 123}
    module.write_session_file(path, state)
    assert json.loads(path.read_text(encoding="utf-8")) == state
    with pytest.raises(FileExistsError):
        module.write_session_file(path, {"token": "other"})
    assert json.loads(path.read_text(encoding="utf-8")) == state


def test_session_file_permissions_only_allow_owner(tmp_path):
    module = bridge_module()
    path = tmp_path / "private.json"
    module.write_session_file(path, {"token": "private"})
    if os.name == "nt":
        import win32security
        sd = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
        control, _ = sd.GetSecurityDescriptorControl()
        assert control & win32security.SE_DACL_PROTECTED
        acl = sd.GetSecurityDescriptorDacl()
        assert acl.GetAceCount() == 1
        assert win32security.ConvertSidToStringSid(acl.GetAce(0)[2]) == "S-1-3-4"
    else:
        assert path.stat().st_mode & 0o777 == 0o600


def test_serve_does_not_follow_dangling_session_symlink(tmp_path):
    module = bridge_module()
    target = tmp_path / "secret-target.json"
    link = tmp_path / "session.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前系统不允许创建符号链接")
    from argparse import Namespace
    args = Namespace(session_file=link, cdp_port=62000, listen_port=61999)
    with pytest.raises(FileExistsError):
        asyncio.run(module.serve(args))
    assert not target.exists()


def test_independent_cli_processes_reuse_bridge_and_stop_cleanly(tmp_path):
    async def scenario():
        module = bridge_module()
        connections = []
        evaluations = []
        session_file = tmp_path / "session.json"
        source_file = tmp_path / "expression.js"
        source_file.write_text("({label:'中文'})", encoding="utf-8")
        script = Path(module.__file__)

        async def cdp_peer(ws):
            connections.append(ws)
            async for raw in ws:
                message = json.loads(raw)
                result = {}
                if message["method"] == "Runtime.evaluate":
                    expression = message["params"]["expression"]
                    evaluations.append(expression)
                    value = {"label": "中文"} if expression == "({label:'中文'})" else 2
                    result = {"result": {"type": "object" if isinstance(value, dict) else "number", "value": value}}
                await ws.send(json.dumps({"id": message["id"], "result": result}, ensure_ascii=False))

        async def cli(*arguments):
            process = await asyncio.create_subprocess_exec(sys.executable, str(script), *arguments, "--session-file", str(session_file), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
            assert process.returncode == 0, stderr.decode("utf-8")
            return json.loads(stdout)

        async with websockets.serve(cdp_peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            # 绑定端口0仅用于集成测试，生产CLI使用显式本机端口。
            import socket
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                api_port = sock.getsockname()[1]
            process = await asyncio.create_subprocess_exec(sys.executable, str(script), "serve", "--cdp-port", str(port), "--listen-port", str(api_port), "--session-file", str(session_file), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                ready = await asyncio.wait_for(process.stderr.readline(), 15)
                assert "CDP 已判活" in ready.decode("utf-8"), ready
                assert (await cli("status"))["cdp"]["connected"]
                assert (await cli("eval", "--code", "1+1"))["result"]["value"] == 2
                assert (await cli("eval", "--file", str(source_file)))["result"]["value"] == {"label": "中文"}
                assert len(connections) == 1
                assert evaluations == ["1+1", "1+1", "({label:'中文'})"]
                assert (await cli("stop"))["ok"]
                await asyncio.wait_for(process.wait(), 15)
                assert process.returncode == 0
                assert not session_file.exists()
            finally:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()

    asyncio.run(scenario())


def test_disconnect_does_not_repeat_expression():
    async def scenario():
        module = bridge_module()
        evaluations = []

        async def cdp_peer(ws):
            async for raw in ws:
                message = json.loads(raw)
                expression = message.get("params", {}).get("expression")
                if expression:
                    evaluations.append(expression)
                if expression == "operation()":
                    await ws.close()
                    return
                result = {"result": {"type": "number", "value": 2}} if expression else {}
                await ws.send(json.dumps({"id": message["id"], "result": result}))

        async with websockets.serve(cdp_peer, "127.0.0.1", 0) as server:
            bridge = module.DebugBridge(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
            await bridge.connect()
            try:
                result = await bridge.evaluate("operation()", timeout_ms=100)
                assert not result["ok"]
                assert result["execution_may_have_run"]
                assert evaluations.count("operation()") == 1
            finally:
                await bridge.close()
            assert bridge.cdp.receive_task is None
            assert bridge.cdp.reconnect_task is None or bridge.cdp.reconnect_task.done()

    asyncio.run(scenario())
