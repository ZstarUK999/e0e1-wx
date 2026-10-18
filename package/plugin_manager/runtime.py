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
from . import license as license_module
from . import server_client, updater
from .automation import AutomationScheduler
from .build_info import current as build_info
from .features import DamageFeature, DesireFeature, SeasonFeature, TreasureFeature
from .gate import PHASE_DENIED, PHASE_INIT, PHASE_MOUNTING, PHASE_WAIT_GAME
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
        self.target_appid = getattr(self.transport, 'TARGET_APPID', TARGET_APPID)
        self.platform_name = getattr(self.transport, 'platform_name', '微信')
        self.window.TARGET_APPID = self.target_appid
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
        self._handshake_job = None   # 后台登录上报；纯上报，失败不影响使用
        self._next_energy = 0.0
        self._next_summary = time.monotonic() + 3600
        self._player_snapshot = None
        self._authorized = None      # 账号门禁结论；None=还没判定
        self._auth = None            # 后台握手回执，只用于记录与提示
        self._bound_id = None        # 游戏里读到的主角ID，也就是绑定ID
        self._identity_misses = 0
        self._legion_name = ''
        self._player_name = ''
        self._update_checked = False # 每次启动只检查一次更新
        self.timer = QTimer(self)
        self.timer.setInterval(100 if window.store.snapshot().get('bloodmoon', {}).get('enabled') else 1000)
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
        window.action_label.setText(f'{self.platform_name}运行服务已接入，等待游戏就绪')
        window.set_connection(connected=False, message=f'等待{self.platform_name}／游戏')
        for task_id, panel in window.task_panels.items():
            panel.runtime_message.setText('等待游戏连接，已接入UI操作')

    def start(self):
        self.timer.start()
        self._schedule_poll()

    def _link_phase(self, state: dict) -> str:
        """拿不到 CDP 时门禁该显示哪一档。

        frida 还没装上才是"初始化中"（这时插件确实在干活，转圈有意义）；
        hook 装好之后剩下的就是等玩家开游戏，不该再转圈假装还在加载。
        """
        if state.get('transport_key'):
            return PHASE_INIT if state.get('error') else PHASE_WAIT_GAME
        if state.get('error') or not state.get('frida'):
            return PHASE_INIT
        return PHASE_WAIT_GAME

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
            # 会话变了就退回门禁：游戏关了就是等玩家重开，还在就只是要重新挂载脚本。
            if state.get('miniapp'):
                self.window.set_gate(PHASE_MOUNTING, '游戏会话已变化，正在重新挂载脚本')
            else:
                self.window.set_gate(PHASE_WAIT_GAME, '游戏会话已变化，等待重新接入')

    def _on_config(self, state):
        self.timer.setInterval(100 if state.get('bloodmoon', {}).get('enabled') else 1000)
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
                    # 微信都没起来，frida 也无从挂起，这里就是在等玩家打开游戏。
                    self.window.set_connection(connected=False, message=f'等待{self.platform_name}小游戏运行（不会主动打开）')
                    self.window.set_gate(PHASE_WAIT_GAME, f'等待{self.platform_name}运行，请打开并进入《遗弃之地》')
                    return
                if self.state.closing:
                    return
                self.session.request_debug()
                state = self.session.engine_state
                if state.get('owner_key') not in ('1', '', None) or not state.get('miniapp') or not (state.get('cdp_port') or state.get('transport_ready')):
                    # 没拿到 CDP 时优先展示引擎的进度提示（自动检测偏移等），再是错误，最后才是默认等待文案。
                    self.window.set_connection(
                        connected=False,
                        message=state.get('error') or state.get('message') or '等待游戏连接内部CDP服务',
                    )
                    self.window.set_gate(
                        self._link_phase(state),
                        state.get('error') or state.get('message') or '正在建立调试链路',
                    )
                    return
                if self.automation.busy:
                    return
                epoch = (state.get('cdp_port') or state.get('transport_key'), state.get('miniapp_epoch'))
                await self.session.connect(state.get('cdp_port') or state.get('transport_key'), epoch)
                # 先只读确认上一命令终态；不把超时当取消，不重放游戏动作。
                await self.transport.wait_idle()
                probe = await self.session.probe()
                if self.state.closing or self.automation.busy:
                    return
                if probe.get('appid') != self.target_appid:
                    self.state.installed = None
                    self.window.reset_session()
                    self.window.set_connection(connected=False, message='等待遗弃之地，当前不是目标游戏')
                    self.window.set_gate(PHASE_WAIT_GAME, '当前打开的不是《遗弃之地》')
                    return
                # 已注入后不要求每个时刻在大厅；首次/新会话必须从大厅初始化。
                if self.state.installed and (epoch != self.state.epoch or probe.get('resident_id') != self.state.installed):
                    self.state.installed = self.state.configured = None
                    self.automation.reset_handlers()
                    self.season.reset()
                    self.window.reset_session()
                if not self.state.installed:
                    if not probe.get('ready'):
                        self.window.set_connection(connected=True, target_appid=self.target_appid, runtime_ready=False)
                        self.window.action_label.setText('等待游戏加载至大厅后自动注入')
                        self.window.set_gate(PHASE_MOUNTING, '已连接《遗弃之地》，等待加载至大厅')
                        return
                    # 大厅已确认，接下来就是挂载脚本；挂之前先把门禁切到"正在挂载"。
                    self.window.set_gate(PHASE_MOUNTING, '大厅已确认，正在挂载插件脚本')
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
                self.window.set_debug_link(f'devtools://devtools/bundled/inspector.html?ws=127.0.0.1:{state["cdp_port"]}' if state.get('cdp_port') else '')
                self.window.set_connection(connected=True, target_appid=self.target_appid, runtime_ready=not bool(self.state.blocked))
                self.window.task_panels['energy'].runtime_message.setText(self.state.blocked or self.window.task_panels['energy'].runtime_message.text().replace('等待游戏连接', '已接入，等待任务开启'))
                await self.season.poll(config)
                self.timer.setInterval(self.season.scan_interval_ms if config.get('bloodmoon', {}).get('enabled') else 1000)
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
                self.window.set_gate(self._link_phase(self.session.engine_state), 'CDP检查失败：' + str(exc))

    async def _ensure_authorized(self) -> bool:
        """账号门禁：以 exe 同级 license 的绑定ID为准，比对通过就放出主 UI。

        门禁到此为止——与后台的 handshake 只是上报，结果不参与能不能用
        （见 _report_handshake）。调试版连这层都不查，直接放行。
        """
        if self._authorized is not None:
            if self._authorized:
                self.window.show_main_ui()
            return self._authorized
        # 只有 release 构建才读主角ID：调试版不做任何鉴权相关的事
        if not build_info().is_release:
            self._authorized = True
            self._auth = server_client.HandshakeResult.debug_skip()
            LOG.info('调试版：跳过账号门禁')
            self.window.show_main_ui()
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
                self.window.set_connection(connected=True, target_appid=self.target_appid, runtime_ready=False)
                self.window.action_label.setText('正在读取账号ID，用于 license 绑定校验')
                self.window.set_gate(PHASE_MOUNTING, '脚本已挂载，正在读取账号信息用于授权校验')
                return False
            self._bound_id = player_id
            self._legion_name = str(identity.get('legion_name') or '')
            self._player_name = str(identity.get('name') or '')
            self.window.set_bound_player_id(player_id)
            LOG.info('读取到绑定ID：%s（阴司：%s）', player_id, self._legion_name or '无')

        # 本地先过一遍：公钥验签 + 绑定ID比对。验签不能省——省了别人把 license.bin
        # 里的 player_id 改成自己的号就能白用。
        bound, reason = license_module.bound_player_id()
        if bound is None:
            self._reject_gate(reason)
            return False
        if bound != self._bound_id:
            self._reject_gate(f'license 绑定账号 {bound}，当前登录账号 {self._bound_id}')
            return False
        LOG.info('license 本地校验通过：%s', self._bound_id)
        self._authorized = True
        self.window.show_main_ui()
        self._start_handshake_report()
        return True

    def _start_handshake_report(self) -> None:
        """把登录信息报给后台；纯上报，丢后台跑，失败不影响已经放行的主 UI。"""
        if self._handshake_job is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._handshake_job = loop.create_task(self._report_handshake())

    async def _report_handshake(self) -> None:
        """上报结果只记日志和提示，不写 state.blocked、不拦自动化。"""
        try:
            result = await asyncio.to_thread(
                server_client.handshake,
                player_id=self._bound_id or '',
                legion_name=self._legion_name,
                player_name=self._player_name,
            )
        except Exception as exc:
            LOG.warning('后台上报失败（不影响使用）：%s', exc)
            return
        self._auth = result
        LOG.info('登录上报：allowed=%s reason=%s offline=%s', result.allowed, result.reason, result.offline)
        if not result.allowed:
            LOG.warning('后台未放行：%s', result.message)
        if result.update_required:
            self.window.action_label.setText('后台提示需要更新到新版本')

    def _reject_gate(self, reason: str) -> None:
        """账号ID与 license 对不上：门禁面板上明示原因和读到的ID，不进主 UI。

        这里刻意不做"看起来还在等连接"的处理——没授权就说没授权。
        """
        message = f'此账号未授权：{reason}'
        LOG.error('%s', message)
        self._authorized = False
        self.state.blocked = message
        self.window.set_gate(PHASE_DENIED, f'{reason}\n当前登录账号ID：{self._bound_id or "未读取"}')
        self.window.action_label.setText(message)

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
            # 登录上报只是上报，退出时直接取消，别让它拖着 15 秒超时。
            if self._handshake_job is not None and not self._handshake_job.done():
                self._handshake_job.cancel()
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
