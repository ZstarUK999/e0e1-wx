"""游戏会话：调试引擎状态、微信进程探测、CDP 连接与脚本注入。

只回答"现在能不能操作游戏"，不负责具体业务。
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time

import psutil

LOG = logging.getLogger('plugin_manager')

# 调试会话一直连不上时的重发间隔与次数。
DEBUG_RETRY_SECONDS = 20.0
DEBUG_MAX_RETRIES = 10

# 微信进程探测的缓存间隔。
PROCESS_CHECK_SECONDS = 5.0


def wechat_ready() -> bool:
    for process in psutil.process_iter(['name']):
        try:
            if str(process.info['name']).casefold() == 'wechatappex.exe' and 'radiumwmpf' in process.exe().casefold() and 'wxwork' not in process.exe().casefold():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def _is_routine_status(message: str) -> bool:
    """不该记进插件日志的状态：每次回调都会重算，或重试期间会刷屏的那些。"""
    if message.startswith('Frida ') and ' | ' in message:
        return True
    # 端口重试每换一个端口就是一条新文案，界面上看得到，日志里不必逐条记。
    return message.startswith('CDP 端口')


class GameSession:
    def __init__(self, service, transport, state, *, record, process_ready=wechat_ready):
        self.service = service
        self.transport = transport
        self.state = state
        self.record = record
        self.process_ready = process_ready
        self.engine_state = service.snapshot()
        self._last_state_message = ''
        self._started = False
        self._debug_retries = 0
        self._next_debug_retry = 0.0
        self._process_available = False
        self._next_process_check = 0.0

    # ── 微信进程 ──

    async def process_available(self) -> bool:
        """带 5 秒缓存的进程探测，避免每秒遍历进程列表。"""
        if time.monotonic() >= self._next_process_check:
            self._process_available = await asyncio.to_thread(self.process_ready)
            self._next_process_check = time.monotonic() + PROCESS_CHECK_SECONDS
        return self._process_available

    # ── 调试引擎状态 ──

    def note_engine_state(self, state: dict) -> bool:
        """记录引擎状态；会话发生变更（小程序退出或 epoch 变了）时返回 True。"""
        self.engine_state = copy.deepcopy(state)
        # 调试引擎的一次性提示（如「正在自动检测 25799 偏移…」）也要进插件日志，
        # 否则 worker 进程的 print 日志在插件这边看不到。
        # 但常规三连状态（Frida/小程序/DevTools）每次状态回调都会重算，刷屏，不记。
        message = str(state.get('message') or '')
        if message and message != self._last_state_message and not _is_routine_status(message):
            self._last_state_message = message
            LOG.info('调试状态：%s', message)
        epoch = (state.get('cdp_port') or state.get('transport_key'), state.get('miniapp_epoch'))
        if self.state.installed is not None and (not state.get('miniapp') or epoch != self.state.epoch):
            self.state.stop_operation = True
            self.transport.invalidate()
            self.state.installed = self.state.configured = None
            LOG.info('游戏会话变更，清空当前状态并等待重新注入')
            return True
        return False

    def request_debug(self) -> None:
        """一检测到微信就挂调试（hook 先装好，之后打开的小程序会自动回连）。

        别等小程序起来再挂：那时 9421 的握手已经错过，frida 补不上。
        只有一直拿不到 CDP 时才重发一次会话请求。
        """
        state = self.engine_state
        if (state.get('cdp_port') or state.get('transport_ready')) and state.get('miniapp'):
            self._debug_retries = 0
            return
        if not self._started:
            self.service.start_debug(self.record)
            self._started = True
            self._next_debug_retry = time.monotonic() + DEBUG_RETRY_SECONDS
            LOG.info('已请求启动内部调试会话（等待小程序回连）')
            return
        if self._debug_retries >= DEBUG_MAX_RETRIES or time.monotonic() < self._next_debug_retry:
            return
        self._debug_retries += 1
        self._next_debug_retry = time.monotonic() + DEBUG_RETRY_SECONDS
        LOG.info('仍未拿到CDP连接，重发调试会话请求（第%d/%d次）', self._debug_retries, DEBUG_MAX_RETRIES)
        self.service.start_debug(self.record)

    async def prepare_reopen(self, timeout=20):
        """Re-arm hooks before opening a new game, then leave them intact during startup."""
        ready=asyncio.Event()
        reset_seen=False
        failure=None
        def changed(state):
            nonlocal reset_seen, failure
            if not state.get('frida'):reset_seen=True
            if state.get('status')=='failed':
                failure=state.get('error') or state.get('message') or '调试监听启动失败'
                ready.set()
            elif reset_seen and state.get('frida'):
                ready.set()
        self.service.state_changed.connect(changed)
        try:
            self._started=True
            self._debug_retries=0
            self._next_debug_retry=time.monotonic()+60
            self.service.start_debug(self.record)
            await asyncio.wait_for(ready.wait(), timeout=timeout)
            if failure:raise RuntimeError(failure)
            if self.state.closing:raise RuntimeError('插件正在退出，已取消打开游戏')
            self._next_debug_retry=time.monotonic()+60
            LOG.info('微信重开调试监听已就绪，接下来60秒保持监听等待游戏回连')
        except TimeoutError:
            raise RuntimeError('调试监听未在20秒内就绪，已停止打开游戏') from None
        finally:
            self.service.state_changed.disconnect(changed)

    # ── CDP 连接与注入 ──

    async def connect(self, port: int, epoch=None) -> None:
        """首次连接或端口变化时重连；已连上就复用。"""
        if not self.transport.connected or (self.state.epoch is not None and epoch is not None and epoch[0] != self.state.epoch[0]):
            await self.transport.wait_idle()
            await self.transport.connect(port)

    async def probe(self) -> dict:
        return await self.transport.probe()

    async def install(self) -> str:
        return await self.transport.install()

    def stale(self, epoch) -> bool:
        """引擎状态是否已经变了：每次 await 之后都要用它复核再改界面或发命令。"""
        return epoch != (self.engine_state.get('cdp_port') or self.engine_state.get('transport_key'), self.engine_state.get('miniapp_epoch'))
