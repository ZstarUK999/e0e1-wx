import asyncio
import json
from types import SimpleNamespace
import pytest
from package.plugin_manager import wechat_launch as launch
from package.plugin_manager import wechat_position_cache as cache

ENTRY=dict(pid=10,processStart='123',hwnd='16',width=100,height=100,dpi=144,
           x=30,y=40,runtimeId=[1,2,3])
NATIVE=dict(pid=10,processCreatedAt=12,hwnd='0x10',origin={'x':0,'y':0},
    clientSize={'width':100,'height':100},scaleX=1.5,scaleY=1.5,version='4.1.15.55',
    root='not-persisted',controls=[dict(label='发现',type='mmui::XTabBarItem',
        object='not-persisted',screenCenter={'x':30,'y':40},localRect={})])


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch,tmp_path):
    monkeypatch.setattr(cache,'cache_path',lambda:tmp_path/'positions.json')


def test_positions_persist_and_merge_without_native_pointers():
    cache.save('native',NATIVE);cache.save('entry',ENTRY)
    loaded=cache.load()
    assert loaded['entry']==ENTRY
    assert loaded['native']['controls'][0]['screenCenter']=={'x':30,'y':40}
    assert 'not-persisted' not in cache.cache_path().read_text(encoding='utf-8')
    cache.save('native',dict(NATIVE,origin={'x':50,'y':60}))
    assert cache.load()['entry']==ENTRY


def test_corrupt_cache_is_ignored():
    cache.cache_path().write_text('{broken')
    assert cache.load()=={}
    cache.cache_path().write_text(json.dumps({'schema':1,'entry':'bad'}))
    assert 'entry' not in cache.load()


def test_cache_preparation_starts_one_background_refresh_without_waiting(monkeypatch):
    async def run():
        cache.save('entry',ENTRY);calls=[];gate=asyncio.Event()
        async def refresh():calls.append('scan-start');await gate.wait();calls.append('scan-done')
        async def recent(mode,**kwargs):
            assert mode=='CachedPrepare';assert kwargs['entry_cache']==ENTRY
            calls.append('cached');return {'ok':True}
        monkeypatch.setattr(launch,'_refresh_positions',refresh)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        await launch._prepare_native_entry()
        first=launch._position_refresh
        await launch._prepare_native_entry()
        assert launch._position_refresh is first and not first.done()
        await asyncio.sleep(0)
        assert calls.count('scan-start')==1 and 'scan-done' not in calls
        gate.set();await first
        assert calls[-1]=='scan-done'
    asyncio.run(run())


def test_failed_cached_launch_uses_new_scan_and_only_one_retry(monkeypatch):
    async def run():
        cache.save('entry',ENTRY);calls=[];waits=[False,True]
        async def refresh():cache.save('entry',dict(ENTRY,x=80));calls.append('refreshed')
        async def prepare(**kwargs):calls.append(('prepare',kwargs.get('force_scan',False)))
        async def native(mode,label=None):calls.append(mode);return {'windows':[]}
        async def recent(mode,**kwargs):
            calls.append(mode)
            if mode=='CachedOpen':assert kwargs['entry_cache']['x']==30
            elif mode=='EntryOpen':assert cache.load()['entry']['x']==80
        async def wait():return waits.pop(0)
        monkeypatch.setattr(launch,'_refresh_positions',refresh)
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        monkeypatch.setattr(launch,'_wait_game_window',wait)
        await launch.open_wechat_game()
        assert calls.count('CachedOpen')==1 and calls.count('EntryOpen')==1
        assert calls.index('refreshed')<calls.index(('prepare',True))<calls.index('EntryOpen')
    asyncio.run(run())


def test_late_game_window_prevents_retry_after_cached_failure(monkeypatch):
    async def run():
        cache.save('entry',ENTRY);calls=[];checks=[[],[999]]
        async def refresh():return None
        async def prepare(**kwargs):calls.append('prepare')
        async def native(mode,label=None):return {'windows':checks.pop(0)}
        async def recent(mode,**kwargs):calls.append(mode);raise RuntimeError('ack lost')
        monkeypatch.setattr(launch,'_refresh_positions',refresh)
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        await launch.open_wechat_game()
        assert calls==['prepare','CachedOpen']
    asyncio.run(run())


def test_two_failed_launches_end_this_round(monkeypatch):
    async def run():
        cache.save('entry',ENTRY);calls=[]
        async def refresh():return None
        async def prepare(**kwargs):return None
        async def native(*args):return {'windows':[]}
        async def recent(mode,**kwargs):calls.append(mode)
        async def wait():return False
        monkeypatch.setattr(launch,'_refresh_positions',refresh)
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        monkeypatch.setattr(launch,'_wait_game_window',wait)
        with pytest.raises(RuntimeError,match='两次尝试'):await launch.open_wechat_game()
        assert calls==['CachedOpen','EntryOpen']
    asyncio.run(run())


def test_cancel_refresh_finishes_its_cleanup(monkeypatch):
    async def run():
        cleaned=[]
        async def refresh():
            try:await asyncio.Event().wait()
            finally:cleaned.append(True)
        monkeypatch.setattr(launch,'_refresh_positions',refresh)
        launch._start_position_refresh();await asyncio.sleep(0)
        await launch.cancel_position_refresh()
        assert cleaned==[True] and launch._position_refresh is None
    asyncio.run(run())


def test_cached_native_click_translates_window_movement_without_frida(monkeypatch):
    from package.plugin_manager import wechat_native_launch as native
    def rect(h,p):p._obj.right=100;p._obj.bottom=100;return True
    def origin(h,p):p._obj.x=200;p._obj.y=300;return True
    def pid(h,p):p._obj.value=10
    def dpi(h):return 144
    user=SimpleNamespace(GetWindowThreadProcessId=pid,IsIconic=lambda h:False,
        SetForegroundWindow=lambda h:None,GetClientRect=rect,ClientToScreen=origin,GetDpiForWindow=dpi)
    monkeypatch.setattr(native,'user32',lambda:user)
    monkeypatch.setattr(native.psutil,'Process',lambda pid:SimpleNamespace(pid=10,name=lambda:'Weixin.exe',create_time=lambda:12))
    monkeypatch.setattr(native.time,'sleep',lambda t:None)
    clicks=[];monkeypatch.setattr(native,'click_control',lambda u,s,c:clicks.append(c['screenCenter']))
    result=native.run('CachedClick','发现',cache=NATIVE)
    assert result['cached'] and clicks==[{'x':230,'y':340}]


def test_cache_write_failure_does_not_stop_positioning(monkeypatch):
    def fail(*args):raise OSError('disk unavailable')
    monkeypatch.setattr(cache,'save',fail)
    launch._save_position('entry',ENTRY)


def test_background_native_scan_does_not_focus_or_click(monkeypatch):
    import frida
    from package.plugin_manager import wechat_native_launch as native
    calls=[]
    script=SimpleNamespace(load=lambda:None,exports_sync=SimpleNamespace(snapshot=lambda:{'hwnd':'0x10','controls':[]}))
    session=SimpleNamespace(create_script=lambda source:script,detach=lambda:calls.append('detach'))
    monkeypatch.setattr(native,'user32',lambda:None)
    monkeypatch.setattr(native.psutil,'process_iter',lambda attrs:[SimpleNamespace(pid=10,info={'name':'Weixin.exe','cmdline':[]})])
    monkeypatch.setattr(native.psutil,'Process',lambda pid:SimpleNamespace(create_time=lambda:123))
    monkeypatch.setattr(frida,'get_local_device',lambda:SimpleNamespace(attach=lambda pid:session))
    result=native.run('Scan')
    assert result['ok'] and result['processCreatedAt']==123 and calls==['detach']


def test_cached_native_position_rejects_restarted_wechat(monkeypatch):
    from package.plugin_manager import wechat_native_launch as native
    monkeypatch.setattr(native,'user32',lambda:None)
    monkeypatch.setattr(native.psutil,'Process',lambda pid:SimpleNamespace(name=lambda:'Weixin.exe',create_time=lambda:99))
    with pytest.raises(RuntimeError,match='进程已变化'):native.run('CachedClick','发现',cache=NATIVE)
