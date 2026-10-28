"""Package-local devtools runtime engine."""

from __future__ import annotations

import asyncio
import json
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from package.devtools import offset_autodetect
from package.devtools.connection_stability import MiniappConnectionStabilizer
from package.devtools.protocol_codec import wrap_debug_message_data, unwrap_debug_message_data
from package.devtools.protocol_userscript import (
    build_cdp_add_script_command,
    build_cdp_enable_page_command,
    build_injection_wrapper,
)
from package.devtools.third_party import wmpf_debug_pb2 as proto


def render_hook_debug_port(source: str, port: int) -> str:
    """Keep the hook callback URL identical to the actual listening port."""
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError('Invalid debug port')
    rendered, count = re.subn(r'(?m)^(\s*const\s+DEBUG_PORT\s*=\s*)\d+(\s*;)',
                             lambda m: m.group(1) + str(port) + m.group(2), source)
    if count != 1 and port != 9421:
        raise RuntimeError('Hook 回连端口声明未核实，停止启动以避免端口不一致')
    return rendered


class DebugMessageBus:
    """Bridge messages between the miniapp debug server and DevTools proxy."""

    def __init__(self) -> None:
        """初始化 CDP 与代理消息回调列表。"""
        self._cdp_callbacks = []
        self._proxy_callbacks = []

    def on_cdp_message(self, callback) -> None:
        """注册小程序侧返回到 CDP 客户端的消息回调。"""
        self._cdp_callbacks.append(callback)

    def on_proxy_message(self, callback) -> None:
        """注册 CDP 客户端发往小程序侧的消息回调。"""
        self._proxy_callbacks.append(callback)

    def emit_cdp_message(self, message: str) -> None:
        """广播小程序侧返回的 CDP 消息。"""
        for callback in self._cdp_callbacks:
            callback(message)

    def emit_proxy_message(self, message: str) -> None:
        """广播代理侧发来的 CDP 命令消息。"""
        for callback in self._proxy_callbacks:
            callback(message)


def buffer_to_hex_string(data: bytes) -> str:
    """把二进制调试消息转换为十六进制字符串。"""
    return data.hex()


def workspace_root() -> Path:
    """Return the project root containing package/ and tools/."""
    return Path(__file__).resolve().parents[2]


def tools_root() -> Path:
    """Return the runtime tools directory containing hook/config assets."""
    return workspace_root() / "tools"


def normalize_proxy_message(message: str) -> str:
    """Force pause-on-exception requests into the safe default used by the UI."""
    try:
        payload = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return message
    if not isinstance(payload, dict):
        return message
    if str(payload.get("method") or "") != "Debugger.setPauseOnExceptions":
        return message
    normalized = dict(payload)
    normalized["params"] = {"state": "none"}
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def _build_protobuf_cdp_message(cdp_json: str, seq: int) -> bytes:
    """Wrap a CDP JSON command into protobuf binary for the miniapp runtime."""
    raw_payload = {
        "jscontext_id": "",
        "op_id": round(100 * random.random()),
        "payload": cdp_json,
    }
    wrapped = wrap_debug_message_data(raw_payload, "chromeDevtools", 0)
    out_msg = proto.WARemoteDebug_DebugMessage()
    out_msg.seq = seq
    out_msg.category = "chromeDevtools"
    out_msg.data = wrapped["buffer"]
    out_msg.compressAlgo = 0
    out_msg.originalSize = wrapped["originalSize"]
    return out_msg.SerializeToString()


class DebugEngine:
    """Run the websocket servers and Frida injection required for devtools."""

    def __init__(self, options, logger, userscripts=None):
        """初始化调试引擎状态、连接集合和小程序连接稳定器。"""
        self.options = options
        self.logger = logger
        self.bus = DebugMessageBus()
        self.userscripts = userscripts or []
        self.debug_srv = None
        self.proxy_srv = None
        self.frida_session = None
        self.frida_script = None
        self.miniapp_clients = set()
        self.devtools_clients = set()
        self.message_counter = 0
        self._pending_responses = {}
        self._cmd_counter = 80000
        self._status_callbacks = []
        self._event_listeners = {}
        self.status = {"frida": False, "miniapp": False, "miniapp_epoch": 0, "devtools": False}
        self.miniapp_connection = MiniappConnectionStabilizer(
            notify=self._notify_miniapp_status,
            on_stable_disconnect=self._fail_pending_miniapp_responses,
            grace_seconds=float(getattr(options, "miniapp_disconnect_grace_seconds", 1.2)),
        )

    def on_status_change(self, callback) -> None:
        """注册调试引擎状态变化回调。"""
        self._status_callbacks.append(callback)

    def _notify_status(self, key, value) -> None:
        """更新单个状态字段并通知所有监听者。"""
        self.status[key] = value
        for callback in self._status_callbacks:
            try:
                callback(dict(self.status))
            except Exception:
                pass

    def _notify_miniapp_status(self, value: bool) -> None:
        """发布小程序连接状态；每次连接递增 epoch 以识别新 runtime。"""
        if value:
            self.status["miniapp_epoch"] = int(self.status.get("miniapp_epoch") or 0) + 1
        self._notify_status("miniapp", bool(value))

    def _fail_pending_miniapp_responses(self) -> None:
        """稳定断连后统一失败所有等待中的 CDP 请求。"""
        for future in list(self._pending_responses.values()):
            if not future.done():
                future.set_exception(RuntimeError("miniapp disconnected"))
        self._pending_responses.clear()

    def handle_last_miniapp_socket_closed(self) -> None:
        """最后一个小程序连接关闭时立刻释放 CDP 等待，但 UI 离线状态继续防抖。"""
        self._fail_pending_miniapp_responses()
        self.miniapp_connection.mark_disconnected_if_idle(lambda: bool(self.miniapp_clients))

    def _next_cmd_id(self) -> int:
        """生成递增的 CDP 命令编号。"""
        self._cmd_counter += 1
        return self._cmd_counter

    async def start(self) -> None:
        """Start the debug server, proxy server, and Frida hook."""
        self.debug_srv = await self._start_debug_server()
        self.proxy_srv = await self._start_proxy_server()
        try:
            self.frida_session, self.frida_script = await self._start_frida()
            self._notify_status("frida", True)
        except Exception as exc:
            self.logger.error(str(exc))
            raise

    async def stop(self) -> None:
        """Gracefully stop all runtime components and clear connection state."""
        if self.debug_srv:
            self.debug_srv.close()
            await self.debug_srv.wait_closed()
            self.debug_srv = None
        if self.proxy_srv:
            self.proxy_srv.close()
            await self.proxy_srv.wait_closed()
            self.proxy_srv = None
        if self.frida_script:
            try:
                self.frida_script.unload()
            except Exception:
                pass
            self.frida_script = None
        if self.frida_session:
            try:
                self.frida_session.detach()
            except Exception:
                pass
            self.frida_session = None
        await self.miniapp_connection.shutdown()
        self._notify_status("frida", False)
        self._notify_status("miniapp", False)
        self._notify_status("devtools", False)
        self.miniapp_clients.clear()
        self.devtools_clients.clear()
        self.message_counter = 0
        self._pending_responses.clear()
        self.logger.info("[server] engine stopped")

    async def evaluate_js(self, expression, timeout=5.0):
        """Send Runtime.evaluate via CDP and return the response dict."""
        if not self.miniapp_clients:
            raise RuntimeError("No miniapp client connected")
        cmd_id = self._next_cmd_id()
        cdp_cmd = json.dumps(
            {
                "id": cmd_id,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True},
            }
        )
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_responses[cmd_id] = future
        self.bus.emit_proxy_message(cdp_cmd)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_responses.pop(cmd_id, None)
            raise

    async def send_cdp_command(self, method, params=None, timeout=5.0):
        """Send an arbitrary CDP command and return the response."""
        if not self.miniapp_clients:
            raise RuntimeError("No miniapp client connected")
        cmd_id = self._next_cmd_id()
        cdp_cmd = json.dumps({"id": cmd_id, "method": method, "params": params or {}})
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_responses[cmd_id] = future
        self.bus.emit_proxy_message(cdp_cmd)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_responses.pop(cmd_id, None)
            raise

    async def set_extra_headers(self, headers: dict) -> None:
        """Enable the Network domain and attach extra request headers."""
        await self.send_cdp_command("Network.enable")
        await self.send_cdp_command("Network.setExtraHTTPHeaders", {"headers": headers})

    def on_cdp_event(self, method, callback) -> None:
        """Subscribe to a CDP event by method name."""
        self._event_listeners.setdefault(method, []).append(callback)

    def off_cdp_event(self, method, callback) -> None:
        """Unsubscribe from a CDP event."""
        callbacks = self._event_listeners.get(method, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def _handle_cdp_response(self, message_str) -> None:
        """Dispatch CDP responses to pending callers or event listeners."""
        try:
            data = json.loads(message_str)
        except (json.JSONDecodeError, TypeError):
            return
        msg_id = data.get("id")
        if msg_id is not None and msg_id in self._pending_responses:
            future = self._pending_responses.pop(msg_id)
            if not future.done():
                future.set_result(data)
        method = data.get("method")
        if method and method in self._event_listeners:
            for callback in self._event_listeners[method]:
                try:
                    callback(data)
                except Exception:
                    pass

    async def _start_debug_server(self):
        """启动小程序远程调试 websocket 服务。"""
        import websockets.exceptions
        import websockets.server

        engine = self
        logger = self.logger
        bus = self.bus
        userscripts = self.userscripts
        scripts_injected = False

        def on_proxy_message(message: str) -> None:
            """把外部 CDP 命令封装为微信调试协议并发给小程序。"""
            engine.message_counter += 1
            raw_payload = {
                "jscontext_id": "",
                "op_id": round(100 * random.random()),
                "payload": str(message),
            }
            logger.main_debug(raw_payload)
            wrapped = wrap_debug_message_data(raw_payload, "chromeDevtools", 0)
            out_msg = proto.WARemoteDebug_DebugMessage()
            out_msg.seq = engine.message_counter
            out_msg.category = "chromeDevtools"
            out_msg.data = wrapped["buffer"]
            out_msg.compressAlgo = 0
            out_msg.originalSize = wrapped["originalSize"]
            encoded = out_msg.SerializeToString()
            for websocket in list(engine.miniapp_clients):
                try:
                    task = asyncio.ensure_future(websocket.send(encoded))
                    task.add_done_callback(
                        lambda current_task: current_task.exception()
                        if current_task.done() and not current_task.cancelled() and current_task.exception()
                        else None
                    )
                except Exception:
                    pass

        bus.on_proxy_message(on_proxy_message)

        async def handler(websocket):
            """处理单个小程序 websocket 连接的收发和断连清理。"""
            nonlocal scripts_injected
            engine.miniapp_clients.add(websocket)
            engine.miniapp_connection.mark_connected()
            logger.info("[miniapp] miniapp client connected")

            if userscripts and not scripts_injected:
                scripts_injected = True
                logger.info("[userscript] registering scripts immediately on connection...")
                try:
                    seq = engine.message_counter
                    cmd_id = 90000
                    seq += 1
                    await websocket.send(_build_protobuf_cdp_message(build_cdp_enable_page_command(cmd_id), seq))
                    cmd_id += 1
                    seq += 1
                    await websocket.send(
                        _build_protobuf_cdp_message(
                            json.dumps({"id": cmd_id, "method": "Debugger.enable", "params": {}}),
                            seq,
                        )
                    )
                    cmd_id += 1
                    logger.info("[anti-debug] Debugger.enable sent")
                    seq += 1
                    await websocket.send(
                        _build_protobuf_cdp_message(
                            json.dumps({"id": cmd_id, "method": "Debugger.setSkipAllPauses", "params": {"skip": True}}),
                            seq,
                        )
                    )
                    cmd_id += 1
                    logger.info("[anti-debug] Debugger.setSkipAllPauses(true) sent")
                    for script in userscripts:
                        seq += 1
                        await websocket.send(_build_protobuf_cdp_message(build_cdp_add_script_command(script, cmd_id), seq))
                        cmd_id += 1
                        logger.info(f"[userscript] registered (persistent): {script.name}")
                    engine.message_counter = seq
                    logger.info("[userscript] registration done, scripts will run on page load")
                except Exception as exc:
                    logger.error(f"[userscript] registration error: {exc}")

            immediate_done = False
            try:
                async for message in websocket:
                    if isinstance(message, str):
                        message = message.encode("utf-8")
                    msg_category = ""
                    try:
                        decoded_msg = proto.WARemoteDebug_DebugMessage()
                        decoded_msg.ParseFromString(message)
                        msg_category = decoded_msg.category
                    except Exception:
                        pass
                    self._process_miniapp_message(message)
                    if msg_category == "setupContext" and userscripts and not immediate_done:
                        immediate_done = True
                        await asyncio.sleep(0.5)
                        try:
                            seq = engine.message_counter
                            cmd_id = 91000
                            seq += 1
                            await websocket.send(
                                _build_protobuf_cdp_message(
                                    json.dumps({"id": cmd_id, "method": "Debugger.enable", "params": {}}),
                                    seq,
                                )
                            )
                            cmd_id += 1
                            seq += 1
                            await websocket.send(
                                _build_protobuf_cdp_message(
                                    json.dumps({"id": cmd_id, "method": "Debugger.setSkipAllPauses", "params": {"skip": True}}),
                                    seq,
                                )
                            )
                            cmd_id += 1
                            logger.info("[anti-debug] Debugger.setSkipAllPauses re-sent after setupContext")
                            for script in userscripts:
                                wrapped = build_injection_wrapper(script)
                                seq += 1
                                cdp_cmd = json.dumps(
                                    {
                                        "id": cmd_id,
                                        "method": "Runtime.evaluate",
                                        "params": {
                                            "expression": wrapped,
                                            "includeCommandLineAPI": True,
                                            "silent": False,
                                        },
                                    }
                                )
                                await websocket.send(_build_protobuf_cdp_message(cdp_cmd, seq))
                                cmd_id += 1
                                logger.info(f"[userscript] immediate inject (Runtime.evaluate): {script.name}")
                            engine.message_counter = seq
                        except Exception as exc:
                            logger.error(f"[userscript] immediate inject warning: {exc}")
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as exc:
                logger.error(f"[miniapp] miniapp client err: {exc}")
            finally:
                engine.miniapp_clients.discard(websocket)
                if not engine.miniapp_clients:
                    engine.handle_last_miniapp_socket_closed()
                logger.info("[miniapp] miniapp client disconnected")

        server = await websockets.server.serve(handler, "0.0.0.0", self.options.debug_port, max_size=None)
        logger.info(f"[server] debug server running on ws://localhost:{self.options.debug_port}")
        logger.info("[server] debug server waiting for miniapp to connect...")
        return server

    def _process_miniapp_message(self, message: bytes) -> None:
        """解析小程序发来的 protobuf 消息并分发 CDP 响应。"""
        self.logger.main_debug(f"[miniapp] client received raw message (hex): {buffer_to_hex_string(message)}")
        unwrapped_data = None
        try:
            decoded = proto.WARemoteDebug_DebugMessage()
            decoded.ParseFromString(message)
            unwrapped_data = unwrap_debug_message_data(decoded)
            self.logger.main_debug("[miniapp] [DEBUG] decoded data:")
            self.logger.main_debug(unwrapped_data)
        except Exception as exc:
            self.logger.error(f"[miniapp] miniapp client err: {exc}")

        if unwrapped_data is None:
            return

        if unwrapped_data.get("category") == "chromeDevtoolsResult":
            payload = unwrapped_data["data"].get("payload", "")
            self.bus.emit_cdp_message(payload)
            self._handle_cdp_response(payload)

    async def _start_proxy_server(self):
        """启动给外部 DevTools 前端连接的 CDP 代理服务。"""
        import websockets.exceptions
        import websockets.server

        engine = self
        logger = self.logger
        bus = self.bus

        def on_cdp_message(message: str) -> None:
            """把小程序侧 CDP 响应广播给所有 DevTools 客户端。"""
            for websocket in list(engine.devtools_clients):
                try:
                    task = asyncio.ensure_future(websocket.send(message))
                    task.add_done_callback(
                        lambda current_task: current_task.exception()
                        if current_task.done() and not current_task.cancelled() and current_task.exception()
                        else None
                    )
                except Exception:
                    pass

        bus.on_cdp_message(on_cdp_message)

        async def handler(websocket):
            """处理单个 DevTools websocket 客户端连接。"""
            engine.devtools_clients.add(websocket)
            engine._notify_status("devtools", True)
            logger.info("[cdp] CDP client connected")
            try:
                async for message in websocket:
                    if isinstance(message, bytes):
                        message = message.decode("utf-8")
                    bus.emit_proxy_message(normalize_proxy_message(message))
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as exc:
                logger.error(f"[cdp] CDP client err: {exc}")
            finally:
                engine.devtools_clients.discard(websocket)
                if not engine.devtools_clients:
                    engine._notify_status("devtools", False)
                logger.info("[cdp] CDP client disconnected")

        server = await websockets.server.serve(handler, "0.0.0.0", self.options.cdp_port, max_size=None)
        logger.info(f"[server] proxy server running on ws://localhost:{self.options.cdp_port}")
        logger.info(f"[server] link: devtools://devtools/bundled/inspector.html?ws=127.0.0.1:{self.options.cdp_port}")
        return server

    def _load_frida(self):
        """延迟导入 frida，避免模块导入阶段触发重依赖加载。"""
        import frida

        return frida

    @staticmethod
    def _is_radium_wmpf_path(proc_path: str) -> bool:
        """判断进程路径是否属于微信小程序运行环境（排除企业微信 WXWork 的同名进程）。"""
        normalized = str(proc_path or "").replace("/", "\\").lower()
        return "radiumwmpf" in normalized and "wmpf_applet" not in normalized

    def _detect_wmpf_version(self, proc_path: str) -> int:
        """从 RadiumWMPF 目录解析运行环境版本，取数字最大的版本目录。

        不能按「有没有配置文件」挑版本：那样会拿旧版本的偏移去 hook 新版本运行时
        （例如用 25715 的配置 hook 实际加载的 25799），直接把小程序搞崩。
        缺配置时由 _start_frida_sync 走自动检测兜底。
        """
        runtime_dir = Path(str(proc_path or "")).parent

        # 1) 路径里带纯数字目录段（如 ...\RadiumWMPF\25715\WeChatAppEx.exe）
        for part in reversed(runtime_dir.parts):
            if part.isdigit():
                return int(part)

        # 2) 可执行文件直接放在 RadiumWMPF 根目录时，扫它的数字子目录
        candidates = sorted(
            (int(entry.name) for entry in runtime_dir.iterdir() if entry.is_dir() and entry.name.isdigit()),
            reverse=True,
        ) if runtime_dir.is_dir() else []
        if not candidates:
            raise RuntimeError("[frida] cannot detect WMPF version from path")
        return candidates[0]

    def _find_wmpf_pids_win(self):
        """Windows: find the main WeChatAppEx.exe PID via PPID frequency."""
        frida = self._load_frida()
        device = frida.get_local_device()
        processes = device.enumerate_processes(scope="metadata")
        wmpf_procs = [
            process
            for process in processes
            if process.name == "WeChatAppEx.exe" and self._is_radium_wmpf_path(process.parameters.get("path", ""))
        ]
        if not wmpf_procs:
            raise RuntimeError("[frida] WeChatAppEx.exe process not found")

        ppids = [process.parameters.get("ppid", 0) or 0 for process in wmpf_procs]
        main_pid = Counter(ppids).most_common(1)[0][0]
        if main_pid == 0:
            raise RuntimeError("[frida] WeChatAppEx.exe main process not found")

        main_proc = next((process for process in processes if process.pid == main_pid), None)
        if main_proc is None:
            raise RuntimeError("[frida] could not locate main WMPF process")

        proc_path = main_proc.parameters.get("path", "")
        version = self._detect_wmpf_version(proc_path)
        if version == 0:
            raise RuntimeError("[frida] invalid WMPF version")

        return [main_pid], version

    def _find_wmpf_pids_darwin(self):
        """macOS: find WeChatAppEx PIDs and the bundled version number."""
        try:
            output = subprocess.check_output(
                ["pgrep", "-f", "/MacOS/WeChatAppEx.app/Contents/MacOS/WeChatAppEx"],
                text=True,
            ).strip()
            pids = [int(pid) for pid in output.splitlines() if pid.strip()]
        except (subprocess.CalledProcessError, ValueError):
            pids = []
        if not pids:
            raise RuntimeError("[frida] WeChatAppEx process not found on macOS")

        try:
            version_output = subprocess.check_output(
                [
                    "defaults",
                    "read",
                    "/Applications/WeChat.app/Contents/MacOS/WeChatAppEx.app/Contents/Info.plist",
                    "CFBundleVersion",
                ],
                text=True,
            ).strip()
            version = int(version_output.split(".")[1])
        except Exception:
            raise RuntimeError("[frida] cannot detect WeChatAppEx version from Info.plist")

        return pids, version

    async def _start_frida(self):
        """在线程中启动 Frida 链路，避免阻塞 DevTools worker 的事件循环。"""
        self._frida_loop=asyncio.get_running_loop()
        return await asyncio.to_thread(self._start_frida_sync)

    def _start_frida_sync(self):
        """同步执行 Frida 查找、脚本读取和注入，供线程池调用。"""
        logger = self.logger
        frida = self._load_frida()
        is_mac = sys.platform == "darwin"
        platform_dir = "mac" if is_mac else "win"

        androws_config = None
        channel = getattr(self.options, 'channel', 'wechat')
        if channel == 'androws':
            if is_mac:
                raise RuntimeError('应用宝渠道仅支持 Windows')
            from package.devtools.androws import find_runtime, load_profile
            pid, dll = find_runtime(frida.get_local_device().enumerate_processes(scope='metadata'))
            androws_config = load_profile(dll, tools_root() / 'config')
            pids, wmpf_version = [pid], int(androws_config['Version'])
        elif channel != 'wechat':
            raise RuntimeError('未知 WMPF 渠道')
        elif is_mac:
            pids, wmpf_version = self._find_wmpf_pids_darwin()
        else:
            pids, wmpf_version = self._find_wmpf_pids_win()

        hook_path = tools_root() / ('hook_androws.js' if androws_config is not None else 'hook.js')
        if not hook_path.exists():
            raise RuntimeError("[frida] hook script not found")

        prepared_session=None
        config_path = tools_root() / "config" / platform_dir / f"addresses.{wmpf_version}.json"
        if androws_config is None and not config_path.exists():
            # 兜底：本机出现新版本运行时时，现算偏移并落盘，之后照常从磁盘读。
            if is_mac:
                raise RuntimeError(
                    f"[frida] macOS 不支持自动检测，请手动补充 tools/config/mac/addresses.{wmpf_version}.json"
                )
            self._notify_status("message", f"正在自动检测 {wmpf_version} 偏移…")
            self._notify_status("offset_detect", True)
            try:
                prepared_session=frida.get_local_device().attach(pids[0])
                detected = offset_autodetect.detect_offsets_sync(pids[0], frida=frida,session=prepared_session)
                normalized = offset_autodetect.normalize_detected_config(wmpf_version, detected)
                saved_path = offset_autodetect.persist_addresses_config(
                    wmpf_version, normalized, platform_dir
                )
                logger.info(f"[frida] 自动检测完成，偏移已写入 {saved_path}")
            except Exception as exc:
                if prepared_session is not None:
                    try:prepared_session.detach()
                    except Exception:pass
                    prepared_session=None
                raise RuntimeError(f"[frida] 版本 {wmpf_version} 偏移自动检测失败：{exc}") from None
            finally:
                # 不清空的话 bridge 结束时还会再推一次状态，界面会一直挂着检测提示。
                self._notify_status("offset_detect", False)
                self._notify_status("message", "")

        try:
            script_content = hook_path.read_text(encoding="utf-8")
            config_content = json.dumps(androws_config if androws_config is not None
                                        else json.loads(config_path.read_text(encoding="utf-8")))
            final_script = script_content.replace("@@CONFIG@@", config_content)
            debug_port = getattr(getattr(self, 'options', None), 'debug_port', 9421)
            final_script = render_hook_debug_port(final_script, debug_port)
        except Exception:
            if prepared_session is not None:
                try:prepared_session.detach()
                except Exception:pass
            raise

        device = frida.get_local_device()
        session = None
        script = None

        def on_message(message, data) -> None:
            """接收 Frida 脚本消息并转发到 worker 日志。"""
            if message.get("type") == "error":
                logger.error("[frida client]", message)
                return
            logger.frida_debug("[frida client]", message.get("payload", ""))

        for pid in pids:
            current_session = None
            current_script = None
            try:
                current_session = prepared_session if prepared_session is not None and pid==pids[0] else device.attach(pid)
                if current_session is prepared_session:prepared_session=None
                current_script = current_session.create_script(final_script)
                current_script.on("message", on_message)
                current_script.load()
                def invalidated(*args,attached=current_session,loaded=current_script):
                    def publish():
                        if getattr(self,'frida_session',None) is attached and getattr(self,'frida_script',None) is loaded:
                            self._notify_status('frida',False)
                    loop=getattr(self,'_frida_loop',None)
                    if loop is not None and not loop.is_closed():loop.call_soon_threadsafe(publish)
                    else:publish()
                if hasattr(current_session,'on'):current_session.on('detached',invalidated)
                current_script.on('destroyed',invalidated)
                if androws_config is not None:
                    current_script.exports_sync.install()
                logger.info(f"[frida] injected pid={pid}, version={wmpf_version}")
                if session is None:
                    session, script = current_session, current_script
            except Exception as exc:
                logger.error(f"[frida] failed to inject pid={pid}: {exc}")
                if current_script is not None:
                    try:current_script.unload()
                    except Exception:pass
                if current_session is not None:
                    try:current_session.detach()
                    except Exception:pass
                if androws_config is not None:
                    raise RuntimeError(f'应用宝调试挂载失败：{exc}') from exc

        if session is None:
            raise RuntimeError("[frida] failed to inject any WeChatAppEx process")

        logger.info(f"[frida] ready ({platform_dir}), version={wmpf_version}, {len(pids)} process(es)")
        logger.info("[frida] you can now open any miniapps")
        return session, script
