import asyncio
import copy
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from package.plugin_manager.features import damage

class Panel:
    def __init__(self):self.message=self
    def __getattr__(self,name):return lambda *a,**k:None
class Transport:
    context_id='runtime'
    def __init__(self):self.fetches=0;self.count=1;self.hooked=2
    async def damage_status(self):
        return {'hooked':self.hooked,'sides':{'self':{'instanceId':1,'eventCount':self.count,'duration':self.count}},'pvpSamples':self.count}
    async def damage_snapshot(self):
        self.fetches+=1
        return {'self':{'instanceId':1,'battleType':26,'seed':1,'eventCount':self.count}}
def fixture():
    t=Transport();f=damage.DamageFeature(t,SimpleNamespace(closing=False,installed=True),Panel(),SimpleNamespace(snapshot=lambda:{}))
    f.summary=lambda data:'';f.hint=lambda data:'';f.status_text=lambda data:''
    return f,t


def test_zero_damage_initial_snapshot_is_reportable():
    from package.plugin_manager.damage_report.serialize import slim
    snapshot = {'status': 'captured', 'time': 0, 'attributes': {'1': 100}}
    data = {'self': {'battleType': 26, 'eventCount': 0, 'initialAttributes': snapshot}}
    assert damage.DamageFeature._has_data(data)
    assert slim(data, False)['initialAttributes'] == snapshot
    data['self']['initialAttributes'] = {'status': 'missed'}
    assert not damage.DamageFeature._has_data(data)


def test_diagnostics_are_preserved_and_logged(caplog):
    import json
    import logging
    from package.plugin_manager.damage_report.serialize import slim
    diag = {'version': '20261024.1', 'modules': {'subLifePatched': False},
            'counts': {'factor.skip.no_context.book': 100},
            'samples': [{'reason': 'factor.skip.no_context.book', 'skillId': 20}]}
    data = {'self': {'instanceId': 7, 'battleType': 20, 'eventCount': 100,
                     'factorRows': [], 'diagnostics': diag}}
    assert json.loads(json.dumps(slim(data, False)))['diagnostics'] == diag
    with caplog.at_level(logging.INFO, logger='plugin_manager'):
        damage.DamageFeature._log_diagnostics(data, '报告')
    assert '20261024.1' in caplog.text
    assert 'factor.skip.no_context.book' in caplog.text
    assert 'diagnostics' in caplog.text

def test_stop_failure_keeps_cleanup_pending_for_retry():
    async def run():
        f,t=fixture();f._injected=True;calls=[]
        async def stop():
            calls.append(True)
            if len(calls)==1:raise RuntimeError('temporary disconnection')
        t.damage_stop=stop
        await f.poll({'damage':{'enabled':False}})
        assert f._injected
        await f.poll({'damage':{'enabled':False}})
        assert not f._injected and len(calls)==2
    asyncio.run(run())


def test_unchanged_and_active_snapshots_are_throttled():
    async def run():
        f,t=fixture();await f.take();await f.take();assert t.fetches==1
        t.count=2;await f.take();assert t.fetches==1
        f._next_snapshot=0;await f.take();assert t.fetches==2
    asyncio.run(run())

def test_final_snapshot_and_report_run_off_event_loop(monkeypatch):
    main=threading.get_ident();saved=[]
    def writer(data,*args,**kwargs):
        assert threading.get_ident()!=main
        time.sleep(.04);saved.append(copy.deepcopy(data));return [Path('new-report.html')]
    monkeypatch.setattr(damage,'write_outputs',writer)
    async def run():
        f,t=fixture();await f.take();t.count=3;t.hooked=0
        task=asyncio.create_task(f.take());await asyncio.sleep(.01)
        assert not task.done(),'report rendering must not block asyncio loop'
        await task
        assert saved[0]['self']['eventCount']==3,'capture final events after World detach'
        await f.take();assert len(saved)==1 and t.fetches==2
    asyncio.run(run())

def test_no_duplicate_fetch_during_manual_refresh(monkeypatch):
    async def run():
        f,t=fixture();original=t.damage_snapshot;ready=asyncio.Event();release=asyncio.Event()
        async def snapshot():ready.set();await release.wait();return await original()
        t.damage_snapshot=snapshot
        task=asyncio.create_task(f.take());await ready.wait();await f.take(force=True)
        release.set();await task;assert t.fetches==1
    asyncio.run(run())

def test_failed_report_can_retry_without_retransferring(monkeypatch):
    writes=[]
    def writer(*args,**kwargs):
        writes.append(1)
        if len(writes)==1:raise OSError('test full disk')
        return [Path('new-report.html')]
    monkeypatch.setattr(damage,'write_outputs',writer)
    async def run():
        f,t=fixture();await f.take();t.hooked=0
        await f.take();assert not f._written
        await f.take();assert f._written and len(writes)==2 and t.fetches==1
    asyncio.run(run())


def test_only_pvp_snapshots_can_generate_reports(monkeypatch):
    saved=[]
    monkeypatch.setattr(damage,'write_outputs',lambda *a,**k:saved.append(a) or [Path('report.html')])
    async def run():
        f,t=fixture()
        for kind in [1,2,3,4,9,10,11,17,21,27,101,102,None]:
            data={'self':{'battleType':kind,'eventCount':10,'instanceId':1}}
            assert not f._has_data(data)
            assert not await f.write_report(data,'test')
        assert not saved
        for kind in [8,16,18,19,20,24,25,26]:
            data={'self':{'battleType':kind,'eventCount':10,'instanceId':1}}
            assert f._has_data(data)
            assert await f.write_report(data,'test')
        assert len(saved)==8
    asyncio.run(run())
