"""GUI运行控制器：把会话、调度和两个功能插件接到窗口上；只持久化配置。

这里只做编排：具体连接归 session.py，任务调度归 automation.py，摸金／伤害归 features/。
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer

from package.daily_tasks.scheduler import BEIJING
from . import server_client, updater
from .automation import AutomationScheduler
from .build_info import current as build_info
from .features import DamageFeature, DesireFeature, SeasonFeature, TreasureFeature
from .session import GameSession, wechat_ready
from .state import RuntimeState
from .transport import PluginTransport, TARGET_APPID

LOG = logging.getLogger('plugin_manager')


class PluginRuntime(QObject):
    def __init__(self, window, *, service=None, transport=None, process_ready=wechat_ready):
        super().__init__(window)
        if service is None:
            from package.devtools.service import DevtoolsService
            service = DevtoolsService(self)
        self.window, self.service = window, service
        self.transport = transport or PluginTransport()
        self.record = {'id': 1, 'name': '遗弃之地插件管理器'}
        self.state = RuntimeState()
        self.session = GameSession(service, self.transport, self.state, record=self.record, process_ready=process_ready)
        self.automation = AutomationScheduler(self.transport, self.state, window)
        self.treasure = TreasureFeature(self.transport, self.state, window.pages['treasure'])
        self.damage = DamageFeature(self.transport, self.state, window.pages['damage'], window.store)
        self.desire = DesireFeature(self.transport, self.state, window.pages['desire'], window.store)
        self.season = SeasonFeature(self.transport, self.state, window.pages['bloodmoon'], window.store)
        self._closed = asyncio.Event()
        self._poll_lock = asyncio.Lock()
        self._poll_job = None
        self._shutdown_job = None
        self._next_energy = 0.0
        self._next_summary = time.monotonic() + 3600
        self._player_snapshot = None
        self._auth = None            # 握手结果；调试版直接放行
        self._bound_id = None        # 游戏里读到的主角ID，也就是绑定ID
        self._identity_misses = 0
        self._legion_name = ''
        self._update_checked = False # 每次启动只检查一次更新
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._schedule_poll)
        service.state_changed.connect(self._on_state)
        # 自动检测偏移时弹独占窗口（FakeService 等没有该信号时跳过）。
        offset_signal = getattr(service, 'offset_detecting_changed', None)
        if offset_signal is not None:
            offset_signal.connect(self.window.set_offset_detecting)
        window.configuration_changed.connect(self._on_config)
        window.test_requested.connect(self._on_test)
        window.automation_requested.connect(self.automation.set_automation)
        window.treasure_requested.connect(self.treasure.request)
        window.damage_requested.connect(self.damage.request)
        window.desire_requested.connect(self.desire.request)
        window.bloodmoon_requested.connect(self.season.request)
        window.shutdown_requested.connect(self.request_shutdown)
        window.attach_runtime(self.automation.capabilities)
        window.action_label.setText('内部运行服务已接入，等待微信／游戏就绪')
        window.set_connection(connected=False, message='等待微信／游戏')
        for task_id, panel in window.task_panels.items():
            panel.runtime_message.setText('等待游戏连接，已接入UI操作')

    def start(self):
        self.timer.start()
        self._schedule_poll()

    def _schedule_poll(self):
        if self.state.closing or (self._poll_job and not self._poll_job.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._poll_job = loop.create_task(self.poll())

    def _on_state(self, state):
        if self.session.note_engine_state(state):
            self._player_snapshot = None
            self.window.reset_session()

    def _on_config(self, state):
        LOG.info('插件配置更新：总开关=%s，启用任务=%s，玩家信息=%s',state['daily']['enabled'],[k for k,v in state['daily']['tasks'].items() if v['enabled']],state['player']['enabled'])
        self.state.configured = None
        if not state['daily']['enabled']:
            # 全部任务被反选时自动化没有意义，按钮同步回到“开始”。
            self.state.stop_operation = True
            self.automation.running = False
            self.window.set_automation_running(False)
        elif self.automation.active and not state['daily']['tasks'][self.automation.active]['enabled']:
            self.state.stop_operation = True

    def _on_test(self, task_id, options):
        if self.state.closing or self.automation.handle(task_id) is None or not self.state.installed or self.state.blocked or self.automation.busy:
            self.window.finish_test(task_id, '无法执行：任务尚未接入或当前会话不允许操作')
            return
        self.automation.begin(task_id, manual=True)

    async def poll(self):
        if self.state.closing or self._poll_lock.locked():
            return
        async with self._poll_lock:
            try:
                if not await self.session.process_available():
                    self.window.set_connection(connected=False, message='等待微信小游戏运行（不会主动打开）')
                    return
                if self.state.closing:
                    return
                self.session.request_debug()
                state = self.session.engine_state
                if state.get('owner_key') not in ('1', '', None) or not state.get('miniapp') or not state.get('cdp_port'):
                    # 没拿到 CDP 时优先展示引擎的进度提示（自动检测偏移等），再是错误，最后才是默认等待文案。
                    self.window.set_connection(
                        connected=False,
                        message=state.get('error') or state.get('message') or '等待游戏连接内部CDP服务',
                    )
                    return
                if self.automation.busy:
                    return
                epoch = (state.get('cdp_port'), state.get('miniapp_epoch'))
                await self.session.connect(state['cdp_port'], epoch)
                # 先只读确认上一命令终态；不把超时当取消，不重放游戏动作。
                await self.transport.wait_idle()
                probe = await self.session.probe()
                if self.state.closing or self.automation.busy:
                    return
                if probe.get('appid') != TARGET_APPID:
                    self.state.installed = None
                    self.window.reset_session()
                    self.window.set_connection(connected=False, message='等待遗弃之地，当前不是目标游戏')
                    return
                # 已注入后不要求每个时刻在大厅；首次/新会话必须从大厅初始化。
                if self.state.installed and (epoch != self.state.epoch or probe.get('resident_id') != self.state.installed):
                    self.state.installed = self.state.configured = None
                    self.automation.reset_handlers()
                    self.season.reset()
                    self.window.reset_session()
                if not self.state.installed:
                    if not probe.get('ready'):
                        self.window.set_connection(connected=True, target_appid=TARGET_APPID, runtime_ready=False)
                        self.window.action_label.setText('等待游戏加载至大厅后自动注入')
                        return
                    installed = await self.session.install()
                    if self.state.closing or self.session.stale(epoch):
                        return
                    self.state.installed = installed
                    self._player_snapshot = None
                    LOG.info('目标游戏大厅已确认，脚本注入成功：%s', installed)
                    self.state.epoch = epoch
                    self.automation.reset_handlers()
                    if installed != self.state.blocked_session:
                        self.state.blocked = ''
                        self.state.blocked_session = None
                    self.state.configured = None
                    self._next_energy = 0.0
                if not await self._ensure_authorized():
                    return
                await self._check_update_once()
                config = self.window.store.snapshot()
                if config != self.state.configured and not self.state.blocked:
                    await self.transport.call('configure', config)
                    self.state.configured = config
                if self.state.closing or self.automation.busy or self.session.stale(epoch):
                    return
                config = self.window.store.snapshot()
                self.window.set_debug_link(f'devtools://devtools/bundled/inspector.html?ws=127.0.0.1:{state["cdp_port"]}')
                self.window.set_connection(connected=True, target_appid=TARGET_APPID, runtime_ready=not bool(self.state.blocked))
                self.window.task_panels['energy'].runtime_message.setText(self.state.blocked or self.window.task_panels['energy'].runtime_message.text().replace('等待游戏连接', '已接入，等待任务开启'))
                if config['player']['enabled']:
                    snapshot = await self.transport.call('player_information')
                    if self.state.closing or self.session.stale(epoch):
                        return
                    if isinstance(snapshot, dict) and snapshot != self._player_snapshot:
                        self._player_snapshot = snapshot
                        self.window.set_player_information(snapshot.get('text', ''), snapshot.get('subject', '玩家信息'))
                        LOG.info('玩家信息页面更新：%s', snapshot.get('subject', '玩家信息'))
                await self.treasure.poll(config)
                await self.damage.poll(config)
                await self.desire.poll(config)
                await self.season.poll(config)
                if self.state.closing or self.session.stale(epoch):
                    return
                if time.monotonic() >= self._next_summary:
                    LOG.info('插件日常摘要：%s', self.window.task_panels['energy'].runtime_message.text())
                    self._next_summary = time.monotonic() + config['daily']['summary_interval_seconds']
                if self.automation.running and not self.state.blocked:
                    selected = self.automation.pick(datetime.now(BEIJING))
                    if selected:
                        self.automation.begin(selected)
            except Exception as exc:
                LOG.error('CDP/插件检查错误：%s',exc)
                self.window.set_connection(connected=False, message='CDP检查失败：' + str(exc))
                self.window.action_label.setText('等待目标游戏就绪；不会重复未确认的任务')

    async def _ensure_authorized(self) -> bool:
        """启动后的一次性鉴权；调试版直接放行，release 必须后台同意。

        返回 False 表示本轮到此为止（未读到身份、被拒绝、或强制更新未完成）。
        """
        if self._auth is not None:
            return self._auth.allowed
        # 只有 release 构建才读主角ID：调试版不做任何鉴权相关的事
        if not build_info().is_release:
            self._auth = server_client.HandshakeResult.debug_skip()
            LOG.info('调试版：跳过后台鉴权')
            return True

        if self._bound_id is None:
            identity = await self.transport.call('identity') or {}
            # player_id 由脚本按 role_id 优先给出，这里再兜一层旧的字段名
            player_id = str(
                identity.get('player_id') or identity.get('role_id') or identity.get('hero_id') or ''
            )
            if not player_id:
                self._identity_misses += 1
                # 每秒一次，只在前几次和之后每 20 次记一条，避免刷屏
                if self._identity_misses <= 3 or self._identity_misses % 20 == 0:
                    LOG.warning('未读到绑定ID（第%d次），identity 返回：%s', self._identity_misses, identity)
                self.window.set_connection(connected=True, target_appid=TARGET_APPID, runtime_ready=False)
                self.window.action_label.setText('正在读取账号ID，用于登录鉴权')
                return False
            self._bound_id = player_id
            self._legion_name = str(identity.get('legion_name') or '')
            self.window.set_bound_player_id(player_id)
            LOG.info('读取到绑定ID：%s（阴司：%s）', player_id, self._legion_name or '无')

        result = await asyncio.to_thread(
            server_client.handshake,
            player_id=self._bound_id,
            legion_name=self._legion_name,
        )
        self._auth = result
        LOG.info('登录鉴权：allowed=%s reason=%s offline=%s', result.allowed, result.reason, result.offline)

        if not self._auth.allowed:
            self._reject_and_exit(f'登录鉴权未通过：{self._auth.message}')
            return False
        if self._auth.update_required:
            self.state.blocked = '需要先完成强制更新才能继续使用'
            self.window.action_label.setText(self.state.blocked)
        return self._auth.allowed

    def _reject_and_exit(self, message: str) -> None:
        """鉴权不过就直接退出，不留半可用的状态。"""
        LOG.error('%s；插件退出', message)
        self.state.blocked = message
        self.window.action_label.setText(message)
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(self.window, '无法使用插件', message)
        self.window.shutdown_requested.emit()

    async def _check_update_once(self) -> None:
        """启动后检查一次更新，静默下载，就绪后提示重启。"""
        if self._update_checked:
            return
        self._update_checked = True
        if updater.pending_update() is not None:
            self.window.action_label.setText('已有下载完成的更新，重启插件后生效')
            return
        try:
            plan = await asyncio.to_thread(updater.check, player_id='')
        except server_client.ServerUnavailable as exc:
            LOG.warning('更新检查失败：%s', exc)
            return
        if not plan or not plan.get('changed'):
            return
        try:
            await asyncio.to_thread(updater.prepare, plan)
        except Exception as exc:
            LOG.error('更新下载失败：%s', exc)
            self.window.action_label.setText(f'更新下载失败：{exc}')
            return
        self.window.action_label.setText(
            f'新版本 {plan["version"]} 已就绪（{len(plan["changed"])} 个文件），重启插件后生效'
        )

    async def wait_operation(self):
        await self.automation.wait_operation()

    def request_shutdown(self):
        if self._shutdown_job is None:
            self.state.closing = True
            self.state.stop_operation = True
            self.timer.stop()
            self._shutdown_job = asyncio.create_task(self.shutdown())

    async def shutdown(self):
        if self._closed.is_set():
            return
        self.state.closing = True
        self.state.stop_operation = True
        self.timer.stop()
        try:
            await self.desire.wait_operation()
            await self.season.wait_operation()
            await self.wait_operation()
            if self._poll_job and self._poll_job is not asyncio.current_task():
                await asyncio.shield(self._poll_job)
            await self.transport.wait_idle()
            if self.state.installed and self.transport.connected:
                try:
                    await self.transport.call('stop')
                except Exception:
                    pass
            await self.transport.close()
            # 插件操作全部收尾后才停止内部调试worker；不停止微信进程。
            self.service.shutdown(wait=True)
        finally:
            self.state.installed = self.state.configured = None
            self.window.reset_session()
            self._closed.set()
            self.window.complete_shutdown()

    async def wait_closed(self):
        await self._closed.wait()
