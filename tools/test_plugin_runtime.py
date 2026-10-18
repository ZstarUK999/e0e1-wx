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
        elif 'createEnergyRuntime' in expression:
            self.resident='injected';value={'resident_id':'injected','capabilities':['energy']}
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
            if method=='Runtime.evaluate' and 'createEnergyRuntime' in params['expression']:
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
        assert sum('createEnergyRuntime' in p.get('expression','') for method,p in fake.messages if p)==1
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
            if method=='Runtime.evaluate' and 'const r=globalThis.__e0e1PluginRuntime' in params['expression']:
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
        source=next(params['expression'] for method,params in fake.messages if params and 'createEnergyRuntime' in params.get('expression',''))
        # 用Node假运行api，仅验证生成的驻留容器，不操作任何游戏数据。
        split=source.index('const id =')
        source=source[:source.index('function createEnergyRuntime')]+'function createEnergyRuntime(g){return {dispatch:async()=>await g.release};}\n'+source[split:]
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
            if method=='Runtime.evaluate' and 'const r=globalThis.__e0e1PluginRuntime' in params['expression']:
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
            if method=='Runtime.evaluate' and 'const r=globalThis.__e0e1PluginRuntime' in params['expression']:
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
