import asyncio
import os
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from package.daily_tasks.free_summon import FreeSummonTask
from package.daily_tasks.pet_hatch import PetHatchTask
from package.daily_tasks.scheduler import ExecutionUncertain
from package.plugin_manager.store import PluginConfigStore,default_config,validate_config
from package.plugin_manager.window import PluginWindow
from package.plugin_manager.reconnect import WechatReconnect

def context(ids=None):
    return SimpleNamespace(task=SimpleNamespace(params={'item_ids':ids or [400001,400004]}),stop_requested=lambda:False)

def test_free_summon_respects_cooldown_even_manual():
    class Game:
        def __init__(self):self.actions=0;self.remaining=120
        async def home(self):pass
        async def free_summon_state(self):return {'remaining_seconds':self.remaining}
        async def free_summon(self):self.actions+=1;return {'confirmed':True,'cooldown_seconds':28800}
    async def run():
        g=Game();task=FreeSummonTask(g)
        result=await task.run(context(),force_trigger=True);assert result.next_delay_seconds==120 and g.actions==0
        g.remaining=0;result=await task.run(context());assert result.next_delay_seconds==28800 and g.actions==1
    asyncio.run(run())

def test_pet_task_serial_claim_then_fill_and_unknown_stops():
    class Game:
        def __init__(self):self.ops=[]
        async def home(self):pass
        async def pet_hatch_state(self,ids):
            assert ids==[400001,400004]
            return [{'claim_slot':1},{'item_id':400004,'free_slot':1,'can_place':True},{'remaining_seconds':30}][len(self.ops)]
        async def pet_hatch_claim(self,slot):self.ops.append(('claim',slot));return {'confirmed':True}
        async def pet_hatch_start(self,id):self.ops.append(('start',id));return {'confirmed':True}
    async def run():
        g=Game();result=await PetHatchTask(g).run(context());assert g.ops==[('claim',1),('start',400004)]
        assert result.next_delay_seconds==30
        async def unknown(id):return {'confirmed':False}
        g=Game();g.pet_hatch_claim=unknown
        with pytest.raises(ExecutionUncertain):await PetHatchTask(g).run(context())
    asyncio.run(run())


def test_pet_task_fills_all_four_slots_and_eight_queue_positions():
    class Game:
        def __init__(self):self.placed=[]
        async def home(self):pass
        async def pet_hatch_state(self,ids):
            count=len(self.placed)
            return {'item_id':400004 if count<5 else 400001,'free_slot':max(0,4-count),
                    'can_place':count<12,'queue_count':max(0,count-4),'queue_capacity':8}
        async def pet_hatch_start(self,id):self.placed.append(id);return {'confirmed':True}
    async def run():
        g=Game();result=await PetHatchTask(g).run(context())
        assert len(g.placed)==12 and g.placed==[400004]*5+[400001]*7
        assert result.status=='success'
    asyncio.run(run())

def test_reconnect_timeout_once_disable_and_new_event():
    class Transport:
        def __init__(self):self.status={'kicked':False};self.events=[]
        async def wechat_reconnect_status(self,enabled):return self.status if enabled else {'kicked':False}
        async def wechat_restart_after_kick(self,event):self.events.append(event);return True
    async def run():
        t=Transport();clock=[0];r=WechatReconnect(t,clock=lambda:clock[0]);cfg={'wechat_reconnect':True,'reconnect_seconds':60}
        assert await r.poll(cfg) is None
        t.status={'kicked':True,'event':'one'};assert '60' in await r.poll(cfg)
        clock[0]=59;await r.poll(cfg);assert not t.events
        clock[0]=60;await r.poll(cfg);await r.poll(cfg);assert t.events==['one']
        assert await r.poll({**cfg,'wechat_reconnect':False}) is None
        t.status={'kicked':True,'event':'two'};await r.poll(cfg);clock[0]=120;await r.poll(cfg);assert t.events==['one','two']
    asyncio.run(run())

def test_new_settings_migrate_and_validate():
    config=default_config();assert len(config['daily']['tasks'])==12
    config['daily']['tasks'].pop('free_summon');config['daily']['tasks'].pop('pet_hatch')
    config['ui'].pop('wechat_reconnect');config['ui'].pop('reconnect_seconds')
    result=validate_config(config);assert not result['ui']['wechat_reconnect']
    assert not result['daily']['tasks']['free_summon']['enabled']
    for ids in [[10004],[400001,400001],['400001'],[{}]]:
        result['daily']['tasks']['pet_hatch']['params']['item_ids']=ids
        with pytest.raises(ValueError):validate_config(result)
    for seconds in [0,86401,True,'60']:
        bad=default_config();bad['ui']['reconnect_seconds']=seconds
        with pytest.raises(ValueError):validate_config(bad)

def test_gui_task_selection_and_reconnect_persistence(tmp_path):
    app=QApplication.instance() or QApplication([]);store=PluginConfigStore(tmp_path/'plugin.json');w=PluginWindow(store)
    assert 'free_summon' in w.task_panels and 'pet_hatch' in w.task_panels
    panel=w.task_panels['pet_hatch'];choices=panel.fields['params.item_ids']
    for i in range(choices.count()):
        if choices.item(i).data(Qt.ItemDataRole.UserRole) in (400001,400004):choices.item(i).setCheckState(Qt.CheckState.Checked)
    panel.save();assert set(store.snapshot()['daily']['tasks']['pet_hatch']['params']['item_ids'])=={400001,400004}
    glob=w.pages['global'];glob.reconnect_seconds.setValue(90);glob.wechat_reconnect.setChecked(True);glob.save()
    saved=PluginConfigStore(store.path).snapshot();assert saved['ui']['wechat_reconnect'] and saved['ui']['reconnect_seconds']==90
    w.deleteLater();app.processEvents()


def test_runtime_stops_tasks_for_kick_and_cancels_pending_reconnect(tmp_path):
    from tools.test_plugin_runtime import FakeTransport, FakeService
    from package.plugin_manager.runtime import PluginRuntime
    class Transport(FakeTransport):
        def __init__(self):
            super().__init__();self.context_id=7;self.connected=True;self.event='kick';self.restarts=[]
        async def wechat_reconnect_status(self,enabled):return {'kicked':True,'event':self.event} if enabled else {'kicked':False}
        async def wechat_restart_after_kick(self,event):self.restarts.append(event);return True
    async def run():
        app=QApplication.instance() or QApplication([]);store=PluginConfigStore(tmp_path/'runtime.json')
        store.set_wechat_reconnect(True,60);w=PluginWindow(store);t=Transport()
        runtime=PluginRuntime(w,service=FakeService(),transport=t,process_ready=lambda:True)
        clock=[0];runtime.wechat_reconnect.clock=lambda:clock[0]
        runtime.state.installed='one';runtime.automation.running=True
        try:
            await runtime.poll();assert not runtime.automation.running;assert runtime.state.stop_operation
            assert '顶号' in runtime.state.blocked and not t.restarts
            clock[0]=60;await runtime.poll();await runtime.poll();assert t.restarts==['kick']
            store.set_wechat_reconnect(False,60);await runtime.poll();assert not runtime.state.blocked
        finally:
            await runtime.shutdown();w.close();app.processEvents()
    asyncio.run(run())


def test_wechat_recent_launch_waits_for_close_and_hook_before_click():
    from package.plugin_manager.wechat_launch import reopen_wechat_game,prepare_wechat_game
    calls=[]
    async def runner(mode):calls.append(mode)
    async def hook():calls.append('hook-ready')
    async def run():
        await prepare_wechat_game(runner=runner)
        await reopen_wechat_game(runner=runner,before_open=hook)
    asyncio.run(run())
    assert calls==['Prepare','WaitClosed','hook-ready','Open']


def test_wechat_recent_launch_does_not_click_when_old_window_remains():
    from package.plugin_manager.wechat_launch import reopen_wechat_game
    calls=[]
    async def runner(mode):
        calls.append(mode)
        if mode=='WaitClosed':raise RuntimeError('old window remains')
    with pytest.raises(RuntimeError):asyncio.run(reopen_wechat_game(runner=runner))
    assert calls==['WaitClosed']


def test_wechat_exit_ack_required_before_external_launch(monkeypatch):
    from package.plugin_manager.transport import PluginTransport
    import package.plugin_manager.wechat_launch as launch
    from tools.test_plugin_runtime import FakeCdp
    opened=[]
    async def prepare(**kwargs):pass
    monkeypatch.setattr(launch,'prepare_wechat_game',prepare)
    async def reopen(**kwargs):opened.append(True)
    monkeypatch.setattr(launch,'reopen_wechat_game',reopen)
    async def run():
        transport=PluginTransport(cdp=FakeCdp());transport.connected=True;transport.context_id=7
        async def rejected(*args,**kwargs):return False
        transport._evaluate=rejected
        assert await transport.wechat_restart_after_kick('one') is False
        assert not opened
        async def accepted(*args,**kwargs):return True
        transport._evaluate=accepted
        assert await transport.wechat_restart_after_kick('one') is True
        assert opened==[True]
        async def lost(*args,**kwargs):raise TimeoutError()
        transport._evaluate=lost
        with pytest.raises(TimeoutError):await transport.wechat_restart_after_kick('one')
        assert opened==[True]
    asyncio.run(run())


def test_wechat_recent_entry_preflight_failure_never_exits_game(monkeypatch):
    from package.plugin_manager.transport import PluginTransport
    import package.plugin_manager.wechat_launch as launch
    from tools.test_plugin_runtime import FakeCdp
    calls=[]
    async def prepare(**kwargs):raise RuntimeError('recent entry not visible')
    monkeypatch.setattr(launch,'prepare_wechat_game',prepare)
    async def evaluate(*args,**kwargs):calls.append('exit')
    async def run():
        t=PluginTransport(cdp=FakeCdp());t.connected=True;t.context_id=7;t._evaluate=evaluate
        with pytest.raises(RuntimeError):await t.wechat_restart_after_kick('one')
    asyncio.run(run());assert not calls


def test_reopen_arms_hook_before_new_launch_and_holds_auto_retries():
    from package.plugin_manager.session import GameSession
    from package.plugin_manager.state import RuntimeState
    class Signal:
        def __init__(self):self.slots=[]
        def connect(self,f):self.slots.append(f)
        def disconnect(self,f):self.slots.remove(f)
        def emit(self,s):
            for f in list(self.slots):f(s)
    class Service:
        def __init__(self):self.state_changed=Signal();self.starts=0
        def snapshot(self):return {'frida':True,'miniapp':False}
        def start_debug(self,record):
            self.starts+=1
            self.state_changed.emit({'status':'starting','frida':False})
            self.state_changed.emit({'status':'running','frida':True})
    async def run():
        service=Service();session=GameSession(service,SimpleNamespace(),RuntimeState(),record={})
        await session.prepare_reopen(timeout=.1)
        for i in range(4):session.request_debug()
        assert service.starts==0 and not service.state_changed.slots
    asyncio.run(run())


def test_wechat_recent_launch_does_not_click_when_hook_is_unready():
    from package.plugin_manager.wechat_launch import reopen_wechat_game
    calls=[]
    async def runner(mode):calls.append(mode)
    async def hook():raise RuntimeError('hook not ready')
    with pytest.raises(RuntimeError):asyncio.run(reopen_wechat_game(runner=runner,before_open=hook))
    assert calls==['WaitClosed']


def test_old_sidebar_configuration_is_discarded_and_no_calibration_button_remains(tmp_path):
    import json
    from PySide6.QtWidgets import QPushButton
    app=QApplication.instance() or QApplication([])
    old=default_config();old['ui']['wechat_sidebar']={'x':30,'y':40,'width':900,'height':800,'window_class':'legacy'}
    path=tmp_path/'plugins.json';path.write_text(json.dumps(old),encoding='utf-8')
    store=PluginConfigStore(path)
    assert 'wechat_sidebar' not in store.snapshot()['ui']
    window=PluginWindow(store)
    assert window.findChild(QPushButton,'ui.wechat_sidebar.calibrate') is None
    window.deleteLater();app.processEvents()


def test_entry_failure_diagnostics_are_logged_without_legacy_calibration(monkeypatch,caplog):
    import logging
    import package.plugin_manager.wechat_launch as launch
    commands=[]
    class Process:
        returncode=1
        async def communicate(self):
            return b'{"ok":false,"message":"missing sidebar","diagnostics":{"stage":"open-sidebar","navigationMatches":0}}',b''
    async def create(*args,**kwargs):commands.append(args);return Process()
    monkeypatch.setattr(launch.asyncio,'create_subprocess_exec',create)
    with caplog.at_level(logging.ERROR,logger='plugin_manager'):
        with pytest.raises(RuntimeError,match='missing sidebar'):
            asyncio.run(launch._recent_ui('Prepare'))
    args=commands[0]
    assert not any(str(arg).startswith('-Sidebar') for arg in args)
    assert 'open-sidebar' in caplog.text and 'navigationMatches' in caplog.text


@pytest.mark.parametrize('info,delay',[
    ({'item_id':None,'remaining_seconds':None},1800),
    ({'item_id':None,'remaining_seconds':7200},1800),
    ({'item_id':None,'remaining_seconds':900},900),
    ({'item_id':400001,'can_place':False,'remaining_seconds':7200},7200),
])
def test_pet_waits_without_opening_ui_and_uses_completion_timer(info,delay):
    class Game:
        async def home(self):raise AssertionError('waiting must not navigate')
        async def pet_hatch_state(self,ids):return info
        async def pet_hatch_start(self,id):raise AssertionError('no available action')
        async def pet_hatch_claim(self,slot):raise AssertionError('no completed slot')
    result=asyncio.run(PetHatchTask(Game()).run(context()))
    assert result.status=='waiting' and result.next_delay_seconds==delay


def test_pet_shortage_still_claims_finished_slots_and_replenishment_resumes():
    class Game:
        def __init__(self):self.complete=True;self.stock=False;self.claimed=0;self.placed=0
        async def home(self):pass
        async def pet_hatch_state(self,ids):
            return {'claim_slot':1 if self.complete else 0,'item_id':400001 if self.stock else None,
                    'can_place':True,'remaining_seconds':None}
        async def pet_hatch_claim(self,slot):
            self.complete=False;self.claimed+=1;return {'confirmed':True}
        async def pet_hatch_start(self,id):
            self.stock=False;self.placed+=1;return {'confirmed':True}
    async def run():
        game=Game();task=PetHatchTask(game)
        result=await task.run(context())
        assert game.claimed==1 and game.placed==0 and result.next_delay_seconds==1800
        game.stock=True
        await task.run(context())
        assert game.placed==1
    asyncio.run(run())


def test_pet_claim_finishes_cleanup_before_returning_home():
    class Game:
        def __init__(self):self.ops=[];self.finished=False
        async def home(self):self.ops.append('home')
        async def pet_hatch_state(self,ids):
            self.ops.append('state')
            return {'claim_slot':0 if self.finished else 1,'item_id':None,'remaining_seconds':None}
        async def pet_hatch_claim(self,slot):
            self.ops.extend(['claim','close-pets','close-rewards']);self.finished=True
            return {'confirmed':True}
    async def run():
        game=Game();result=await PetHatchTask(game).run(context())
        assert result.status=='success'
        assert game.ops==['state','home','claim','close-pets','close-rewards','state','home']
    asyncio.run(run())


def test_startup_retry_reuses_the_debug_listener_during_hold_period():
    import time
    from package.plugin_manager.session import GameSession
    class Service:
        def snapshot(self):return {'frida':True}
        def start_debug(self,record):raise AssertionError('do not tear down the prepared listener')
    session=GameSession(Service(),SimpleNamespace(),SimpleNamespace(closing=False),record={})
    session._started=True;session._next_debug_retry=time.monotonic()-60
    asyncio.run(session.prepare_reopen())


def test_free_summon_cooldown_check_never_navigates():
    class Game:
        async def home(self):raise AssertionError('cooldown checks are passive')
        async def free_summon_state(self):return {'remaining_seconds':120}
        async def free_summon(self):raise AssertionError('cooldown must not claim')
    result=asyncio.run(FreeSummonTask(Game()).run(context()))
    assert result.status=='waiting' and result.next_delay_seconds==120
