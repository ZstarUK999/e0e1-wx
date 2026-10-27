import asyncio
from types import SimpleNamespace
import pytest
from package.plugin_manager import wechat_launch as launch
from package.plugin_manager.wechat_native_launch import choose_control, click_control


@pytest.fixture(autouse=True)
def isolated_positions(monkeypatch,tmp_path):
    monkeypatch.setattr(launch.positions,'cache_path',lambda:tmp_path/'positions.json')


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
    assert calls==['Probe','EntryPrepare']


def test_discover_uses_frida_position_then_text_entry(monkeypatch):
    calls=[];found=[False]
    async def recent(mode):calls.append(mode);return {'found':found[0]}
    async def native(mode,label=None):
        calls.append((mode,label))
        if mode=='Click':found[0]=True
        return {'controls':[{'label':'发现'}]}
    monkeypatch.setattr(launch,'_recent_ui',recent);monkeypatch.setattr(launch,'_native_ui',native)
    asyncio.run(launch.prepare_wechat_game())
    assert calls==['Probe',('Snapshot',None),('Click','发现'),'Probe','EntryPrepare']


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


def test_frida_helper_detaches_on_probe_error(monkeypatch):
    from package.plugin_manager import wechat_native_launch as native
    import frida
    calls=[]
    def fail():raise RuntimeError('profile rejected')
    script=SimpleNamespace(load=lambda:None,exports_sync=SimpleNamespace(snapshot=fail))
    session=SimpleNamespace(create_script=lambda source:script,detach=lambda:calls.append('detach'))
    monkeypatch.setattr(native,'user32',lambda:None)
    monkeypatch.setattr(native.psutil,'process_iter',lambda attrs:[SimpleNamespace(pid=10,info={'name':'Weixin.exe','cmdline':[]})])
    monkeypatch.setattr(frida,'get_local_device',lambda:SimpleNamespace(attach=lambda pid:session))
    with pytest.raises(RuntimeError,match='profile rejected'):native.run('Snapshot')
    assert calls==['detach']


def test_native_helper_timeout_kills_child(monkeypatch):
    calls=[]
    class Child:
        returncode=None
        async def communicate(self):
            calls.append('communicate')
            if calls.count('communicate')==1:raise TimeoutError()
            return b'',b''
        def kill(self):calls.append('kill');self.returncode=-1
    async def spawn(*args,**kwargs):return Child()
    monkeypatch.setattr(launch.asyncio,'create_subprocess_exec',spawn)
    with pytest.raises(TimeoutError):asyncio.run(launch._native_ui('Snapshot'))
    assert calls==['communicate','kill','communicate']


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
