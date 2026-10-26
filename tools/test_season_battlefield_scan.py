import asyncio
from types import SimpleNamespace

from tools.test_season_legion_statistics import setup, battle
from package.plugin_manager.season_insight import SeasonInsightFeature
from package.plugin_manager.season_legion_statistics import scan_battlefield


class GraphTransport:
    def __init__(self):
        self.calls=[]
        self.fail=False

    async def season_insight(self,op,args):
        self.calls.append((op,dict(args)))
        if op=='legion_roster':return dict(members=[],memberNum=1)
        if op=='statistics':return dict(rows=[dict(id=100005,name='本阴司',score=50,killRoleNum=1,killGuardNum=2,dieNum=0)])
        if op=='guard_count':return dict(total=3)
        if op=='reports':
            pid=args['roleId']
            if pid==100004 and self.fail:raise RuntimeError('测试断网')
            # No previews at all: IDs on both attacker and defender still lead
            # to players in successive rounds. A guard must not enter the queue.
            rows={100002:[battle(1,100002,100003,100002)],
                  100003:[battle(2,100004,100003,100004)],
                  100004:[battle(3,100004,100006,100004)],
                  100006:[battle(4,100006,1,100006)],100005:[]}[pid]
            return dict(rows=rows,total=len(rows))
        raise AssertionError(op)


def prepare(tmp_path):
    app,panel=setup(tmp_path)
    ranks=panel.cache[panel.account]['ranks']['war']
    ranks['legions'].append(dict(id=42,name='本阴司',memberNum=1))
    transport=GraphTransport()
    feature=SeasonInsightFeature(transport,SimpleNamespace(installed='one',closing=False),panel,None)
    feature.generation=1
    return app,panel,transport,feature


def test_recursive_scan_includes_unaffiliated_and_settlement_players_and_reuses_cache(tmp_path):
    async def run():
        app,panel,transport,feature=prepare(tmp_path)
        await scan_battlefield(feature,dict(warId='war',bTimeId=1),'one',1)
        scan=panel.cache[panel.account]['battlefield_scans']['war']
        rows={str(r['id']):r for r in scan['rows']}
        assert set(rows)=={'100002','100003','100004','100005','100006'}
        assert rows['100004']['legionName']=='阴司未知'
        assert rows['100005']['statisticsSource']=='服务端结算'
        assert scan['round']>=3 and scan['complete'] and not scan['failures']
        report_ids=[args['roleId'] for op,args in transport.calls if op=='reports']
        assert sorted(report_ids)==[100002,100003,100004,100005,100006]
        roster_indices=[i for i,(op,_) in enumerate(transport.calls) if op=='legion_roster']
        unknown_index=next(i for i,(op,a) in enumerate(transport.calls) if op=='reports' and a['roleId']==100003)
        assert max(roster_indices)<unknown_index
        assert panel.roles.rowCount()==5
        before=len(transport.calls)
        await scan_battlefield(feature,dict(warId='war',bTimeId=1),'one',1)
        assert len(transport.calls)==before
        panel.close()
    asyncio.run(run())


def test_failure_is_saved_without_retry_loop_and_next_scan_recovers(tmp_path):
    async def run():
        app,panel,transport,feature=prepare(tmp_path)
        transport.fail=True
        await scan_battlefield(feature,dict(warId='war',bTimeId=1),'one',1)
        scan=panel.cache[panel.account]['battlefield_scans']['war']
        assert not scan['complete'] and '100004' in scan['failures']
        assert len([1 for op,a in transport.calls if op=='reports' and a['roleId']==100004])==1
        transport.fail=False
        before=len(transport.calls)
        await scan_battlefield(feature,dict(warId='war',bTimeId=1),'one',1)
        scan=panel.cache[panel.account]['battlefield_scans']['war']
        assert scan['complete'] and len(scan['rows'])==5
        assert [a['roleId'] for op,a in transport.calls[before:] if op=='reports']==[100004,100006]
        panel.close()
    asyncio.run(run())


def test_stop_preserves_report_cache_and_scan_can_continue(tmp_path):
    async def run():
        app,panel,transport,feature=prepare(tmp_path)
        original=transport.season_insight
        async def stop_after_page(op,args):
            result=await original(op,args)
            if op=='guard_count' and args['roleId']==100003:feature.request('stop_scan',{})
            return result
        transport.season_insight=stop_after_page
        await scan_battlefield(feature,dict(warId='war',bTimeId=1),'one',1)
        bucket=panel.cache[panel.account]
        assert bucket['reports']['war:100003:players']['complete']
        assert not bucket['battlefield_scans']['war']['complete']
        assert '已停止扫描' in panel.message.text()
        transport.season_insight=original
        await scan_battlefield(feature,dict(warId='war',bTimeId=1),'one',feature.generation)
        assert bucket['battlefield_scans']['war']['complete']
        assert len([1 for op,a in transport.calls if op=='reports' and a['roleId']==100003])==1
        panel.close()
    asyncio.run(run())


def test_refresh_button_dispatches_selected_battlefield_scan(tmp_path):
    async def run():
        app,panel,transport,feature=prepare(tmp_path)
        original=transport.season_insight
        ranks=panel.cache[panel.account]['ranks']['war']
        async def fetch(op,args):
            if op=='history':return dict(account=panel.account,rows=[dict(warId='war',bTimeId=1,name='血月')])
            if op=='ranks':return ranks
            return await original(op,args)
        transport.season_insight=fetch
        panel.set_ready(True)
        panel.refresh.click()
        await feature.job
        await asyncio.sleep(0)  # pending scan is dispatched after history releases the read slot
        await feature.job
        assert panel.cache[panel.account]['battlefield_scans']['war']['complete']
        assert panel.tabs.currentIndex()==1 and panel.roles.rowCount()==5
        panel.close()
    asyncio.run(run())
