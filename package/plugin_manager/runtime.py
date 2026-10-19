"""GUI运行控制器：把会话、调度和两个功能插件接到窗口上；只持久化配置。

这里只做编排：具体连接归 session.py，任务调度归 automation.py，摸金／伤害归 features/。
"""
from __future__ import annotations

import asyncio
import logging
import time
import threading
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
from .transport import PluginTransport, TARGET_APPID, CdpConnectionPending

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
        self._next_overlay_sync = 0.0
        self._overlay_error = False
        self._next_battle_timing = 0.0
        self._next_energy = 0.0
        self._next_summary = time.monotonic() + 3600
        self._last_check_error = None
        self._next_check_error_log = 0.0
        self._player_snapshot = None
        self._feature_ready_session = None
        self._authorized = None      # 账号门禁结论；None=还没判定
        self._auth = None            # 后台握手回执，只用于记录与提示
        self._bound_id = None        # 游戏里读到的主角ID，也就是绑定ID
        self._identity_misses = 0
        self._legion_name = ''
        self._player_name = ''
        self._update_checked = False
        self._update_job = None
        self._update_attempts = 0
        self._next_update_check = 0.0
        self._update_cancel = threading.Event()
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
            panel.runtime_message.setText('功能尚未就绪，等待连接游戏并完成挂载')

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

    async def _sync_automation_overlay(self):
        sync = getattr(self.transport, 'automation_overlay', None)
        if not sync or not self.state.installed or not self.transport.connected or time.monotonic() < self._next_overlay_sync:
            return
        self._next_overlay_sync = time.monotonic() + 1.0
        active = self.automation.active
        payload = {'run_id': self.automation.run_id,
                   'active': self.automation.running or self.automation.stopping,
                   'task': '',
                   'phase': 'running' if active else 'waiting',
                   'status': '等待当前操作安全收尾' if self.state.stop_operation else '等待下一项定时任务'}
        if active:
            from package.daily_tasks.config import parse_config
            payload['task'] = parse_config(self.window.store.snapshot()['daily']).tasks[active].name
        elif self.automation.running and not self.state.blocked:
            upcoming = self.automation.next_check(datetime.now(BEIJING))
            payload['next_task'] = upcoming['name'] if upcoming else ''
            payload['next_check_at'] = (time.time() + upcoming['delay_seconds']) * 1000 if upcoming else None
            payload['status'] = '当前没有启用的定时任务' if upcoming is None else '本轮已完成，正在等待下次检查'
        if self.state.blocked:
            payload.update(phase='paused', status='托管已暂停：' + self.state.blocked)
        elif self.automation.stopping:
            payload['phase'] = 'stopping'
        try:
            reply = await sync(payload)
            if (isinstance(reply, dict) and reply.get('run_id') == self.automation.run_id
                    and reply.get('stop_requested') and self.automation.running):
                LOG.info('游戏内按钮请求退出日常托管')
                self.automation.set_automation(False)
            self._overlay_error = False
        except Exception as exc:
            if not self._overlay_error:
                LOG.warning('游戏托管状态浮层暂不可用：%s', str(exc) or type(exc).__name__)
            self._overlay_error = True

    def _publish_battle_assist_timing(self, rows):
        for key in ('battle_assist','control_chain'):
            panel=self.window.pages.get(key)
            if panel is not None and hasattr(panel,'set_timing_preview'):
                panel.set_timing_preview(rows)

    async def _sync_battle_assist_timing(self, config):
        getter=getattr(self.transport,'battle_assist_timing',None)
        if not (config.get('battle_assist') or {}).get('enabled') or not getter:
            self._publish_battle_assist_timing([])
            return
        if time.monotonic()<self._next_battle_timing:return
        self._next_battle_timing=time.monotonic()+1
        epoch=(self.session.engine_state.get('cdp_port') or self.session.engine_state.get('transport_key'), self.session.engine_state.get('miniapp_epoch'))
        try:
            rows=await getter()
        except Exception:
            rows=[]
        if self.state.closing or not self.state.installed or self.session.stale(epoch):
            self._publish_battle_assist_timing([])
            return
        self._publish_battle_assist_timing(rows if isinstance(rows,list) else [])

    async def poll(self):
        if self.state.closing or self._poll_lock.locked():
            return
        async with self._poll_lock:
            try:
                await self._sync_automation_overlay()
                if not await self.session.process_available():
                    self._publish_battle_assist_timing([])
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
                        self.window.action_label.setText(probe.get('message') or '功能尚未就绪，请关闭游戏弹窗并返回大厅，等待自动挂载')
                        self.window.set_gate(PHASE_MOUNTING, '已连接《遗弃之地》，等待加载至大厅')
                        return
                    # 大厅已确认，接下来就是挂载脚本；挂之前先把门禁切到"正在挂载"。
                    self.window.set_gate(PHASE_MOUNTING, '大厅已确认，正在挂载插件脚本')
                    LOG.info('开始挂载插件：平台=%s，当前实例=%s', self.platform_name, probe.get('resident_id') or '无')
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
                    self._next_overlay_sync = 0.0
                    self._overlay_error = False
                    self._next_energy = 0.0
                if self.state.configured is None:
                    self.window.action_label.setText('插件已挂载，正在检查账号与功能配置')
                if not await self._ensure_authorized():
                    return
                await self._check_update_once()
                config = self.window.store.snapshot()
                if config != self.state.configured and not self.state.blocked:
                    enabled={key:bool((config.get(key) or {}).get('enabled')) for key in ('daily','player','bloodmoon','damage','treasure','desire')}
                    LOG.info('开始同步插件配置：实例=%s；功能开关=%s', self.state.installed,enabled)
                    await self.transport.call('configure', config)
                    LOG.info('插件配置同步成功：实例=%s', self.state.installed)
                    self.state.configured = config
                if self.state.closing or self.automation.busy or self.session.stale(epoch):
                    return
                config = self.window.store.snapshot()
                self.window.set_debug_link(f'devtools://devtools/bundled/inspector.html?ws=127.0.0.1:{state["cdp_port"]}' if state.get('cdp_port') else '')
                initializing = self._feature_ready_session != self.state.installed
                if initializing:
                    self.window.set_connection(connected=True, target_appid=self.target_appid, runtime_ready=False)
                if self.state.blocked:
                    self.window.task_panels['energy'].runtime_message.setText(self.state.blocked)
                def feature_stage(name):
                    if initializing:
                        self.window.action_label.setText('正在初始化功能：' + name)
                        LOG.info('功能初始化阶段：%s；实例=%s', name, self.state.installed)
                feature_stage('血月战场')
                await self.season.poll(config)
                await self._sync_battle_assist_timing(config)
                self.timer.setInterval(self.season.scan_interval_ms if config.get('bloodmoon', {}).get('enabled') else 1000)
                if config['player']['enabled']:
                    feature_stage('玩家信息')
                    snapshot = await self.transport.call('player_information')
                    if self.state.closing or self.session.stale(epoch):
                        return
                    if isinstance(snapshot, dict) and snapshot != self._player_snapshot:
                        self._player_snapshot = snapshot
                        self.window.set_player_information(snapshot.get('text', ''), snapshot.get('subject', '玩家信息'))
                        LOG.info('玩家信息页面更新：%s', snapshot.get('subject', '玩家信息'))
                feature_stage('摸金地图')
                await self.treasure.poll(config)
                feature_stage('PVP伤害采集')
                await self.damage.poll(config)
                feature_stage('三尸合成')
                await self.desire.poll(config)
                if self.state.closing or self.session.stale(epoch):
                    return
                self.window.set_connection(connected=True, target_appid=self.target_appid, runtime_ready=not bool(self.state.blocked))
                if initializing:
                    self._feature_ready_session = self.state.installed
                    LOG.info('功能初始化完成：平台=%s；实例=%s',self.platform_name,self.state.installed)
                    self.window.action_label.setText('游戏与插件已就绪')
                if self.state.closing or self.session.stale(epoch):
                    return
                if time.monotonic() >= self._next_summary:
                    LOG.info('插件日常摘要：%s', self.window.task_panels['energy'].runtime_message.text())
                    self._next_summary = time.monotonic() + config['daily']['summary_interval_seconds']
                if self.automation.running and not self.state.blocked:
                    selected = self.automation.pick(datetime.now(BEIJING))
                    if selected:
                        self.automation.begin(selected)
            except CdpConnectionPending as exc:
                self._publish_battle_assist_timing([])
                error_key=(type(exc).__name__,str(exc),self.state.installed)
                now=time.monotonic()
                if error_key!=self._last_check_error or now>=self._next_check_error_log:
                    self._last_check_error=error_key;self._next_check_error_log=now+30
                    LOG.warning('%s',exc)
                self.window.set_connection(connected=False,message=str(exc))
                self.window.action_label.setText('正在等待游戏调试连接恢复')
                self.window.set_gate(self._link_phase(self.session.engine_state),str(exc))
            except Exception as exc:
                self._publish_battle_assist_timing([])
                detail=str(exc) or ('游戏或调试链路未响应' if isinstance(exc,TimeoutError) else type(exc).__name__)
                if isinstance(exc,TimeoutError) and self.automation.running:
                    self.state.stop_operation=True
                    self.state.blocked='游戏调试链路超时，已暂停日常；请核对当前操作后重新连接'
                    self.state.blocked_session=self.state.installed or self.state.blocked_session
                error_key=(type(exc).__name__,str(exc),self.state.installed)
                now=time.monotonic()
                if error_key!=self._last_check_error or now>=self._next_check_error_log:
                    self._last_check_error=error_key;self._next_check_error_log=now+30
                    LOG.exception('插件检查错误：平台=%s；实例=%s；已配置=%s；错误类型=%s；详情=%s',
                                  self.platform_name,self.state.installed,self.state.configured is not None,type(exc).__name__,detail)
                self.window.set_connection(connected=False, message='CDP检查失败：' + detail)
                self.window.action_label.setText('等待目标游戏就绪；不会重复未确认的任务')
                self.window.set_gate(self._link_phase(self.session.engine_state), 'CDP检查失败：' + detail)

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

        # 读到账号即尝试异步上报；本地拒绝也必须让服务端留下访问记录。
        self._start_handshake_report()

        # 本地先过一遍：公钥验签 + 绑定ID比对。验签不能省——省了别人把 license.bin
        # 里的 player_id 改成自己的号就能白用。
        bound, reason = license_module.bound_player_id(login_player_id=self._bound_id)
        if bound is None:
            self._reject_gate(reason)
            return False
        if bound != self._bound_id:
            self._reject_gate(f'license 绑定账号 {bound}，当前登录账号 {self._bound_id}')
            return False
        LOG.info('license 本地校验通过：%s', self._bound_id)
        self._authorized = True
        self.window.show_main_ui()
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
        if self.state.closing or self._update_checked or time.monotonic() < self._next_update_check:
            return
        if self._update_job is not None and not self._update_job.done():
            return
        self._update_job = asyncio.create_task(self._download_update())

    async def _download_update(self):
        self._update_attempts += 1
        try:
            if updater.pending_update() is not None:
                self._update_checked = True
                self.window.action_label.setText('更新已下载，正常退出插件后自动安装并重新启动')
                return
            plan = await asyncio.to_thread(updater.check, player_id=self._bound_id or '')
            if self.state.closing:
                return
            if not plan or not (plan.get('changed') or plan.get('removed')):
                self._update_checked = True
                return
            loop = asyncio.get_running_loop()
            last_notice = [0.0]
            def show(done, total, path):
                if not self.state.closing:
                    pct = int(done * 100 / total) if total else 100
                    self.window.action_label.setText(f'正在下载更新 {plan["version"]}：{pct}% · {path}')
            def progress(done, total, path):
                now = time.monotonic()
                if now-last_notice[0] >= .2 or done == total:
                    last_notice[0] = now
                    loop.call_soon_threadsafe(show, done, total, path)
            await asyncio.to_thread(updater.prepare, plan, progress=progress, cancel_event=self._update_cancel)
            self._update_checked = True
            if not self.state.closing:
                self.window.action_label.setText(f'新版本 {plan["version"]} 已就绪，正常退出后自动安装并重新启动')
        except Exception as exc:
            if self.state.closing:
                return
            LOG.warning('更新检查或下载失败（第%d次）：%s', self._update_attempts, exc)
            self._next_update_check = time.monotonic() + 60
            self._update_checked = self._update_attempts >= 3
            self.window.action_label.setText('更新失败，60秒后重试' if not self._update_checked else '更新失败，重启插件后可重试')

    async def wait_operation(self):
        await self.automation.wait_operation()

    def request_shutdown(self):
        if self._shutdown_job is None:
            # 抖音已有明确退出等待上限；其他平台显示估计值，仍以实际收尾为准。
            if hasattr(self.transport, 'detach_for_shutdown'):
                self.window.set_shutdown_estimate(self.transport.shutdown_timeout)
            self.state.closing = True
            self.state.stop_operation = True
            self.timer.stop()
            self._shutdown_job = asyncio.create_task(self.shutdown())

    async def shutdown(self):
        LOG.info('开始退出收尾：平台=%s；实例=%s；轮询在途=%s；更新在途=%s',self.platform_name,self.state.installed,
                 bool(self._poll_job and not self._poll_job.done()),bool(self._update_job and not self._update_job.done()))
        self._update_cancel.set()
        if self._closed.is_set():
            return
        self.state.closing = True
        self.state.stop_operation = True
        self.timer.stop()
        if hasattr(self.transport, 'detach_for_shutdown'):
            await self._shutdown_douyin()
            return
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
            LOG.info('游戏操作收尾完成，关闭插件窗口：平台=%s',self.platform_name)
            self.window.complete_shutdown()

    async def _shutdown_douyin(self):
        """抖音游戏失联时也能退出桌面；不据此认定在途请求已取消。"""
        drain = None
        try:
            if self._handshake_job is not None and not self._handshake_job.done():
                self._handshake_job.cancel()
            try:
                self.transport.begin_shutdown()
            except Exception as exc:
                LOG.warning('抖音退出通知写入失败：%s', exc)

            async def finish():
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

            drain = asyncio.create_task(finish())
            done, _ = await asyncio.wait({drain}, timeout=self.transport.shutdown_timeout)
            if done:
                await drain
            else:
                LOG.warning('抖音退出等待已到上限，断开本地通道；未确认的游戏操作不重发')
                self.transport.detach_for_shutdown()
        except Exception as exc:
            LOG.warning('抖音退出收尾异常，继续关闭本地窗口：%s', exc)
        finally:
            self.transport.detach_for_shutdown()
            if drain is not None and not drain.done():
                drain.cancel()
                drain.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            self.service.shutdown(wait=False)
            self.state.installed = self.state.configured = None
            self.window.set_operation_running(False)
            self.window.reset_session()
            self._closed.set()
            LOG.info('游戏操作收尾完成，关闭插件窗口：平台=%s',self.platform_name)
            self.window.complete_shutdown()

    async def wait_closed(self):
        await self._closed.wait()
