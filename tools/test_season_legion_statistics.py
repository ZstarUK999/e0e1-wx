import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QTableWidgetItem
from package.plugin_manager.season_insight import SeasonInsightPanel, SeasonInsightFeature
from package.plugin_manager.season_legion_statistics import report_statistics, load_reports
from package.plugin_manager.store import PluginConfigStore


def battle(key, a=100001, d=100002, winner=100001):
    return dict(battleId=key, roleInfo=dict(roleId=a), tarRoleInfo=dict(roleId=d), winRoleId=winner)


def test_report_statistics_guard_defense_loss_and_duplicates():
    rows = [battle(1), battle(1), battle(2, 100002, 100001, 100001),
            battle(3, 100001, 1, 100001), battle(4, 100001, 100002, 100002),
            battle(5, 100001, 100002, 0), battle(6, 100003, 100004, 100003)]
    assert report_statistics(rows, 100001) == dict(killRoleNum=2, killGuardNum=1, dieNum=1, unresolved=2)


def setup(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = SeasonInsightPanel(PluginConfigStore(tmp_path/'plugins.json'))
    panel.accept_history(dict(account='wechat:100001:42', rows=[dict(warId='war', bTimeId=1, name='血月')]))
    panel.show_ranks(dict(warId='war', legions=[dict(id=99, name='其他阴司', memberNum=4, rank=1)],
                          roles=[dict(id=100002, name='乙', legionId=99, score=10)]))
    return app, panel


class Transport:
    def __init__(self):
        self.calls = []
    async def season_insight(self, op, args):
        self.calls.append((op, dict(args)))
        if op == 'legion_roster':
            return dict(memberNum=4, members=[dict(id='100003', name='丙', legionId=99)])
        if op == 'guard_count':
            return dict(total=12 if args['roleId']==100002 else 0)
        if op == 'reports':
            pid = args['roleId']
            row = battle(pid, pid, 1, pid)
            # A participant outside top 100 is discovered in a cached report.
            if pid == 100002:
                row['rolePreview'] = dict(id=100002, legionId=99)
                row['tarRolePreview'] = dict(id=100004, name='丁', legionId=99)
                row['tarRoleInfo'] = dict(roleId=100004)
            return dict(rows=[row], total=1)
        raise AssertionError(op)


def test_double_click_discovers_members_and_cache_skips_network(tmp_path):
    async def run():
        app, panel = setup(tmp_path)
        transport = Transport()
        feature = SeasonInsightFeature(transport, SimpleNamespace(installed='one', closing=False), panel, None)
        panel._open_legion(0, 0)
        await feature.job
        assert panel.tabs.currentIndex() == 1
        assert panel.roles.rowCount() == 3 and '3/4' in panel.message.text()
        assert panel.roles.item(0, 4).text() == '10'
        assert {panel.roles.item(i, 8).text() for i in range(3)} == {'玩家战报统计'}
        assert all(args.get('reportFilter')=='players' for op,args in transport.calls if op=='reports')
        assert sorted(r['killGuardNum'] for r in panel.cache[panel.account]['legion_statistics']['war:99']['rows']) == [0,0,12]
        assert len([1 for op,_ in transport.calls if op=='guard_count'])==3
        assert panel.cache[panel.account]['legion_statistics']['war:99']['complete']
        before = len(transport.calls)
        panel._open_legion(0, 0)
        assert len(transport.calls) == before
        panel._open_player(0, 0)
        assert panel.reports.rowCount() == 1 and len(transport.calls) == before
        panel.close()
        _, restored = setup(tmp_path)
        restored._open_legion(0, 0)
        assert restored.roles.rowCount() == 3
        restored.close()
    asyncio.run(run())


def test_partial_reports_resume_without_repeating_first_page(tmp_path):
    async def run():
        app, panel = setup(tmp_path)
        calls = []
        fail = [True]
        class Paging:
            async def season_insight(self, op, args):
                calls.append(args['start'])
                if args['start'] == 15 and fail[0]:
                    raise RuntimeError('网络中断')
                return dict(rows=[battle(i+1) for i in range(args['start'], min(args['start']+15, 17))], total=17)
        state = SimpleNamespace(installed='one', closing=False)
        feature = SeasonInsightFeature(Paging(), state, panel, None)
        feature.generation = 1
        args = dict(warId='war', roleId=100001)
        try:
            await load_reports(feature, args, 'one', 1, panel.account)
        except RuntimeError:
            pass
        assert panel.cache[panel.account]['reports']['war:100001']['nextStart'] == 15
        fail[0] = False
        saved = await load_reports(feature, args, 'one', 1, panel.account)
        assert calls == [0, 15, 15] and len(saved['rows']) == 17 and saved['complete']
        await load_reports(feature, args, 'one', 1, panel.account)
        assert calls == [0, 15, 15]
        panel.close()
    asyncio.run(run())


def test_bulk_table_uses_native_items_and_survives_repeated_replacement(tmp_path):
    app, panel = setup(tmp_path)
    panel.selected_legion=dict(id=99)
    rows=[dict(id=str(100000+i),name='成员'+str(i),score=500-i if i<25 else None,
               statisticsSource='战报统计',statisticsComplete=i<25) for i in range(50)]
    snapshot=dict(warId='war',legionId=99,legionName='测试',memberNum=56,rows=rows)
    for _ in range(100):
        panel.show_legion_statistics(snapshot)
        app.processEvents()
        assert type(panel.roles.item(0,0)) is QTableWidgetItem
        assert panel.roles.item(0,4).text()=='500'
        assert panel.roles.item(0,0).data(Qt.ItemDataRole.UserRole+1)['id']=='100000'
        assert panel.roles.item(0,1).data(Qt.ItemDataRole.UserRole+1) is None
    panel.close()


def test_filtered_cursor_is_separate_and_complete_all_cache_is_reused(tmp_path):
    async def run():
        app,panel=setup(tmp_path)
        transport=Transport()
        feature=SeasonInsightFeature(transport,SimpleNamespace(installed='one',closing=False),panel,None)
        feature.generation=1
        cache=panel.cache[panel.account]['reports']
        cache['war:100002']=dict(rows=[battle(1)],nextStart=15,complete=False)
        saved=await load_reports(feature,dict(warId='war',roleId=100002,reportFilter='players'),'one',1,panel.account)
        assert transport.calls[0][1]['start']==0
        assert 'war:100002:players' in cache and cache['war:100002']['nextStart']==15
        cache['war:100003']=dict(rows=[battle(2,100003,1,100003)],complete=True)
        before=len(transport.calls)
        saved=await load_reports(feature,dict(warId='war',roleId=100003,reportFilter='players'),'one',1,panel.account)
        assert saved is cache['war:100003'] and len(transport.calls)==before
        panel.close()
    asyncio.run(run())


def test_score_sort_uses_numeric_variants_across_digit_lengths(tmp_path):
    app,panel=setup(tmp_path)
    panel.selected_legion={'id':99}
    panel.show_legion_statistics(dict(warId='war',legionId=99,legionName='测试',
        rows=[dict(id=str(100000+i),score=score) for i,score in enumerate([887,1405,1025,152,None])]))
    assert [panel.roles.item(i,4).data(Qt.ItemDataRole.UserRole) for i in range(5)]==[1405,1025,887,152,None]
    assert isinstance(panel.roles.item(0,4).data(Qt.ItemDataRole.DisplayRole),int)
    panel.roles.sortItems(4,Qt.SortOrder.AscendingOrder)
    values=[panel.roles.item(i,4).data(Qt.ItemDataRole.UserRole) for i in range(5)]
    assert [v for v in values if v is not None]==[152,887,1025,1405]
    panel.close()
