"""正式GUI运行服务测试：仅本地fake CDP/Qt事件，不操作微信。"""
import asyncio
import copy
import importlib
import json
import os
import time
from contextlib import asynccontextmanager

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel

from package.plugin_manager.store import PluginConfigStore
from package.plugin_manager.window import PluginWindow


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def runtime():
    try:
        return importlib.import_module('package.plugin_manager.runtime')
    except ModuleNotFoundError:
        pytest.fail('内部CDP运行服务尚未接入')


class FakeService(QObject):
    state_changed = Signal(dict)
    offset_detecting_changed = Signal(bool)
    def __init__(self):
        super().__init__()
        self.state = {'status':'stopped','miniapp':False,'cdp_port':0,'owner_key':'1','miniapp_epoch':0}
        self.starts=[]
        self.closed=False
    def start_debug(self, record):
        self.starts.append(record)
    def stop_debug(self):
        self.closed=False
    def snapshot(self):
        return copy.deepcopy(self.state)
    def shutdown(self, wait=False):
        self.closed=True
    def update(self, **patch):
        self.state.update(patch)
        self.state_changed.emit(copy.deepcopy(self.state))


class FakeTransport:
    def __init__(self):
        self.connected=False
        self.ready=True
        self.target=True
        self.session_id='one'
        self.calls=[]
        self.energy=30
        self.release=None
        self.entered=None
    async def connect(self, port):
        self.calls.append(('connect', port))
        self.connected=True
    async def probe(self):
        return {'appid':'wx6d5e82c174635a48' if self.target else 'wrong','ready':self.ready,'context_id':7,'resident_id':self.session_id}
    async def install(self):
        self.calls.append(('install', None))
        return self.session_id
    async def call(self, op, payload=None):
        self.calls.append((op,copy.deepcopy(payload)))
        if op=='inspect':return {'energy':self.energy,'maximum':100,'safe':True}
        if op=='catalog':return {'sanshi':[0],'magic':[{'artifact':201,'plan':1}], 'eye':11}
        if op in ('capture','restore'):
            return {'role_id':1,'selection':{'sanshi':0,'artifact':201,'plan':1,'eye':10},'formation':1,'slots':[10,11,0,0]}
        if op=='select':return 10
        if op=='optimize':return {'choice':{'sanshi':0,'artifact':201,'plan':1},'gold':10,'scores':[],'measured':[]}
        if op=='quote':return {'energy':self.energy,'cost':10,'sweep_num':0,'allowed':True}
        if op=='sweep':
            if self.entered:self.entered.set()
            if self.release:await self.release.wait()
            self.energy=0
            return {'energy':0,'sweep_num':1}
        return True
    def invalidate(self):
        self.connected=False
    async def wait_idle(self):
        self.calls.append(('wait_idle',None))
        if hasattr(self,'idle_release'):
            await self.idle_release.wait()
    async def close(self):
        self.calls.append(('close',None))
        self.connected=False


def make_controller(tmp_path, process=True):
    m=runtime()
    service,transport=FakeService(),FakeTransport()
    window=PluginWindow(PluginConfigStore(tmp_path/'plugins.json'))
    controller=m.PluginRuntime(window,service=service,transport=transport,process_ready=lambda:process)
    return controller,service,transport,window


async def ready(controller, service):
    await controller.poll()
    service.update(status='running',worker_alive=True,miniapp=True,frida=True,cdp_port=62000,miniapp_epoch=1)
    await controller.poll()


def test_bloodmoon_fast_poll_does_not_refresh_other_features(app, tmp_path):
    async def run():
        c, s, t, w = make_controller(tmp_path)
        try:
            await ready(c, s)
            w.store.set_bloodmoon({'enabled': True})
            config = w.store.snapshot()
            c.state.configured = copy.deepcopy(config)
            c._feature_ready_session = c.state.installed
            c._next_full_poll = float('inf')
            scans = []
            async def scan(config): scans.append(True)
            c.season.poll = scan
            before = list(t.calls)
            for _ in range(10): await c.poll()
            assert len(scans) == 10
            assert t.calls == before
            c._next_full_poll = 0
            await c.poll()
            assert len(t.calls) > len(before)
        finally:
            await c.shutdown(); w.close()
    asyncio.run(run())


def test_shutdown_stops_game_collectors_before_disconnecting(app, tmp_path):
    async def run():
        c, s, t, w = make_controller(tmp_path)
        await ready(c, s)
        async def damage_stop(): t.calls.append(('damage_stop', None))
        async def season_call(op): t.calls.append(('season_' + op, None))
        t.damage_stop = damage_stop
        t.season_call = season_call
        try:
            await c.shutdown()
            ops = [op for op, _ in t.calls]
            assert ops.index('wait_idle') < ops.index('damage_stop') < ops.index('close')
            assert ops.index('season_stop') < ops.index('close')
        finally:
            w.close()
    asyncio.run(run())


def test_startup_activity_cleanup_gates_feature_configuration(app, tmp_path):
    async def run():
        controller, service, transport, window = make_controller(tmp_path)
        cleared = [False]
        async def cleanup():return {'ready':cleared[0], 'message':'等待开屏活动关闭'}
        transport.dismiss_startup = cleanup
        try:
            await controller.poll()
            service.update(status='running', worker_alive=True, miniapp=True, frida=True, cdp_port=62000, miniapp_epoch=1)
            await controller.poll()
            assert controller.state.installed
            assert not any(op == 'configure' for op, _ in transport.calls)
            assert '开屏活动' in window.action_label.text()
            cleared[0] = True
            await controller.poll()
            assert any(op == 'configure' for op, _ in transport.calls)
        finally:
            await controller.shutdown()
            window.close()
    asyncio.run(run())


def test_late_startup_page_checked_after_initial_hall_handoff(app, tmp_path):
    async def run():
        controller, service, transport, window = make_controller(tmp_path)
        response = [{'ready': True}]
        calls = []
        async def cleanup():
            calls.append(True)
            return response[0]
        transport.dismiss_startup = cleanup
        try:
            await ready(controller, service)
            initial = len(calls)
            controller._next_full_poll = 0
            response[0] = {'ready': False, 'pendingStartup': True, 'message': '已点击开屏页关闭按钮：LateFirstFaceUI'}
            await controller.poll()
            assert len(calls) > initial
            assert 'LateFirstFaceUI' in window.action_label.text()
            response[0] = {'ready': False, 'message': '待手动关闭的开屏页面：LegionUI'}
            controller._next_full_poll = 0
            controller._feature_ready_session = None
            await controller.poll()
            assert controller._feature_ready_session == controller.state.installed
            controller._startup_watch_until = 0
            controller._next_full_poll = 0
            before = len(calls)
            await controller.poll()
            assert len(calls) == before
        finally:
            await controller.shutdown()
            window.close()
    asyncio.run(run())


@pytest.mark.parametrize('task', ['daily', 'desire', 'pet_fodder'])
def test_restart_resumes_supported_task_once_from_new_session(app, tmp_path, task):
    async def run():
        c, s, t, w = make_controller(tmp_path)
        calls = []
        try:
            w.store.set_daily_enabled(True)
            c.desire.request = lambda op, args=None: calls.append(('desire', op))
            c.automation.set_automation = lambda running: calls.append(('daily', running))
            c.automation.begin = lambda name, **kwargs: calls.append((name, kwargs))
            c.restart_resume.observe({task}, 'old', healthy=True)
            c.restart_resume.arm()
            c.restart_resume.launched = True
            c.state.installed = 'old'
            assert not c._resume_restarted_tasks()
            c.state.installed = 'new'
            c.state.blocked = '开屏尚未确认'
            assert not c._resume_restarted_tasks()
            c.state.blocked = ''
            assert c._resume_restarted_tasks()
            assert not c._resume_restarted_tasks()
            assert len(calls) == 1
            assert calls[0] == {'daily': ('daily', True), 'desire': ('desire', 'start'),
                                'pet_fodder': ('pet_fodder', {'manual': True})}[task]
        finally:
            await c.shutdown()
            w.close()
    asyncio.run(run())


def test_waits_for_wechat_without_launching_it(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path,False)
        try:
            await c.poll()
            assert not s.starts and not t.calls
            assert '等待微信' in w.connection_label.text()
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_debug_session_hooks_before_the_game_starts(app,tmp_path):
    """hook 必须在小程序启动前装好：检测到微信就发会话，不等游戏起来。"""
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            c.session.process_ready=lambda:True
            await c.poll()
            assert len(s.starts)==1,'检测到微信就该挂调试（游戏还没开也要发）'
            await c.poll()
            assert len(s.starts)==1,'不能重复发'
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_autodetect_hint_is_shown_while_waiting_for_cdp(app,tmp_path):
    """偏移自动检测期间界面要能看到进度提示，不能等 error 才显示。"""
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await c.poll()
            s.update(message='正在自动检测 25799 偏移…')
            await c.poll()
            assert '自动检测' in w.connection_label.text()
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_offset_adapting_dialog_is_exclusive_and_closes(app,tmp_path):
    """检测到热更新算偏移时要弹独占窗口，算完必须自己关掉。"""
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            s.offset_detecting_changed.emit(True)
            dialog=w._offset_dialog.dialog
            assert dialog is not None and dialog.isVisible() and dialog.isModal()
            assert dialog.windowTitle()=='正在适配'
            assert any('热更新' in label.text() for label in dialog.findChildren(QLabel))
            s.offset_detecting_changed.emit(False)
            assert w._offset_dialog.dialog is None,'算完必须关闭独占窗口'
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_debug_session_is_resent_when_cdp_never_comes(app,tmp_path):
    from package.plugin_manager import session as session_module
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            c.session.process_ready=lambda:True
            await c.poll()
            assert len(s.starts)==1
            # 模拟一直没连上：到点应重发调试会话。
            c.session._next_debug_retry=time.monotonic()-1
            await c.poll()
            assert len(s.starts)==2,s.starts
            for _ in range(session_module.DEBUG_MAX_RETRIES + 2):
                c.session._next_debug_retry=time.monotonic()-1
                await c.poll()
            assert len(s.starts)==1+session_module.DEBUG_MAX_RETRIES,'重试次数要有上限'
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_internal_service_auto_inject_once_after_target_and_hall_ready(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await c.poll()
            assert len(s.starts)==1
            s.update(status='running',worker_alive=True,miniapp=True,frida=True,cdp_port=62000,miniapp_epoch=1)
            t.target=False
            await c.poll()
            assert not any(op=='install' for op,_ in t.calls)
            assert not w.game_connected
            t.target=True;t.ready=False
            await c.poll()
            assert not any(op=='install' for op,_ in t.calls)
            t.ready=True
            await c.poll();await c.poll()
            assert sum(op=='install' for op,_ in t.calls)==1
            assert w.game_connected and w.runtime_ready
            assert w.pages['debug'].link.text().endswith('127.0.0.1:62000')
            assert w.test_actions_for('arena')['arena'].isEnabled()
            assert w.test_actions_for('energy')['energy'].isEnabled()
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_config_updates_live_and_manual_test_bypasses_only_threshold(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            w.store.set_task_enabled('energy',True)
            w.store.set_daily_enabled(True)
            await c.poll()
            await c.wait_operation()  # 自动阈值检查收尾后再测试，避免同时手动执行。
            assert any(op=='configure' and args['daily']['enabled'] for op,args in t.calls)
            assert not any(op=='sweep' for op,_ in t.calls)
            w.request_test('energy',confirmed=True)
            await c.wait_operation()
            assert sum(op=='sweep' for op,_ in t.calls)==1
            assert any(op=='restore' for op,_ in t.calls)
            assert w._busy_task is None
            assert not (tmp_path/'plugins.energy_restore.json').exists()
            w.store.set_task_enabled('energy',False)
            t.energy=90
            await c.poll()
            assert sum(op=='sweep' for op,_ in t.calls)==1
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_new_epoch_clears_old_state_and_injects_fresh(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            w.set_player_information('临时信息','本人')
            s.update(miniapp=False,miniapp_epoch=2)
            await c.poll()
            assert not w.game_connected
            assert not w.pages['player'].text.toPlainText()
            t.session_id='two'
            s.update(miniapp=True)
            await c.poll()
            assert sum(op=='install' for op,_ in t.calls)==2
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_close_waits_for_sweep_response_and_restore_before_service_shutdown(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        await ready(c,s)
        t.entered=asyncio.Event();t.release=asyncio.Event()
        w.request_test('energy',confirmed=True)
        await t.entered.wait()
        assert not w.close()
        assert not s.closed
        t.release.set()
        await c.wait_closed()
        assert s.closed
        assert any(op=='restore' for op,_ in t.calls)
        assert not w.game_connected
    asyncio.run(run())


def test_no_automatic_dispatch_until_automation_is_started(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            w.store.set_daily_enabled(True);w.store.set_task_enabled('energy',True)
            t.energy=90
            await c.poll()
            assert not any(op=='sweep' for op,_ in t.calls)
            c.automation.set_automation(True)
            await c.poll();await c.wait_operation()
            assert sum(op=='sweep' for op,_ in t.calls)==1
            c.automation.set_automation(False)
            t.energy=90
            await c.poll()
            assert sum(op=='sweep' for op,_ in t.calls)==1
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_ui_rejection_retries_twice_then_returns_home(app,tmp_path):
    from package.daily_tasks.scheduler import RetryableTaskError
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            attempts=[]
            original=t.call
            async def call(op,args=None):
                if op=='sweep':
                    attempts.append(op)
                    raise RetryableTaskError('界面未就绪')
                return await original(op,args)
            t.call=call
            w.request_test('energy',confirmed=True)
            await c.wait_operation()
            assert attempts==['sweep','sweep','sweep'],attempts
            assert ('home',None) in t.calls
            assert any(op=='restore' for op,_ in t.calls),'未确认的操作不得留下已改配置'
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_uncertain_result_is_never_retried(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            attempts=[]
            original=t.call
            async def call(op,args=None):
                if op=='sweep':
                    attempts.append(op)
                    raise ExecutionUncertain('响应丢失')
                return await original(op,args)
            t.call=call
            w.request_test('energy',confirmed=True)
            await c.wait_operation()
            assert attempts==['sweep'],attempts
            assert c.state.blocked
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_automation_cannot_start_while_session_is_blocked(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            c.state.blocked='上次操作未确认'
            c.automation.set_automation(True)
            assert not c.automation.running
            assert '停止' not in w.pages['daily'].run_button.text()
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


class FakeCdp:
    def __init__(self):
        self.handlers={};self.messages=[];self.live=False
        self.context=7;self.appid='wx6d5e82c174635a48';self.hall=True;self.resident=None
    def on(self,method,fn):self.handlers[method]=fn
    def is_connected(self):return self.live
    async def connect(self,url,**kwargs):self.live=True
    async def close(self):self.live=False
    async def send(self,method,params=None,**kwargs):
        self.messages.append((method,params))
        if method=='Runtime.enable':return {'result':{}}
        m=importlib.import_module('package.plugin_manager.transport')
        expression=params['expression']
        if expression==m.LOCATION_PROBE:value=f'https://servicewechat.com/{self.appid}/65/page-frame.html'
        elif expression==m.GAME_PROBE:
            value={'game':params.get('contextId')==self.context,'hall':self.hall,'resident_id':self.resident}
        elif 'createPluginRuntime' in expression:
            self.resident='injected';value={'resident_id':'injected','capabilities':['lazy-v1']}
        elif 'r.register(' in expression:value=True
        elif expression.startswith('globalThis.__e0e1PluginRuntime'):
            value={'status':'ok','value':{'energy':30,'maximum':100,'safe':True}}
        else:raise AssertionError(expression)
        return {'result':{'result':{'value':value}}}


def test_transport_dynamic_context_once_injection_then_small_calls_no_http():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        probe=await transport.probe()
        assert probe['appid']==transport.TARGET_APPID and probe['ready']
        transport.session_id='injected'
        await transport.install()
        await transport.call('inspect')
        expressions=[p['expression'] for method,p in fake.messages if method=='Runtime.evaluate']
        assert sum('createEnergyRuntime' in e for e in expressions)==1
        assert expressions[-1].startswith('globalThis.__e0e1PluginRuntime')
        assert 'createEnergyRuntime' not in expressions[-1]
        await transport.close()
    asyncio.run(run())


def test_injection_during_context_destruction_cannot_mark_runtime_ready():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        original=fake.send
        async def send(method, params=None, **kwargs):
            response=await original(method,params,**kwargs)
            if method=='Runtime.evaluate' and 'createPluginRuntime' in params['expression']:
                fake.handlers['Runtime.executionContextDestroyed']({'params':{'executionContextId':7}})
            return response
        fake.send=send
        transport.session_id='injected'
        with pytest.raises(RuntimeError):
            await transport.install()
        assert transport.session_id is None
        await transport.close()
    asyncio.run(run())


def test_disabled_during_pending_sweep_stops_after_receipt_and_restores(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            w.store.set_daily_enabled(True);w.store.set_task_enabled('energy',True)
            c.automation.set_automation(True)  # 自动派发必须先点击“开始日常自动化”
            assert c.automation.running
            t.energy=90;t.entered=asyncio.Event();t.release=asyncio.Event()
            await c.poll();await t.entered.wait()
            w.store.set_task_enabled('energy',False)
            assert not c.automation.operation.done()
            t.release.set();await c.wait_operation()
            assert sum(op=='sweep' for op,_ in t.calls)==1
            assert any(op=='restore' for op,_ in t.calls)
            assert not w._operation_running
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_poll_cannot_start_second_round_during_manual_execution(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            w.store.set_daily_enabled(True);w.store.set_task_enabled('energy',True)
            configured,continue_poll=asyncio.Event(),asyncio.Event()
            t.entered=asyncio.Event();t.release=asyncio.Event();t.energy=90
            original=t.call
            async def call(op,args=None):
                if op=='configure':
                    configured.set();await continue_poll.wait()
                return await original(op,args)
            t.call=call
            poll=asyncio.create_task(c.poll())
            await configured.wait()
            w.request_test('energy',confirmed=True)
            manual=c.automation.operation
            await t.entered.wait()
            continue_poll.set();await poll
            assert c.automation.operation is manual
            t.release.set();await c.wait_operation()
            assert sum(op=='sweep' for op,_ in t.calls)==1
        finally:
            if t.release:t.release.set()
            await c.shutdown();w.close()
    asyncio.run(run())


def test_error_blocks_retry_until_real_new_context(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            from package.daily_tasks.scheduler import ExecutionUncertain
            original=t.call
            async def call(op,args=None):
                if op=='sweep':raise ExecutionUncertain('响应丢失')
                return await original(op,args)
            t.call=call
            w.request_test('energy',confirmed=True)
            await c.wait_operation()
            assert not w.runtime_ready
            assert c.state.blocked
            await c.poll()
            assert c.state.blocked and not w.runtime_ready
            assert not any(op=='restore' for op,_ in t.calls)
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_same_live_resident_does_not_reset_uncertain_result_on_epoch_change(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            c.state.blocked='未确认，禁止重试'
            c.state.blocked_session=c.state.installed
            s.update(miniapp=False,miniapp_epoch=2)
            await c.poll()
            s.update(miniapp=True)
            await c.poll()
            assert c.state.blocked and not w.runtime_ready
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_shutdown_cannot_close_cdp_until_old_js_is_confirmed_idle(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        await ready(c,s)
        t.idle_release=asyncio.Event()
        shutdown=asyncio.create_task(c.shutdown())
        await asyncio.sleep(0)
        assert not s.closed
        assert not shutdown.done()
        t.idle_release.set()
        await shutdown
        names=[name for name,_ in t.calls]
        assert names.index('wait_idle') < names.index('close')
    asyncio.run(run())


def test_port_change_reconnects_internal_cdp_before_injection(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            # 模拟真实invalidate只清context、不直接断开WebSocket。
            t.invalidate=lambda:None
            t.port=62000
            t.session_id='two'
            s.update(cdp_port=62001,miniapp_epoch=2)
            await c.poll()
            assert ('connect',62001) in t.calls
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_reconnect_to_same_live_context_recognizes_own_resident_without_reinjecting():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        transport.session_id='injected'
        await transport.install()
        fake.live=False
        assert not (await transport.probe())['ready']
        await transport.connect(62000)
        probe=await transport.probe()
        assert probe['resident_id']=='injected'
        assert transport.session_id=='injected'
        assert sum('createPluginRuntime' in p.get('expression','') for method,p in fake.messages if p)==1
        await transport.close()
    asyncio.run(run())


def test_unconfirmed_command_waits_for_js_terminal_state_without_replay():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        from package.daily_tasks.scheduler import ExecutionUncertain
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        transport.session_id='injected';await transport.install()
        original=fake.send;reads=0;actions=[]
        async def send(method,params=None,**kwargs):
            nonlocal reads
            if method=='Runtime.evaluate' and params['expression'].startswith('globalThis.__e0e1PluginRuntime'):
                actions.append(params['expression'])
                raise asyncio.TimeoutError
            if method=='Runtime.evaluate' and 'const r=globalThis.__e0e1PluginRuntime' in params['expression'] and 'r.register(' not in params['expression']:
                reads+=1
                return {'result':{'result':{'value':{'id':'injected','pending':reads<2}}}}
            return await original(method,params,**kwargs)
        fake.send=send
        with pytest.raises(ExecutionUncertain):await transport.call('sweep')
        assert transport._inflight
        with pytest.raises(ExecutionUncertain):await transport.call('configure', {'enabled':False})
        assert len(actions)==1  # 在途终态未确认前不能发送另一命令。
        assert transport._inflight
        await transport.wait_idle()
        assert reads==2 and transport._inflight is None
        await transport.close()
    asyncio.run(run())


def test_resident_script_tracks_pending_operation_and_small_config_messages():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        import subprocess,sys
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        transport.session_id='injected';await transport.install()
        source=next(params['expression'] for method,params in fake.messages if params and 'createPluginRuntime' in params.get('expression',''))
        # 用Node假运行api，仅验证生成的驻留容器，不操作任何游戏数据。
        source+="\nglobalThis.__e0e1PluginRuntime.register('ui',()=>({dispatch:async()=>await globalThis.release}));"
        code='''const assert=require('node:assert/strict'); const vm=require('node:vm');
const source=require('fs').readFileSync(process.argv[1],'utf8'); const g={};let resolve;g.release=new Promise(r=>resolve=r);vm.createContext(g);vm.runInContext(source,g);
(async()=>{const r=g.__e0e1PluginRuntime;const job=r.dispatch('sweep',{});assert.equal(r.pending,true);const blocked=await r.dispatch('eye',{});assert.equal(blocked.status,'uncertain');await r.dispatch('configure',{daily:{enabled:false}});assert.equal(r.pending,true);resolve({status:'ok',value:1});await job;assert.equal(r.pending,false);await r.dispatch('stop',{});assert.equal((await r.dispatch('sweep',{})).status,'unavailable');})().catch(e=>{console.error(e);process.exit(1)});'''
        # 注入源码已经超过 Windows 命令行长度上限，走临时文件而不是 argv。
        import tempfile
        handle=tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
        try:
            handle.write(source)
            handle.close()
            result=subprocess.run(['node','-e',code,handle.name],capture_output=True,text=True,timeout=10)
        finally:
            os.unlink(handle.name)
        assert result.returncode==0,result.stderr
        await transport.close()
    asyncio.run(run())


def test_context_id_reuse_does_not_skip_new_request_terminal_check():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        transport.session_id='injected';await transport.install()
        fake.handlers['Runtime.executionContextDestroyed']({'params':{'executionContextId':7}})
        fake.resident=None
        await transport.connect(62001)
        transport.session_id='injected';await transport.install()
        from package.daily_tasks.scheduler import ExecutionUncertain
        original=fake.send;reads=[]
        async def send(method,params=None,**kwargs):
            if method=='Runtime.evaluate' and params['expression'].startswith('globalThis.__e0e1PluginRuntime'):
                raise asyncio.TimeoutError
            if method=='Runtime.evaluate' and 'const r=globalThis.__e0e1PluginRuntime' in params['expression'] and 'r.register(' not in params['expression']:
                reads.append(True)
                return {'result':{'result':{'value':{'id':'injected','pending':False}}}}
            return await original(method,params,**kwargs)
        fake.send=send
        with pytest.raises(ExecutionUncertain):await transport.call('sweep')
        await transport.wait_idle()
        assert reads==[True]
        await transport.close()
    asyncio.run(run())


def test_destroyed_context_clears_only_its_old_inflight_marker():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        transport.session_id='injected';await transport.install()
        transport._inflight={'id':'injected','context':7}
        fake.handlers['Runtime.executionContextDestroyed']({'params':{'executionContextId':7}})
        assert transport._inflight is None
        fake.resident=None
        await transport.probe()
        transport.session_id='injected';await transport.install()
        assert await transport.call('configure',{})
        await transport.close()
    asyncio.run(run())


def test_context_destroyed_during_target_probe_does_not_send_action():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        transport.session_id='injected';await transport.install()
        original=fake.send
        async def send(method,params=None,**kwargs):
            receipt=await original(method,params,**kwargs)
            if method=='Runtime.evaluate' and params['expression']==m.LOCATION_PROBE:
                fake.handlers['Runtime.executionContextDestroyed']({'params':{'executionContextId':7}})
            return receipt
        fake.send=send
        before=len(fake.messages)
        with pytest.raises(RuntimeError):await transport.call('sweep')
        actions=[params for method,params in fake.messages[before:] if method=='Runtime.evaluate' and params['expression'].startswith('globalThis.__e0e1PluginRuntime')]
        assert not actions
        await transport.close()
    asyncio.run(run())


def test_configure_timeout_recovers_after_terminal_check_without_game_action(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            original=t.call
            pending=False;failed=False
            async def call(op,args=None):
                nonlocal pending,failed
                if op=='configure' and not failed:
                    failed=True;pending=True
                    from package.daily_tasks.scheduler import ExecutionUncertain
                    raise ExecutionUncertain('配置回执超时')
                if pending:
                    from package.daily_tasks.scheduler import ExecutionUncertain
                    raise ExecutionUncertain('上一命令未确认')
                return await original(op,args)
            async def wait_idle():
                nonlocal pending
                pending=False
            t.call=call;t.wait_idle=wait_idle
            await ready(c,s)
            assert not w.runtime_ready
            await c.poll()
            assert w.runtime_ready
            assert not any(op=='sweep' for op,_ in t.calls)
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_process_scan_runs_off_event_loop_and_is_cached(app, tmp_path):
    async def run():
        import threading, time
        c,s,t,w=make_controller(tmp_path)
        main_thread=threading.get_ident()
        started=threading.Event(); release=threading.Event(); scans=[]; heartbeat=[]
        def slow_scan():
            scans.append(threading.get_ident());started.set()
            release.wait(0.5)
            return True
        c.session.process_ready=slow_scan
        loop=asyncio.get_running_loop()
        loop.call_later(0.05, lambda: (heartbeat.append(True),release.set()))
        try:
            await c.poll()
            assert heartbeat, '同步扫描堵塞了事件循环'
            assert scans == [scans[0]] and scans[0] != main_thread
            await c.poll()
            assert len(scans)==1
        finally:
            release.set();await c.shutdown();w.close()
    asyncio.run(run())


def test_player_ui_information_updates_gui_when_enabled(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            original=t.call
            async def call(op,args=None):
                if op=='player_information':return {'subject':'玩家A（公开页面）','text':'战力100'}
                return await original(op,args)
            t.call=call
            w.store.set_player_enabled(True)
            await c.poll()
            assert w.pages['player'].text.toPlainText()=='战力100'
            assert '玩家A' in w.pages['player'].subject.text()
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_file_logging_records_actions_and_errors_without_loop_spam(tmp_path):
    import logging
    from package.plugin_manager.logging_setup import start_file_logging
    session=start_file_logging(tmp_path/'plugin.log')
    log=logging.getLogger('plugin_manager')
    try:
        log.info('操作开始：体力扫荡')
        log.error('报错：阵眼未找到')
    finally:
        session.close()
    text=(tmp_path/'plugin.log').read_text(encoding='utf-8')
    assert '操作开始' in text and '报错' in text


def test_ui_console_events_logged_only_for_current_game_context(caplog):
    import logging
    from package.plugin_manager.transport import PluginTransport
    fake=FakeCdp();transport=PluginTransport(cdp=fake);transport.context_id=7
    with caplog.at_level(logging.INFO,logger='plugin_manager'):
        fake.handlers['Runtime.consoleAPICalled']({'params':{'executionContextId':7,'args':[{'value':'[plugin.ui]'},{'value':'点击阵眼'}]}})
        fake.handlers['Runtime.consoleAPICalled']({'params':{'executionContextId':7,'args':[{'value':'[plugin.error]'},{'value':'匹配失败'}]}})
        fake.handlers['Runtime.consoleAPICalled']({'params':{'executionContextId':8,'args':[{'value':'[plugin.ui]'},{'value':'其他页面'}]}})
    assert '点击阵眼' in caplog.text and '匹配失败' in caplog.text and '其他页面' not in caplog.text


def test_wait_idle_reconnect_recognizes_confirmed_destroyed_context():
    async def run():
        runtime()
        from package.plugin_manager.transport import PluginTransport
        fake=FakeCdp();transport=PluginTransport(cdp=fake)
        await transport.connect(62000)
        transport._inflight={'id':'injected','context':7};fake.live=False
        original=fake.send
        async def send(method,params=None,**kwargs):
            if method=='Runtime.evaluate' and 'const r=globalThis.__e0e1PluginRuntime' in params['expression'] and 'r.register(' not in params['expression']:
                raise RuntimeError(json.dumps({'code':-32000,'message':'Cannot find context with specified id'}))
            return await original(method,params,**kwargs)
        fake.send=send
        await asyncio.wait_for(transport.wait_idle(),0.5)
        assert transport._inflight is None
        assert sum(method=='Runtime.enable' for method,_ in fake.messages)>=2
        await transport.close()
    asyncio.run(run())


def test_transport_refuses_foreign_target_and_invalidates_destroyed_context():
    async def run():
        runtime()
        m=importlib.import_module('package.plugin_manager.transport')
        fake=FakeCdp();transport=m.PluginTransport(cdp=fake)
        await transport.connect(62000)
        fake.appid='wrong'
        assert not (await transport.probe())['ready']
        with pytest.raises(RuntimeError):await transport.install()
        fake.appid=transport.TARGET_APPID
        await transport.probe()
        transport.session_id='injected';await transport.install()
        fake.handlers['Runtime.executionContextDestroyed']({'params':{'executionContextId':7}})
        assert not transport.session_id
        with pytest.raises(RuntimeError):await transport.call('sweep')
        await transport.close()
    asyncio.run(run())


def test_license_match_opens_ui_and_handshake_never_blocks(app,tmp_path,monkeypatch):
    """门禁只认 license 绑定ID；后台 handshake 是上报，在飞或失败都不许拖住主 UI。"""
    import threading
    m=runtime()
    from package.plugin_manager import build_info as build_info_module
    from package.plugin_manager import license as license_module
    from package.plugin_manager import server_client
    async def run():
        c,s,t,w=make_controller(tmp_path)
        entered,release=threading.Event(),threading.Event()
        try:
            monkeypatch.setattr(m,'build_info',lambda:build_info_module.BuildInfo('release','1.0.0','localhost:1'))
            monkeypatch.setattr(m.updater,'check',lambda **kwargs:None)
            monkeypatch.setattr(license_module,'load',lambda:{'player_id':'role-7'})
            monkeypatch.setattr(license_module,'verify',lambda payload:True)
            calls=[]
            def slow_handshake(**kwargs):
                calls.append(kwargs)
                entered.set()
                release.wait(5)   # 后台很慢，但主 UI 不能等它
                return server_client.HandshakeResult(False,'denied','后台未放行','9.9.9',True)
            monkeypatch.setattr(server_client,'handshake',slow_handshake)
            original=t.call
            async def call(op,args=None):
                if op=='identity':return {'player_id':'role-7','legion_name':'阴司'}
                return await original(op,args)
            t.call=call
            await ready(c,s)
            # 上报还在飞（甚至还没调度到），主 UI 已经放出来了。
            assert w.main_ui_shown
            assert not c.state.blocked
            for _ in range(200):
                if entered.is_set():break
                await asyncio.sleep(0.01)
            assert entered.is_set(),'登录信息应该报给后台'
            release.set()
            await asyncio.wait_for(c._handshake_job, 10)   # 等它真正跑完，别留个被取消的任务
            assert calls==[{'player_id':'role-7','legion_name':'阴司','player_name':''}]
            assert not c.state.blocked,'后台不放行／要求更新都不能拦住已放行的用户'
            assert w.main_ui_shown
        finally:
            release.set()
            await c.shutdown();w.close()
    asyncio.run(run())


def test_license_mismatch_keeps_ui_on_gate(app,tmp_path,monkeypatch):
    m=runtime()
    from package.plugin_manager import build_info as build_info_module
    from package.plugin_manager import license as license_module
    from package.plugin_manager import server_client
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            monkeypatch.setattr(m,'build_info',lambda:build_info_module.BuildInfo('release','1.0.0','localhost:1'))
            monkeypatch.setattr(license_module,'load',lambda:{'player_id':'role-7'})
            monkeypatch.setattr(license_module,'verify',lambda payload:True)
            reports=[]
            def rejected_report(**kwargs):
                reports.append(kwargs)
                return server_client.HandshakeResult(False,'player_id_mismatch','账号未授权','',False)
            monkeypatch.setattr(server_client,'handshake',rejected_report)
            original=t.call
            async def call(op,args=None):
                if op=='identity':return {'player_id':'role-9'}
                return await original(op,args)
            t.call=call
            await ready(c,s)
            assert not w.main_ui_shown
            assert w.gate.title.text()=='此账号未授权'
            assert 'role-9' in w.gate.detail.text()
            assert c.state.blocked
            await c._handshake_job
            assert reports[0]['player_id']=='role-9'
            await c._ensure_authorized()
            assert len(reports)==1
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


@pytest.mark.parametrize("payload", [None, {"player_id":"role-7", "signature":"bad"}])
def test_invalid_or_missing_license_still_reports_login(app,tmp_path,monkeypatch,payload):
    m=runtime()
    from package.plugin_manager import build_info as build_info_module, license as license_module, server_client
    async def run():
        c,s,t,w=make_controller(tmp_path)
        calls=[]
        try:
            monkeypatch.setattr(m,'build_info',lambda:build_info_module.BuildInfo('release','1.0.0','localhost:1'))
            monkeypatch.setattr(license_module,'load',lambda:payload)
            monkeypatch.setattr(license_module,'verify',lambda _:False)
            def report(**kwargs):
                calls.append(kwargs)
                return server_client.HandshakeResult(False,'invalid_license','授权无效','',False)
            monkeypatch.setattr(server_client,'handshake',report)
            original=t.call
            async def call(op,args=None):
                if op=='identity':return {'player_id':'role-9','name':'来访玩家','legion_name':'阴司'}
                return await original(op,args)
            t.call=call
            await ready(c,s)
            assert not w.main_ui_shown and c.state.blocked
            await c._handshake_job
            await c._ensure_authorized()
            assert len(calls)==1
            assert calls[0]['player_id']=='role-9' and calls[0]['player_name']=='来访玩家'
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())



def test_douyin_shutdown_has_deadline_when_game_never_replies(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        await ready(c,s)
        stalled=asyncio.Event()
        notifications=[]
        t.shutdown_timeout=.02
        def begin():notifications.append('begin')
        def detach():
            notifications.append('detach');t.connected=False;stalled.set()
        async def blocked_idle():
            await stalled.wait()
            raise RuntimeError('reply unknown')
        t.begin_shutdown=begin;t.detach_for_shutdown=detach;t.wait_idle=blocked_idle
        w.set_operation_running(True)
        await asyncio.wait_for(c.shutdown(),.5)
        assert c._closed.is_set() and s.closed
        assert 'begin' in notifications and 'detach' in notifications
        assert w._shutdown_complete and not w._operation_running
    asyncio.run(run())



def test_game_stop_button_is_polled_while_a_task_is_waiting_and_finishes_at_home(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        w.store.set_ui_flag("automation_overlay", True)
        try:
            await ready(c,s)
            c.automation.set_automation(True)
            t.entered=asyncio.Event();t.release=asyncio.Event()
            w.request_test('energy',confirmed=True)
            await t.entered.wait()
            payloads=[]
            async def overlay(payload):
                payloads.append(payload)
                return {'run_id':c.automation.run_id,'stop_requested':True}
            t.automation_overlay=overlay
            c._next_overlay_sync=0
            await c.poll()
            assert not c.automation.running and c.state.stop_operation
            assert c.automation.busy,'do not cancel an in-flight game request'
            t.release.set()
            await c.wait_operation()
            assert any(op=='home' for op,_ in t.calls)
            c._next_overlay_sync=0
            await c._sync_automation_overlay()
            assert payloads[-1]['active'] is False
        finally:
            if getattr(t,'release',None):t.release.set()
            await c.shutdown();w.close()
    asyncio.run(run())


def test_overlay_state_channel_does_not_wait_for_the_game_action_lock():
    async def run():
        m=importlib.import_module('package.plugin_manager.transport')
        transport=m.PluginTransport(cdp=FakeCdp())
        transport.connected=True;transport.session_id='owned';transport.context_id=7
        marker={'id':'game-action'};transport._inflight=marker
        async def evaluate(expression,context_id=None,timeout_ms=0):
            if 'r.register(' in expression:return True
            assert 'await o.update' in expression and 'owned' in expression
            return {'run_id':'run','stop_requested':True}
        transport._evaluate=evaluate
        async with transport._lock:
            result=await asyncio.wait_for(transport.automation_overlay({'run_id':'run','active':True}),.2)
        assert result['stop_requested'] and transport._inflight is marker
    asyncio.run(run())



def test_next_check_countdown_respects_task_delay_disabled_tasks_and_daily_window(app,tmp_path,monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    m=importlib.import_module('package.plugin_manager.automation')
    monkeypatch.setattr(m,'time',SimpleNamespace(monotonic=lambda:100.0))
    c,s,t,w=make_controller(tmp_path)
    try:
        for key in w.store.snapshot()['daily']['tasks']:w.store.set_task_enabled(key,False)
        assert c.automation.next_check(datetime(2026,10,18,9,tzinfo=m.BEIJING)) is None
        w.store.set_task_enabled('energy',True)
        c.automation._task_due['energy']=190
        result=c.automation.next_check(datetime(2026,10,18,9,tzinfo=m.BEIJING))
        assert result['task_id']=='energy' and result['delay_seconds']==90
        w.store.set_task_enabled('energy',False)
        w.store.set_task_enabled('arena',True)
        result=c.automation.next_check(datetime(2026,10,18,10,27,tzinfo=m.BEIJING))
        assert result['task_id']=='arena' and result['delay_seconds']==60
        result=c.automation.next_check(datetime(2026,10,18,10,31,tzinfo=m.BEIJING))
        assert result['delay_seconds']==23*3600+57*60
    finally:
        asyncio.run(c.shutdown());w.close()


def test_idle_overlay_reports_waiting_and_next_check_timestamp(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        w.store.set_ui_flag("automation_overlay", True)
        try:
            await ready(c,s)
            for key in w.store.snapshot()['daily']['tasks']:w.store.set_task_enabled(key,False)
            w.store.set_task_enabled('energy',True)
            c.automation.set_automation(True)
            c.automation._task_due['energy']=time.monotonic()+90
            received=[]
            async def overlay(payload):received.append(payload);return {}
            t.automation_overlay=overlay
            await c._sync_automation_overlay()
            value=received[-1]
            assert value['active'] and value['phase']=='waiting'
            assert '体力' in value['next_task']
            assert 88 < value['next_check_at']/1000-time.time() <= 90
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_update_download_runs_without_blocking_runtime_and_reports_progress(app,tmp_path,monkeypatch):
    import threading
    from package.plugin_manager import runtime as module
    async def run():
        c,s,t,w=make_controller(tmp_path)
        entered=threading.Event();release=threading.Event()
        monkeypatch.setattr(module.updater,'pending_update',lambda:None)
        monkeypatch.setattr(module.updater,'check',lambda **kwargs:{'version':'9.9','changed':[{}],'removed':[]})
        def prepare(plan,progress,cancel_event):
            entered.set();progress(5,10,'app.bin');release.wait(1)
        monkeypatch.setattr(module.updater,'prepare',prepare)
        try:
            await c._check_update_once()
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(.005)
            assert entered.is_set() and not c._update_job.done()
            await asyncio.sleep(.01)
            assert '50%' in w.action_label.text()
            release.set();await c._update_job
            assert c._update_checked and '自动安装' in w.action_label.text()
        finally:
            release.set();await c.shutdown();w.close()
    asyncio.run(run())


def test_update_failure_retries_and_handles_removal_only(app,tmp_path,monkeypatch):
    from package.plugin_manager import runtime as module
    async def run():
        c,s,t,w=make_controller(tmp_path);checks=[];downloads=[]
        monkeypatch.setattr(module.updater,'pending_update',lambda:None)
        def check(**kwargs):
            checks.append(1)
            if len(checks)==1:raise RuntimeError('offline')
            return {'version':'9.9','changed':[],'removed':['old.dll']}
        monkeypatch.setattr(module.updater,'check',check)
        monkeypatch.setattr(module.updater,'prepare',lambda plan,**kwargs:downloads.append(plan))
        try:
            await c._check_update_once();await c._update_job
            assert not c._update_checked and c._next_update_check>0
            await c._check_update_once();assert len(checks)==1
            c._next_update_check=0
            await c._check_update_once();await c._update_job
            assert c._update_checked and downloads[0]['removed']==['old.dll']
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_handshake_timeout_cleans_connection_and_next_attempt_recovers():
    async def run():
        from package.plugin_manager.transport import PluginTransport,CdpConnectionPending
        class SlowCdp(FakeCdp):
            fail=True
            closed=0
            async def close(self):
                self.closed+=1
                await super().close()
            async def send(self,method,params=None,**kw):
                if method=='Runtime.enable':
                    assert not transport.connected
                    if self.fail:raise TimeoutError()
                return await super().send(method,params,**kw)
        cdp=SlowCdp();transport=PluginTransport(cdp=cdp)
        with pytest.raises(CdpConnectionPending,match='Runtime.enable'):
            await transport.connect(62000)
        assert not transport.connected and not cdp.live and cdp.closed==1
        assert transport.port is None and not transport.contexts
        cdp.fail=False
        await transport.connect(62000)
        assert transport.connected and cdp.live and transport.port==62000
    asyncio.run(run())


def test_handshake_cancellation_closes_socket_and_is_not_swallowed():
    async def run():
        from package.plugin_manager.transport import PluginTransport
        class CancelCdp(FakeCdp):
            async def send(self,method,params=None,**kw):raise asyncio.CancelledError()
        cdp=CancelCdp();transport=PluginTransport(cdp=cdp)
        with pytest.raises(asyncio.CancelledError):await transport.connect(62000)
        assert not transport.connected and not cdp.live and transport.port is None
    asyncio.run(run())


def test_probe_timeout_pauses_daily_and_retains_operation_identity(app,tmp_path):
    async def run():
        c,s,t,w=make_controller(tmp_path)
        try:
            await ready(c,s)
            installed=c.state.installed
            c.automation.running=True
            async def timeout():raise TimeoutError()
            t.probe=timeout
            await c.poll()
            assert c.state.stop_operation and c.state.blocked
            assert c.state.blocked_session==installed
            assert c.state.installed==installed,'timeout must not imply an action was cancelled or a resident destroyed'
            assert '未响应' in w.connection_label.text()
        finally:
            await c.shutdown();w.close()
    asyncio.run(run())


def test_game_script_failures_preserve_error_objects_and_stack_without_spam(caplog):
    import logging
    from package.plugin_manager.transport import PluginTransport
    fake=FakeCdp();transport=PluginTransport(cdp=fake);transport.context_id=7
    stack={'callFrames':[{'functionName':'renderOverlay','url':'battle.js','lineNumber':12,'columnNumber':3}]}
    event={'params':{'executionContextId':7,'type':'error','args':[{'value':'[对战辅助]'},
        {'type':'object','subtype':'error','description':'TypeError: renderer invalid'}], 'stackTrace':stack}}
    with caplog.at_level(logging.ERROR,logger='plugin_manager'):
        fake.handlers['Runtime.consoleAPICalled'](event)
        fake.handlers['Runtime.consoleAPICalled'](event)
        fake.handlers['Runtime.consoleAPICalled']({'params':{**event['params'],'executionContextId':8}})
        fake.handlers['Runtime.exceptionThrown']({'params':{'exceptionDetails':{'executionContextId':7,
            'exception':{'description':'RangeError: bad geometry'},'stackTrace':stack}}})
        fake.handlers['Runtime.exceptionThrown']({'params':{'exceptionDetails':{'executionContextId':8,
            'exception':{'description':'other context failure'}}}})
    assert caplog.text.count('TypeError: renderer invalid')==1
    assert 'RangeError: bad geometry' in caplog.text and 'renderOverlay battle.js:13:4' in caplog.text
    assert 'other context failure' not in caplog.text


def test_battle_diagnostic_console_breadcrumb_is_persisted(caplog):
    import logging
    from package.plugin_manager.transport import PluginTransport
    fake=FakeCdp();transport=PluginTransport(cdp=fake);transport.context_id=7
    with caplog.at_level(logging.INFO,logger='plugin_manager'):
        fake.handlers['Runtime.consoleAPICalled']({'params':{'executionContextId':7,'type':'log',
            'args':[{'value':'[plugin.diagnostic]'},{'value':'{"stage":"heartbeat","time":13}'}]}})
    assert '战斗诊断' in caplog.text and 'heartbeat' in caplog.text


def test_zhongkui_runtime_publishes_live_status_and_marks_timeout_stale():
    from types import SimpleNamespace
    from package.plugin_manager.runtime import PluginRuntime
    published=[]
    class Transport:
        fail=False
        async def battle_assist_timing(self):return []
        async def battle_assist_status(self):
            if self.fail:raise TimeoutError()
            return {'active':True,'monsters':[{'name':'妖物甲','wave':2}]}
    transport=Transport()
    panel=SimpleNamespace(set_monster_status=lambda value,stale=False:published.append((value,stale)))
    fake=SimpleNamespace(transport=transport,_next_battle_timing=0,
        session=SimpleNamespace(engine_state={},stale=lambda epoch:False),
        state=SimpleNamespace(closing=False,installed='one'),window=SimpleNamespace(pages={'zhongkui':panel}))
    fake._publish_zhongkui=lambda value,stale=False:PluginRuntime._publish_zhongkui(fake,value,stale)
    fake._publish_battle_assist_timing=lambda rows:None
    async def run():
        await PluginRuntime._sync_battle_assist_timing(fake,{'battle_assist':{'enabled':True}})
        assert published[-1][0]['monsters'][0]['name']=='妖物甲' and not published[-1][1]
        fake._next_battle_timing=0;transport.fail=True
        await PluginRuntime._sync_battle_assist_timing(fake,{'battle_assist':{'enabled':True}})
        assert published[-1]==(None,True)
        await PluginRuntime._sync_battle_assist_timing(fake,{'battle_assist':{'enabled':False}})
        assert published[-1]==(None,False)
    asyncio.run(run())


def test_native_promise_object_error_preserves_error_code_without_getters(caplog):
    import logging
    from package.plugin_manager.transport import PluginTransport
    class Cdp(FakeCdp):
        async def send(self,method,params=None,**kwargs):
            assert method=='Runtime.getProperties' and params['ownProperties'] is True
            return {'result':{'result':[
                {'name':'errMsg','value':{'type':'string','value':'launch:fail session unavailable'}},
                {'name':'errno','value':{'type':'number','value':123}},
                {'name':'token','value':{'type':'string','value':'secret-never-log'}},
                {'name':'message','get':{'objectId':'getter'}}]}}
    async def run():
        t=PluginTransport(cdp=Cdp());t.context_id=7
        t._exception({'params':{'exceptionDetails':{'executionContextId':7,'text':'Uncaught (in promise) #<Object>',
            'exception':{'type':'object','objectId':'error-1'}}}})
        await asyncio.gather(*t._exception_tasks)
    with caplog.at_level(logging.ERROR,logger='plugin_manager'):asyncio.run(run())
    assert 'launch:fail session unavailable' in caplog.text and '123' in caplog.text
    assert 'secret-never-log' not in caplog.text
