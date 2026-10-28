import asyncio
import json
from types import SimpleNamespace
import pytest
from package.plugin_manager import wechat_launch as launch
from package.plugin_manager.wechat_ui_worker import RecentUiWorker


def test_ui_worker_reuses_one_process_for_navigation_and_final_validation(monkeypatch):
    async def run():
        spawns=[];sent=[];responses=[{'ready':True},{'ok':True,'found':True},{'ok':True,'cached':True}]
        async def read():return (json.dumps(responses.pop(0))+'\n').encode()
        process=SimpleNamespace(returncode=None)
        def write(data):sent.append(json.loads(data))
        def close():process.returncode=0
        async def wait():return process.returncode
        async def drain():pass
        process.stdin=SimpleNamespace(write=write,drain=drain,close=close)
        process.stdout=SimpleNamespace(readline=read);process.wait=wait
        async def spawn(*args,**kwargs):spawns.append(args);return process
        monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
        worker=RecentUiWorker()
        assert (await worker.request('Probe'))['found']
        assert (await worker.request('CachedPrepare','entry.json'))['cached']
        assert len(spawns)==1 and len(sent)==2 and '-Worker' in spawns[0]
        await worker.close()
        assert process.returncode==0 and worker.process is None
    asyncio.run(run())


def test_ui_worker_timeout_does_not_replay_click(monkeypatch):
    async def run():
        sent=[];reads=[0];process=SimpleNamespace(returncode=None)
        async def read():
            reads[0]+=1
            if reads[0]==1:return b'{"ready":true}\n'
            raise TimeoutError()
        def write(data):sent.append(json.loads(data))
        def close():process.returncode=0
        async def wait():return 0
        async def drain():pass
        process.stdin=SimpleNamespace(write=write,drain=drain,close=close)
        process.stdout=SimpleNamespace(readline=read);process.wait=wait
        async def spawn(*args,**kwargs):return process
        monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
        worker=RecentUiWorker()
        with pytest.raises(TimeoutError):await worker.request('CachedOpen','entry.json')
        assert [r['mode'] for r in sent]==['CachedOpen']
        assert worker.process is None
    asyncio.run(run())


def test_debug_hooks_and_navigation_prepare_concurrently(monkeypatch):
    async def run():
        nav=asyncio.Event();hook=asyncio.Event();ticket={'cache':{'x':10}}
        async def prepare():nav.set();await hook.wait();return ticket
        async def debug():hook.set();await nav.wait()
        monkeypatch.setattr(launch,'prepare_wechat_game',prepare)
        assert await asyncio.wait_for(launch.prepare_wechat_start(debug),timeout=1) is ticket
    asyncio.run(run())


def test_failed_debug_preparation_cancels_navigation_before_launch(monkeypatch):
    async def run():
        stopped=[]
        async def prepare():
            try:await asyncio.Event().wait()
            finally:stopped.append(True)
        async def debug():raise RuntimeError('hook failed')
        monkeypatch.setattr(launch,'prepare_wechat_game',prepare)
        with pytest.raises(RuntimeError,match='hook failed'):await launch.prepare_wechat_start(debug)
        assert stopped==[True]
    asyncio.run(run())


def test_prepared_entry_skips_duplicate_navigation_before_click(monkeypatch):
    async def run():
        calls=[];ticket={'cache':{'x':20}}
        async def prepare(**kwargs):raise AssertionError('must not prepare twice')
        async def native(mode,*args,**kwargs):calls.append(mode);return {'windows':[]}
        async def recent(mode,**kwargs):
            calls.append(mode);assert kwargs['entry_cache'] is ticket['cache']
        async def wait():return True
        monkeypatch.setattr(launch.positions,'load',lambda:{})
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'_recent_ui',recent)
        monkeypatch.setattr(launch,'_wait_game_window',wait)
        await launch.open_wechat_game(prepared=ticket)
        assert calls==['Status','CachedOpen']
    asyncio.run(run())


def test_reopen_reuses_entry_prepared_before_closing_game(monkeypatch):
    async def run():
        calls=[];ticket={'cache':{'x':20}}
        async def prepare(**kwargs):raise AssertionError('entry already prepared')
        async def native(mode,*args,**kwargs):calls.append(mode)
        async def debug():calls.append('hook')
        async def opened(**kwargs):calls.append('open');assert kwargs['prepared'] is ticket
        monkeypatch.setattr(launch,'_prepare_native_entry',prepare)
        monkeypatch.setattr(launch,'_native_ui',native)
        monkeypatch.setattr(launch,'open_wechat_game',opened)
        await launch.reopen_wechat_game(before_open=debug,prepared=ticket)
        assert calls==['Close','hook','open']
    asyncio.run(run())
