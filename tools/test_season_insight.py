import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from package.plugin_manager.season_insight import SeasonInsightPanel, SeasonInsightFeature, report_row, format_time
from package.plugin_manager.store import PluginConfigStore


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def report(battle=1):
    return {'battleId':battle,'rolePreview':{'id':100001,'name':'甲','fightPower':123456789},
        'tarRolePreview':{'id':100002,'name':'乙','fightPower':90000000},
        'roleInfo':{'roleId':100001,'energy':80},'tarRoleInfo':{'roleId':100002,'energy':0},
        'winRoleId':100002,'time':1792840000000,'place':'黄泉城'}


def history():
    return {'account':'100001:42','rows':[{'warId':'a','bTimeId':101,'name':'血月初赛','seasonId':10}], 'note':'历史记录'}


def panel(tmp_path):
    store=PluginConfigStore(tmp_path/'plugins.json')
    return SeasonInsightPanel(store)


def test_report_perspective_power_zero_energy_and_missing(app,tmp_path):
    row=report_row(report(),100002)
    assert row['name']=='乙' and row['opponent']=='甲'
    assert row['result']=='胜' and row['side']=='防守'
    assert row['energy']==0 and row['other_energy']==80
    assert row['power']==90000000
    missing=report();missing['tarRolePreview'].pop('fightPower')
    assert report_row(missing,100002)['power'] is None
    assert format_time(None)=='—'


def test_panel_root_tabs_double_click_sorted_player_and_replay(app,tmp_path):
    p=panel(tmp_path);events=[];p.requested.connect(lambda op,args:events.append((op,args)))
    p.accept_history(history())
    assert p.tabs.count()==3
    ranks={'warId':'a','legions':[{'id':42,'name':'阴司甲','rank':1}],
        'roles':[{'id':100001,'name':'甲','rank':2},{'id':100002,'name':'乙','rank':1}]}
    p.show_ranks(ranks);p.roles.sortItems(0,Qt.SortOrder.AscendingOrder)
    p._open_player(0,0)
    assert p.tabs.currentIndex()==2
    assert events[-1][0]=='reports' and events[-1][1]['roleId']==100002
    assert events[-1][1]['reportFilter']=='players'
    p.show_reports({'warId':'a','roleId':100002,'rows':[report()]})
    assert p.reports.item(0,8).text()=='9000万'
    assert p.reports.item(0,6).text()=='0'
    p._open_replay(0,0)
    assert events[-1][0]=='replay' and events[-1][1]['battleId']==1
    assert events[-1][1]['roleId']==100002
    assert p.cache_path.exists()


def test_personal_reports_hide_cached_guards_and_keep_replay_mapping(app,tmp_path):
    p=panel(tmp_path);p.accept_history(history());p.role={'id':100001,'name':'甲'}
    guard=report(7);guard['tarRoleInfo']['roleId']=1;guard['tarRolePreview']['id']=1
    pvp=report(8)
    data={'warId':'a','roleId':100001,'rows':[guard,pvp],'complete':True}
    p.show_reports(data)
    assert p.reports.rowCount()==1
    assert p.reports.item(0,0).data(Qt.ItemDataRole.UserRole+1)['battleId']==8
    assert '仅玩家对战' in p.tabs.tabText(2)
    assert len(p.cache[p.account]['reports']['a:100001']['rows'])==2
    p.close()


def test_csv_exports_current_sorted_members_and_only_visible_player_reports(app,tmp_path):
    import csv
    p=panel(tmp_path);p.accept_history(history())
    p.show_ranks({'warId':'a','legions':[], 'roles':[
        {'id':100001,'rank':2,'name':'甲,乙','score':10,'fightPower':123456789,'killGuardNum':3},
        {'id':100002,'rank':1,'name':'=公式','score':100,'dieNum':0}]})
    p.tabs.setCurrentIndex(1);p.roles.sortItems(4,Qt.SortOrder.DescendingOrder)
    path=tmp_path/'members.csv';p.export_table_csv(path)
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    with path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.reader(stream))
    assert rows[1][4]=="'=公式" and rows[2][4]=='甲,乙'
    assert rows[2][13]=='123456789'
    p.role={'id':100001};guard=report(7);guard['tarRoleInfo']['roleId']=1
    p.show_reports({'warId':'a','roleId':100001,'rows':[guard,report(8)]})
    p.tabs.setCurrentIndex(2);p.export_table_csv(path)
    with path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.reader(stream))
    assert len(rows)==2 and rows[1][-1]=='8'
    p.close()


def test_stale_results_do_not_replace_new_player_and_account_cache_is_separate(app,tmp_path):
    p=panel(tmp_path);p.accept_history(history());p.role={'id':100002}
    p.show_reports({'warId':'a','roleId':100001,'rows':[report()]})
    assert p.reports.rowCount()==0
    p.accept_history({'account':'other:42','rows':[]})
    assert p.selector.count()==0 and p.war is None


class Transport:
    def __init__(self):self.calls=[];self.statuses=[{'hooked':0},{'hooked':1},{'hooked':0}]
    async def season_insight(self,op,args):
        self.calls.append((op,args))
        if op=='replay':return {'token':'test'}
        if op=='replay_status':return {'token':'test','status':'returned'}
        if op=='history':return history()
        if op=='ranks':return {'warId':'a','legions':[],'roles':[]}
        if op=='reports':
            start=args['start'];return {'rows':[report(i+1) for i in range(start,min(start+15,123))],'total':123}
    async def damage_status(self):return self.statuses.pop(0) if self.statuses else {'hooked':0}
    async def damage_reset(self):self.calls.append(('reset',{}))
    async def damage_stop(self):self.calls.append(('stop',{}))


class Damage:
    def __init__(self,store):self.store=store;self.forced_replay=False;self.takes=[];self._injected=False
    async def _ensure_injected(self):self._injected=True
    async def take(self,force=False):self.takes.append((force,self.forced_replay));self._written=True


def feature(tmp_path):
    p=panel(tmp_path);t=Transport();state=SimpleNamespace(closing=False,installed='session')
    d=Damage(p.store);f=SeasonInsightFeature(t,state,p,d)
    return f,p,t,state,d


def test_all_report_pages_loaded_and_preserved(app,tmp_path):
    async def run():
        f,p,t,state,d=feature(tmp_path);p.war=history()['rows'][0];p.role={'id':100001};p.account='100001:42'
        p.cache[p.account]={'wars':{},'ranks':{},'reports':{}}
        await f.handle('reports',{'warId':'a','roleId':100001},'session',0)
        assert [args['start'] for op,args in t.calls if op=='reports']==list(range(0,123,15))
        assert p.reports.rowCount()==123
        assert len(p.cache[p.account]['reports']['a:100001']['rows'])==123
    asyncio.run(run())


@pytest.mark.parametrize('enabled',[False,True])
def test_replay_forces_collector_then_restores_setting_after_finish(app,tmp_path,enabled):
    async def run():
        f,p,t,state,d=feature(tmp_path);d.store.set_damage({'enabled':enabled})
        await f.replay({'warId':'a','roleId':100001,'battleId':1},'session')
        assert d.takes and all(forced for _,forced in d.takes)
        assert not d.forced_replay
        assert any(op=='stop' for op,_ in t.calls)==(not enabled)
        assert '回放结束' in p.message.text()
        assert d.store.snapshot()['damage']['enabled']==enabled
    asyncio.run(run())


def test_replay_open_failure_releases_collector(app,tmp_path):
    async def run():
        f,p,t,state,d=feature(tmp_path)
        original=t.season_insight
        async def fail(op,args):
            if op=='replay':raise RuntimeError('战报已过期')
            return await original(op,args)
        t.season_insight=fail
        await f.replay({'warId':'a','roleId':100001,'battleId':1},'session')
        assert not d.forced_replay and ('stop',{}) in t.calls
        assert '过期' in p.message.text()
    asyncio.run(run())


def test_shutdown_cancels_replay_and_releases_force(app,tmp_path):
    async def run():
        f,p,t,state,d=feature(tmp_path)
        t.statuses=[{'hooked':0}]+[{'hooked':1}]*20
        f.request('replay',{'warId':'a','roleId':100001,'battleId':1})
        for _ in range(10):await asyncio.sleep(0)
        assert d.forced_replay
        await f.close()
        assert not d.forced_replay
    asyncio.run(run())


def test_history_refresh_queues_rank_read(app,tmp_path):
    async def run():
        f,p,t,state,d=feature(tmp_path)
        f.request('history',{})
        for _ in range(20):await asyncio.sleep(0)
        assert [op for op,args in t.calls]==['history','ranks']
    asyncio.run(run())
