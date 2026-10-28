import asyncio
from types import SimpleNamespace
import pytest
from package.plugin_manager import wechat_launch as launch
from package.plugin_manager.wechat_native_launch import choose_control, click_control


@pytest.fixture(autouse=True)
def isolated_positions(monkeypatch,tmp_path):
    monkeypatch.setattr(launch.positions,'cache_path',lambda:tmp_path/'positions.json')
    from package.plugin_manager import wechat_native_launch as native
    monkeypatch.setattr(native,'_probe',native.NativeProbe())


def test_native_control_selection_requires_unique_target():
    controls=[{'label':'发现','screenCenter':{'x':100,'y':200}}]
    assert choose_control({'controls':controls},'发现') is controls[0]
    with pytest.raises(RuntimeError,match='0 个'):choose_control({'controls':controls},'小程序')
    controls.append({'label':'发现','screenCenter':{'x':300,'y':200}})
    with pytest.raises(RuntimeError,match='2 个'):choose_control({'controls':controls},'发现')


def test_native_click_rejects_foreign_foreground_before_input():
    user=SimpleNamespace(IsWindow=lambda h:True,GetForegroundWindow=lambda:99)
    with pytest.raises(RuntimeError,match='前台'):
        click_control(user,{'hwnd':'0x10'},{'screenCenter':{'x':100,'y':200}})


def test_native_click_rejects_moved_window_before_input():
    def rectangle(h,p):p._obj.right=100;p._obj.bottom=100;return True
    def origin(h,p):p._obj.x=20;p._obj.y=30;return True
    user=SimpleNamespace(IsWindow=lambda h:True,GetForegroundWindow=lambda:16,
        GetClientRect=rectangle,ClientToScreen=origin)
    snapshot={'hwnd':'0x10','origin':{'x':0,'y':0},'clientSize':{'width':100,'height':100}}
    with pytest.raises(RuntimeError,match='已变化'):
        click_control(user,snapshot,{'screenCenter':{'x':10,'y':20}})


def test_open_recent_page_needs_no_frida_or_image_navigation(monkeypatch):
    calls=[]
    async def recent(mode):calls.append(mode);return {'found':True}
    async def native(*args):raise AssertionError('must not attach unnecessarily')
    monkeypatch.setattr(launch,'_recent_ui',recent);monkeypatch.setattr(launch,'_native_ui',native)
    asyncio.run(launch.prepare_wechat_game())
    assert calls==['Probe']


def test_discover_uses_frida_position_then_text_entry(monkeypatch):
    calls=[];found=[False]
    async def recent(mode):calls.append(mode);return {'found':found[0]}
    async def native(mode,label=None,**kwargs):
        calls.append((mode,label))
        if mode=='Click':found[0]=True
        return {'controls':[{'label':'发现'}]}
    monkeypatch.setattr(launch,'_recent_ui',recent);monkeypatch.setattr(launch,'_native_ui',native)
    asyncio.run(launch.prepare_wechat_game())
    assert calls==['Probe',('Snapshot',None),('Click','发现'),('Snapshot',None),'Probe']


def test_unsupported_native_build_does_not_close_game(monkeypatch):
    calls=[]
    async def recent(mode):return {'found':False}
    async def native(mode,label=None):calls.append(mode);raise RuntimeError('Unsupported Weixin build')
    monkeypatch.setattr(launch,'_recent_ui',recent);monkeypatch.setattr(launch,'_native_ui',native)
    with pytest.raises(RuntimeError,match='Unsupported'):
        asyncio.run(launch.prepare_wechat_game())
    assert calls==['Snapshot']


def test_reopen_waits_for_close_hooks_and_checks_duplicate_before_click(monkeypatch):
    calls=[]
    async def prepare():calls.append('prepare')
    async def native(mode,label=None):
        calls.append(mode)
        return {'windows':[123] if calls.count('Status')>1 else []}
    async def recent(mode):calls.append(mode);return {'ok':True}
    async def hook():calls.append('hook')
    monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
    monkeypatch.setattr(launch,'_native_ui',native);monkeypatch.setattr(launch,'_recent_ui',recent)
    asyncio.run(launch.reopen_wechat_game(before_open=hook))
    assert calls==['prepare','Close','hook','prepare','Status','EntryOpen','Status']


def test_existing_game_never_gets_a_duplicate_click(monkeypatch):
    calls=[]
    async def prepare():calls.append('prepare')
    async def native(mode,label=None):calls.append(mode);return {'windows':[123]}
    async def recent(mode):raise AssertionError('must not click game')
    monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
    monkeypatch.setattr(launch,'_native_ui',native);monkeypatch.setattr(launch,'_recent_ui',recent)
    with pytest.raises(RuntimeError,match='已经存在'):asyncio.run(launch.open_wechat_game())
    assert calls==['prepare','Status']


def test_read_error_keeps_session_until_explicit_close(monkeypatch):
    from package.plugin_manager import wechat_native_launch as native
    import frida
    calls=[]
    def fail(*args):raise RuntimeError('profile rejected')
    script=SimpleNamespace(load=lambda:None,exports_sync=SimpleNamespace(snapshot=fail))
    session=SimpleNamespace(create_script=lambda source:script,detach=lambda:calls.append('detach'))
    monkeypatch.setattr(native,'user32',lambda:None)
    monkeypatch.setattr(native,'main_geometry',lambda user,pid:{'hwnd':'0x1'})
    monkeypatch.setattr(native.psutil,'process_iter',lambda attrs:[SimpleNamespace(pid=10,info={'name':'Weixin.exe','cmdline':[]})])
    monkeypatch.setattr(native.psutil,'Process',lambda pid:SimpleNamespace(create_time=lambda:123))
    monkeypatch.setattr(frida,'get_local_device',lambda:SimpleNamespace(attach=lambda pid:session))
    with pytest.raises(RuntimeError,match='profile rejected'):native.run('Scan')
    assert calls==[]
    native.close()
    assert calls==['detach']


def test_native_operations_do_not_spawn_another_helper(monkeypatch):
    from package.plugin_manager import wechat_native_launch as native
    calls=[]
    def run(mode,label,cache):calls.append(mode);return {'ok':True,'windows':[]}
    async def spawn(*args,**kwargs):raise AssertionError('native session belongs to plugin process')
    monkeypatch.setattr(native,'run',run)
    monkeypatch.setattr(launch.asyncio,'create_subprocess_exec',spawn)
    assert asyncio.run(launch._native_ui('Status'))['windows']==[]
    assert calls==['Status']


def test_startup_uses_native_path_and_never_closes_existing_game(monkeypatch):
    from package.plugin_manager.startup_launch import ensure_game_started
    calls=[]
    async def native(mode,label=None):calls.append(mode);return {'windows':[123]}
    monkeypatch.setattr(launch,'_native_ui',native)
    assert asyncio.run(ensure_game_started('微信')) is False
    assert calls==['Status']


def test_windowed_helper_writes_result_without_stdout(monkeypatch,tmp_path):
    import sys,json
    from package.plugin_manager import wechat_native_launch as native
    monkeypatch.setattr(native,'run',lambda mode,label:{'ok':True,'windows':[]})
    monkeypatch.setattr(sys,'stdout',None)
    result=tmp_path/'result.json'
    assert native.helper_main('Status',result_path=result)==0
    assert json.loads(result.read_text())=={'ok':True,'windows':[]}


def test_overlapping_native_probes_are_rejected_before_second_injection(monkeypatch):
    async def run():
        entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def probe(mode,label,cache):
            calls.append(mode);entered.set();await release.wait();return {'ok':True}
        monkeypatch.setattr(launch,'_native_ui_request',probe)
        first=asyncio.create_task(launch._native_ui('Scan'))
        await entered.wait()
        with pytest.raises(RuntimeError,match='暂不重复注入'):await launch._native_ui('Snapshot')
        release.set();await first
        assert calls==['Scan']
    asyncio.run(run())


def test_cancelled_native_probe_finishes_without_being_killed(monkeypatch):
    async def run():
        entered=asyncio.Event();release=asyncio.Event();finished=[]
        async def probe(mode,label,cache):
            entered.set();await release.wait();finished.append(True);return {'ok':True}
        monkeypatch.setattr(launch,'_native_ui_request',probe)
        outer=asyncio.create_task(launch._native_ui('Scan'));await entered.wait()
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):await outer
        with pytest.raises(RuntimeError,match='暂不重复注入'):await launch._native_ui('Scan')
        release.set();await launch._native_probe_task
        assert finished==[True]
    asyncio.run(run())


def test_native_probe_reuses_session_script_and_reconnects_only_when_invalid(monkeypatch):
    import frida
    from package.plugin_manager import wechat_native_launch as native
    calls=[];sessions=[]
    def attach(pid):
        calls.append(('attach',pid))
        script=SimpleNamespace(is_destroyed=False,
            load=lambda:calls.append('load'),unload=lambda:calls.append('unload'),
            exports_sync=SimpleNamespace(snapshot=lambda *args:{'hwnd':'0x10'}))
        session=SimpleNamespace(is_detached=False,create_script=lambda source:script,
            detach=lambda:calls.append('detach'),script=script)
        sessions.append(session);return session
    monkeypatch.setattr(frida,'get_local_device',lambda:SimpleNamespace(attach=attach))
    probe=native.NativeProbe()
    for _ in range(3):probe.snapshot(10,123,None,{})
    assert calls==[('attach',10),'load']
    sessions[-1].script.is_destroyed=True
    probe.snapshot(10,123,None,{})
    assert calls.count(('attach',10))==2
    probe.snapshot(11,456,None,{})
    assert calls.count(('attach',11))==1
    probe.close();assert calls.count('detach')==3


def test_failed_native_script_load_releases_partial_session(monkeypatch):
    import frida
    from package.plugin_manager import wechat_native_launch as native
    calls=[]
    def load():raise RuntimeError('load failed')
    script=SimpleNamespace(load=load,unload=lambda:calls.append('unload'))
    session=SimpleNamespace(create_script=lambda source:script,detach=lambda:calls.append('detach'))
    monkeypatch.setattr(frida,'get_local_device',lambda:SimpleNamespace(attach=lambda pid:session))
    probe=native.NativeProbe()
    with pytest.raises(RuntimeError,match='load failed'):probe.snapshot(10,123,None,{})
    assert calls==['unload','detach'] and probe.session is None


@pytest.mark.parametrize('minimized',[False,True])
def test_main_geometry_ignores_hidden_weixin_helper_and_keeps_minimized_main(minimized):
    from package.plugin_manager.wechat_native_launch import main_geometry,wechat_window_pids
    windows={100:dict(title='微信',visible=not minimized,iconic=minimized),
             200:dict(title='Weixin',visible=False,iconic=False)}
    def enum(callback,param):
        for hwnd in windows:callback(hwnd,param)
        return True
    def title(hwnd,buffer,size):buffer.value=windows[hwnd]['title'];return len(buffer.value)
    def owner(hwnd,pointer):pointer._obj.value=123;return 1
    def rect(hwnd,pointer):pointer._obj.right=900;pointer._obj.bottom=600;return True
    def origin(hwnd,pointer):pointer._obj.x=30;pointer._obj.y=40;return True
    def dpi(hwnd):return 96
    user=SimpleNamespace(EnumWindows=enum,GetWindowTextW=title,GetWindowThreadProcessId=owner,
        IsWindowVisible=lambda hwnd:windows[hwnd]['visible'],IsIconic=lambda hwnd:windows[hwnd]['iconic'],
        GetClientRect=rect,ClientToScreen=origin,GetDpiForWindow=dpi)
    assert wechat_window_pids(user)=={123}
    assert main_geometry(user,123)==dict(hwnd='0x64',origin=dict(x=30,y=40),
        clientSize=dict(width=900,height=600),scale=1)
    windows[200]['visible']=True
    with pytest.raises(RuntimeError,match='未唯一就绪'):main_geometry(user,123)


def test_click_revalidates_visible_control_before_input(monkeypatch):
    async def run():
        snapshot={'controls':[{'label':'发现'}]};calls=[]
        async def native(mode,label,**kwargs):
            calls.append(mode)
            if mode=='CachedClick':
                assert kwargs['cache'] is snapshot
                raise RuntimeError('window resized')
            return {'ok':True}
        monkeypatch.setattr(launch,'_native_ui',native)
        assert (await launch._click_native_control(snapshot,'发现'))['ok']
        assert calls==['Click']
    asyncio.run(run())


def test_discover_cell_navigation_stays_on_native_path(monkeypatch):
    async def run():
        snapshots=0;opened=False;clicks=[]
        async def native(mode,label=None,**kwargs):
            nonlocal snapshots,opened
            if mode=='Snapshot':
                snapshots+=1
                return {'controls':[{'label':'发现'}] if snapshots==1 else
                    [{'label':'小程序','type':'mmui::ExtensionDiscoverContentCell'}]}
            assert mode=='Click'
            clicks.append(label)
            if label=='小程序':opened=True
            return {'ok':True}
        async def recent(mode,**kwargs):
            assert mode in ('Probe','WaitPrepare'), 'must not fall back to unmatched UIA text navigation'
            return {'found':opened,'ok':True}
        async def sleep(seconds):pass
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        monkeypatch.setattr(launch.asyncio,'sleep',sleep)
        assert (await launch.prepare_wechat_game())['ok']
        assert clicks==['发现','小程序'] and snapshots==2
    asyncio.run(run())


def test_ready_probe_returns_same_validated_card_without_rescanning(monkeypatch):
    prepared={'ok':True,'found':True,'cache':{'runtimeId':[1,2]}}
    async def recent(mode):
        assert mode=='Probe'
        return prepared
    monkeypatch.setattr(launch,'_recent_ui',recent)
    assert asyncio.run(launch._prepare_native_entry()) is prepared


@pytest.mark.parametrize('page',['chat','discover','recent'])
def test_persisted_small_program_coordinate_never_selects_navigation(page,monkeypatch):
    async def run():
        cached={'native':{'controls':[{'label':'小程序'},{'label':'发现'}]}}
        state=[page];calls=[]
        async def native(mode,label=None,**kwargs):
            calls.append((mode,label))
            assert mode!='CachedClick', 'historical coordinates cannot establish visibility'
            if mode=='Snapshot':
                labels=['发现'] if state[0]=='chat' else ['发现','小程序']
                return {'controls':[{'label':x} for x in labels]}
            assert mode=='Click'
            if label=='发现':
                assert state[0]=='chat'
                state[0]='discover'
            else:
                assert state[0]=='discover', 'must open Discover before clicking small program'
                state[0]='recent'
            return {'ok':True}
        async def recent(mode,**kwargs):
            calls.append(mode)
            assert mode in ('Probe','WaitPrepare')
            if mode=='WaitPrepare':assert state[0]=='recent'
            return {'ok':True,'found':state[0]=='recent','cache':{}}
        monkeypatch.setattr(launch.positions,'load',lambda:cached)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        await launch._prepare_native_entry()
        clicks=[x[1] for x in calls if isinstance(x,tuple) and x[0]=='Click']
        assert clicks==({'chat':['发现','小程序'],'discover':['小程序'],'recent':[]}[page])
        assert calls[0]=='Probe'
        assert calls.count('WaitPrepare')==(page!='recent')
    asyncio.run(run())
