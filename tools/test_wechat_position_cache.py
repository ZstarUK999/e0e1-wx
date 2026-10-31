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


def test_cached_prepare_uses_only_saved_entry_without_background_tasks(monkeypatch):
    async def run():
        cache.save('entry',ENTRY);calls=[]
        async def recent(mode,**kwargs):
            assert mode=='CachedPrepare' and kwargs['entry_cache']==ENTRY
            calls.append(mode);return {'ok':True}
        async def native(*args,**kwargs):raise AssertionError('cached entry needs no scan')
        monkeypatch.setattr(launch,'_recent_ui',recent)
        monkeypatch.setattr(launch,'_native_ui',native)
        before=set(asyncio.all_tasks())
        await launch._prepare_native_entry()
        assert calls==['CachedPrepare'] and set(asyncio.all_tasks())==before
    asyncio.run(run())


def test_failed_cached_launch_uses_new_scan_and_only_one_retry(monkeypatch):
    async def run():
        cache.save('entry',ENTRY);calls=[];waits=[False,True]
        async def prepare(**kwargs):
            calls.append(('prepare',kwargs.get('force_scan',False)))
            if kwargs.get('force_scan'):cache.save('entry',dict(ENTRY,x=80))
        async def native(mode,label=None):calls.append(mode);return {'windows':[]}
        async def recent(mode,**kwargs):
            calls.append(mode)
            if mode=='CachedOpen':assert kwargs['entry_cache']['x']==30
            elif mode=='EntryOpen':assert cache.load()['entry']['x']==80
        async def wait():return waits.pop(0)
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        monkeypatch.setattr(launch,'_wait_game_window',wait)
        await launch.open_wechat_game()
        assert calls.count('CachedOpen')==1 and calls.count('EntryOpen')==1
        assert calls.index(('prepare',True))<calls.index('EntryOpen')
    asyncio.run(run())


def test_late_game_window_prevents_retry_after_cached_failure(monkeypatch):
    async def run():
        cache.save('entry',ENTRY);calls=[];checks=[[],[999]]
        async def prepare(**kwargs):calls.append('prepare')
        async def native(mode,label=None):return {'windows':checks.pop(0)}
        async def recent(mode,**kwargs):calls.append(mode);raise RuntimeError('ack lost')
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        await launch.open_wechat_game()
        assert calls==['prepare','CachedOpen']
    asyncio.run(run())


def test_two_failed_launches_end_this_round(monkeypatch):
    async def run():
        cache.save('entry',ENTRY);calls=[]
        async def prepare(**kwargs):return None
        async def native(*args):return {'windows':[]}
        async def recent(mode,**kwargs):calls.append(mode)
        async def wait():return False
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        monkeypatch.setattr(launch,'_wait_game_window',wait)
        with pytest.raises(RuntimeError,match='两次尝试'):await launch.open_wechat_game()
        assert calls==['CachedOpen','EntryOpen']
    asyncio.run(run())


@pytest.mark.parametrize('mode',['CachedClick','CachedEntryClick'])
def test_cached_click_uses_saved_coordinates_without_frida_and_follows_moved_window(monkeypatch,mode):
    from package.plugin_manager import wechat_native_launch as native
    user=SimpleNamespace(IsIconic=lambda h:False,SetForegroundWindow=lambda h:None)
    monkeypatch.setattr(native,'user32',lambda:user)
    process=SimpleNamespace(pid=10,info={'name':'Weixin.exe','cmdline':[]},name=lambda:'Weixin.exe',create_time=lambda:12)
    monkeypatch.setattr(native.psutil,'Process',lambda pid:process)
    monkeypatch.setattr(native.psutil,'process_iter',lambda attrs:[process])
    monkeypatch.setattr(native,'wechat_window_pids',lambda user:{10})
    geometry=dict(hwnd='0x10',origin={'x':50,'y':60},clientSize=NATIVE['clientSize'],scale=1.5)
    monkeypatch.setattr(native,'main_geometry',lambda user,pid:geometry)
    monkeypatch.setattr(native.time,'sleep',lambda t:None)
    def scan(*args):raise AssertionError('cached click must not scan')
    monkeypatch.setattr(native,'_probe',SimpleNamespace(snapshot=scan))
    clicks=[];monkeypatch.setattr(native,'click_control',lambda u,s,c:clicks.append(c['screenCenter']))
    entry=dict(ENTRY,processStart=str(621355968000000000+120000000))
    native.run(mode,'发现' if mode=='CachedClick' else '遗弃之地',cache=NATIVE if mode=='CachedClick' else entry)
    assert clicks==[{'x':80,'y':100}]


def test_cached_navigation_ticket_defers_all_clicks_and_scans(monkeypatch):
    native=dict(NATIVE,controls=NATIVE['controls']+[dict(label='小程序',screenCenter={'x':50,'y':60})])
    cache.save('native',native);cache.save('entry',ENTRY)
    async def unexpected(*args,**kwargs):raise AssertionError('must defer work until open')
    monkeypatch.setattr(launch,'_native_ui',unexpected)
    monkeypatch.setattr(launch,'_recent_ui',unexpected)
    result=asyncio.run(launch._prepare_native_entry())
    assert result['cached_navigation'] and result['cache']==ENTRY


def test_cached_click_rejects_changed_size_without_scanning_or_clicking(monkeypatch):
    from package.plugin_manager import wechat_native_launch as native
    user=SimpleNamespace(IsIconic=lambda h:False,SetForegroundWindow=lambda h:None)
    monkeypatch.setattr(native,'user32',lambda:user)
    monkeypatch.setattr(native.psutil,'Process',lambda pid:SimpleNamespace(pid=10,name=lambda:'Weixin.exe',create_time=lambda:12))
    monkeypatch.setattr(native,'main_geometry',lambda u,p:dict(hwnd='0x10',origin=NATIVE['origin'],clientSize={'width':200,'height':100},scale=1.5))
    monkeypatch.setattr(native.time,'sleep',lambda t:None)
    def unexpected(*args):raise AssertionError('must not click or scan invalid geometry')
    monkeypatch.setattr(native,'click_control',unexpected)
    monkeypatch.setattr(native,'_probe',SimpleNamespace(snapshot=unexpected))
    with pytest.raises(RuntimeError,match='尺寸已变化'):native.run('CachedClick','发现',cache=NATIVE)


def test_late_window_after_cached_navigation_failure_prevents_scan_and_second_launch(monkeypatch):
    async def run():
        checks=iter([[],[],[123]])
        async def native(mode,label=None,**kwargs):
            if mode=='Status':return {'windows':next(checks)}
            assert mode=='CachedClick';raise RuntimeError('acknowledgement lost')
        async def unexpected(*args,**kwargs):raise AssertionError('must not retry an opened game')
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_prepare_native_entry',unexpected)
        monkeypatch.setattr(launch,'_recent_ui',unexpected)
        await launch.open_wechat_game(prepared={'cached_navigation':True,'native_cache':NATIVE,'cache':ENTRY})
    asyncio.run(run())


@pytest.mark.parametrize('opened',[True,False])
def test_cached_navigation_is_attempted_before_scan_and_failed_launch_falls_back_once(monkeypatch,opened):
    async def run():
        calls=[]
        ticket={'cache':ENTRY,'native_cache':NATIVE,'cached_navigation':True}
        async def native(mode,label=None,**kwargs):
            calls.append((mode,label))
            return {'windows':[]}
        async def recent(mode,**kwargs):calls.append(mode)
        async def prepare(**kwargs):assert kwargs=={'force_scan':True};calls.append('scan')
        waits=iter([opened,True])
        async def wait(timeout=15):calls.append('wait');return next(waits)
        async def pause(delay):pass
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_wait_game_window',wait)
        monkeypatch.setattr(launch.asyncio,'sleep',pause)
        await launch.open_wechat_game(prepared=ticket)
        inputs=[c for c in calls if isinstance(c,tuple) and c[0]!='Status']
        assert inputs==[('CachedClick','发现'),('CachedEntryClick','遗弃之地'),
                       ('CachedClick','小程序'),('CachedEntryClick','遗弃之地')]
        if opened:assert 'scan' not in calls and 'EntryOpen' not in calls
        else:
            assert calls.count('scan')==calls.count('EntryOpen')==1
            assert calls.index('wait')<calls.index('scan')<calls.index('EntryOpen')
    asyncio.run(run())


@pytest.mark.parametrize('page_visible',[True,False])
def test_game_position_is_tried_before_toggling_mini_program_page(monkeypatch,page_visible):
    async def run():
        page=[page_visible];windows=[];inputs=[];waits=[]
        async def native(mode,label=None,**kwargs):
            if mode=='Status':return {'windows':windows[:]}
            inputs.append((mode,label))
            if label=='小程序':page[0]=not page[0]
            if mode=='CachedEntryClick' and page[0]:windows.append(123)
            return {'ok':True}
        async def wait(timeout=15):waits.append(timeout);return bool(windows)
        async def pause(delay):pass
        async def unexpected(*args,**kwargs):raise AssertionError('cached launch must succeed without scanning')
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_wait_game_window',wait)
        monkeypatch.setattr(launch.asyncio,'sleep',pause)
        monkeypatch.setattr(launch,'_prepare_native_entry',unexpected)
        monkeypatch.setattr(launch,'_recent_ui',unexpected)
        await launch.open_wechat_game(prepared={'cached_navigation':True,'native_cache':NATIVE,'cache':ENTRY})
        assert inputs[:2]==[('CachedClick','发现'),('CachedEntryClick','遗弃之地')]
        if page_visible:
            assert inputs[2:]==[('CachedClick','小程序')] and waits==[]
        else:
            assert inputs[2:]==[('CachedClick','小程序'),('CachedEntryClick','遗弃之地')]
            assert waits==[15]
        assert windows==[123]
    asyncio.run(run())


def test_native_cache_keeps_navigation_buttons_across_pages_and_translates_window_move():
    initial=dict(NATIVE,controls=NATIVE['controls']+[dict(label='小程序',screenCenter={'x':50,'y':60})])
    cache.save('native',initial)
    cache.save('native',dict(NATIVE,origin={'x':10,'y':20}))
    controls={c['label']:c for c in cache.load()['native']['controls']}
    assert controls['小程序']['screenCenter']=={'x':60,'y':80}
    assert controls['发现']['screenCenter']=={'x':30,'y':40}


def test_cache_write_failure_does_not_stop_positioning(monkeypatch):
    def fail(*args):raise OSError('disk unavailable')
    monkeypatch.setattr(cache,'save',fail)
    launch._save_position('entry',ENTRY)


def test_background_native_scan_does_not_focus_or_click(monkeypatch):
    import frida
    from package.plugin_manager import wechat_native_launch as native
    calls=[]
    script=SimpleNamespace(load=lambda:None,exports_sync=SimpleNamespace(snapshot=lambda *args:{'hwnd':'0x10','controls':[]}))
    session=SimpleNamespace(create_script=lambda source:script,detach=lambda:calls.append('detach'))
    monkeypatch.setattr(native,'user32',lambda:None)
    monkeypatch.setattr(native,'main_geometry',lambda user,pid:{'hwnd':'0x10'})
    monkeypatch.setattr(native.psutil,'process_iter',lambda attrs:[SimpleNamespace(pid=10,info={'name':'Weixin.exe','cmdline':[]})])
    monkeypatch.setattr(native.psutil,'Process',lambda pid:SimpleNamespace(create_time=lambda:123))
    monkeypatch.setattr(frida,'get_local_device',lambda:SimpleNamespace(attach=lambda pid:session))
    monkeypatch.setattr(native,'_probe',native.NativeProbe())
    result=native.run('Scan')
    assert result['ok'] and result['processCreatedAt']==123 and calls==[]
    native.close();assert calls==['detach']


def test_cached_native_position_rejects_restarted_wechat(monkeypatch):
    from package.plugin_manager import wechat_native_launch as native
    monkeypatch.setattr(native,'user32',lambda:None)
    monkeypatch.setattr(native.psutil,'Process',lambda pid:SimpleNamespace(name=lambda:'Weixin.exe',create_time=lambda:99))
    with pytest.raises(RuntimeError,match='进程已变化'):native.run('CachedClick','发现',cache=NATIVE)


@pytest.mark.parametrize('mode',['Snapshot','Click'])
def test_foreground_native_lookup_saves_its_positions_immediately(monkeypatch,mode):
    from package.plugin_manager import wechat_native_launch as native
    def run(*args):
        return dict(NATIVE,ok=True) if mode=='Snapshot' else dict(ok=True,snapshot=NATIVE,control=NATIVE['controls'][0])
    monkeypatch.setattr(native,'run',run)
    asyncio.run(launch._native_ui(mode,'发现' if mode=='Click' else None))
    saved=cache.load()['native']
    assert saved['controls'][0]['screenCenter']==NATIVE['controls'][0]['screenCenter']
    assert saved['processCreatedAt']==NATIVE['processCreatedAt']
