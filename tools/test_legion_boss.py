import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from package.plugin_manager.legion_boss import compare_members, LegionBossPanel


def snapshot():
    return dict(roleId='1', legionId='42', legionName='本阴司', bfId='bf-current', source='legion-theater',
                bossName='跨服 Boss', rankLimit=500, fetchedAt='2026-10-25T12:00:00Z',
                members=[dict(id='1', name='甲'), dict(id='2', name='重名'), dict(id='3', name='重名')],
                ranks=[dict(id='2', name='重名', rank=5, score=123)], selfDamage=10, me=None)


def test_comparison_uses_ids_and_preserves_uncertainty():
    data = snapshot()
    rows = {r['id']: r for r in compare_members(data)}
    assert rows['1']['participated'] and rows['1']['score'] == 10
    assert rows['2']['participated'] and rows['2']['rank'] == 5
    assert not rows['3']['participated'] and rows['3']['status'] == '未上榜（待确认）'
    data['selfDamage'] = 0
    assert '本人伤害为 0' in next(r for r in compare_members(data) if r['id'] == '1')['status']
    data['me'] = dict(id='1', rank=600, score=100)
    assert next(r for r in compare_members(data) if r['id'] == '1')['participated']


def test_panel_filter_copy_and_rank_table():
    app = QApplication.instance() or QApplication([])
    panel = LegionBossPanel()
    panel.accept(snapshot())
    panel.filter.setCurrentIndex(0)
    assert panel.table.rowCount() == 1 and panel.table.item(0, 1).text() == '3'
    assert panel.rank_table.rowCount() == 1
    assert '已确认参与 2 人' in panel.summary.text()
    assert '战场 bf-current' in panel.summary.text()
    panel.filter.setCurrentIndex(1)
    assert panel.table.rowCount() == 3
    panel.filter.setCurrentIndex(2)
    assert panel.table.rowCount() == 2
    panel.copy_missing()
    assert '重名（3）' in app.clipboard().text() and '（2）' not in app.clipboard().text()
    panel.close()


def test_daily_wins_contribution_estimate_and_csv(tmp_path):
    import csv
    from package.plugin_manager.legion_boss import export_members_csv
    data=snapshot()
    logs=[battle_log(2,2,'player',False),battle_log(2,2,'monster',True),
          battle_log(2,4,'monster',True),battle_log(2,4,'player',True),
          battle_log(2,4,'monster',False),battle_log(3,6,'boss',False)]
    for log,point in zip(logs,[5,20,30,40,2,0]):log['point']=point
    data.update(logComplete=True,logTotal=6,logs=logs,
        contributions=[dict(id='2',rank=1,score=1234)],bossOngoing=True,
        bossRewardRules=[dict(**{'from':4,'to':5},points=12000)])
    rows=compare_members(data);r=next(r for r in rows if r['id']=='2')
    assert (r['wed_failures'],r['wed_monsters'],r['wed_players'],r['wed_contribution'])==(0,1,0,25)
    assert (r['fri_failures'],r['fri_monsters'],r['fri_players'],r['fri_contribution'])==(1,1,1,72)
    assert r['total_contribution']==13234 and r['boss_bonus']==12000
    unknown=next(r for r in rows if r['id']=='3')
    assert unknown['participated'] and unknown['total_contribution'] is None
    r['name']='=danger,名字'
    path=tmp_path/'members.csv';export_members_csv(path,data,rows)
    with path.open(encoding='utf-8-sig',newline='') as f: exported=list(csv.DictReader(f))
    entry=next(r for r in exported if r['玩家ID']=='2')
    assert entry['名字']=="'=danger,名字" and entry['当前总贡献']=='13234'
    assert entry['周三获取贡献']=='25' and entry['周五失败次数']=='1'
    assert len(exported)==3 and entry['日志完整']=='是'
    data['bossOngoing']=False
    settled=next(r for r in compare_members(data) if r['id']=='2')
    assert settled['total_contribution']==1234 and settled['boss_bonus']==12000


def test_feature_fetch_and_session_change(tmp_path):
    from package.plugin_manager.legion import LegionPanel, LegionFeature
    app = QApplication.instance() or QApplication([])
    panel = LegionPanel(SimpleNamespace(path=tmp_path / 'plugins.json'))
    state = SimpleNamespace(installed='one', closing=False)
    class Transport:
        async def legion_boss_read(self):
            return snapshot()
    feature = LegionFeature(Transport(), state, panel)
    asyncio.run(feature.fetch_boss())
    assert panel.boss.data['legionId'] == '42' and panel.boss.refresh.isEnabled()
    panel.boss.data = None
    async def changed():
        state.installed = 'two'
        return snapshot()
    feature.transport.legion_boss_read = changed
    asyncio.run(feature.fetch_boss())
    assert panel.boss.data is None and panel.boss.refresh.isEnabled()
    panel.close()


def test_transport_routes_and_packaging():
    from package.plugin_manager.transport import PluginTransport
    from package.plugin_manager.douyin import DouyinTransport
    from tools.build_exe import RESOURCES
    class Cdp:
        def on(self, *args):
            pass
    transport = PluginTransport(Cdp())
    transport.connected = True
    transport.context_id = 7
    async def evaluate(expression, context_id, timeout_ms):
        assert 'readLegionCrossBoss(globalThis)' in expression
        assert context_id == 7 and timeout_ms == 30000
        return snapshot()
    transport._evaluate = evaluate
    assert asyncio.run(transport.legion_boss_read())['legionId'] == '42'
    async def rpc(op, args, timeout_ms):
        assert op == 'legion-boss-read' and args == {} and timeout_ms == 30000
        return snapshot()
    fake = SimpleNamespace(_rpc=rpc)
    assert asyncio.run(DouyinTransport.legion_boss_read(fake))['legionId'] == '42'
    assert ('package/plugin_manager/legion_boss_runtime.js', 'package/plugin_manager') in RESOURCES


def battle_log(role,day,kind,win):
    return dict(roleId=str(role),roundId=day,kind=kind,isWin=win,targetRoleId='0',
                targetLegionId='0',point=0,wave=1,timeAt=100)


def test_failure_counts_use_member_id_and_only_monster_losses():
    data=snapshot()
    data.update(logComplete=True,logs=[
        battle_log(2,2,'player',False),battle_log(2,2,'monster',False),
        battle_log(2,4,'monster',True),battle_log(2,4,'monster',False),
        battle_log(2,6,'boss',False),battle_log(3,2,'monster',False),
        battle_log(2,4,'monster',None),battle_log(999,2,'monster',False),
        battle_log(2,1,'monster',False),battle_log(2,3,'monster',False)])
    rows={r['id']:r for r in compare_members(data)}
    assert rows['2']['wed_failures']==1 and rows['2']['fri_failures']==1
    assert rows['2']['wed_players']==0 and rows['2']['fri_monsters']==1
    assert rows['2']['wed_complete'] and not rows['2']['fri_complete']
    assert rows['3']['wed_failures']==1 and rows['3']['wed_complete']
    assert rows['1']['wed_failures']==0 and rows['1']['fri_failures']==0


def test_failure_table_csv_and_unknown_result_are_explicit(tmp_path):
    import csv
    from package.plugin_manager.legion_boss import export_members_csv
    app=QApplication.instance() or QApplication([])
    data=snapshot();data.update(logComplete=False,logTotal=200,logs=[
        battle_log(2,2,'player',False),battle_log(2,2,'monster',None),battle_log(2,2,'monster',False)])
    panel=LegionBossPanel();panel.accept(data)
    row=next(i for i in range(panel.table.rowCount()) if panel.table.item(i,1).text()=='2')
    assert panel.table.item(row,6).text()=='≥1'
    assert panel.table.item(row,7).text()=='≥0'
    assert panel.table.item(row,8).text()=='≥0'
    assert panel.log_table.item(0,10).text()=='重名'
    assert panel.log_table.item(0,3).text()=='0'
    assert panel.log_table.item(1,6).text()=='未知'
    assert panel.log_table.item(2,3).text()=='1'
    path=tmp_path/'members.csv';export_members_csv(path,data,panel.rows)
    with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    row=next(r for r in rows if r['玩家ID']=='2')
    assert row['周三失败次数']=='1' and row['周三次数完整']=='否'
    panel.close()


def test_complete_empty_logs_mean_zero_but_missing_logs_are_only_lower_bounds():
    data=snapshot();data.update(logComplete=True,logs=[])
    assert all(r['wed_failures']==0 and r['wed_complete'] and r['fri_complete'] for r in compare_members(data))
    data['logComplete']=False
    assert all(r['wed_failures']==0 and not r['wed_complete'] for r in compare_members(data))
    data.update(logComplete=True,logResultsComplete=False)
    assert not any(r['wed_complete'] for r in compare_members(data))


def test_missing_daily_points_do_not_fabricate_contribution():
    data=snapshot();logs=[battle_log(2,2,'monster',True),battle_log(2,2,'player',False)]
    logs[0]['point']=15;logs[1].pop('point')
    data.update(logComplete=True,logs=logs)
    row=next(r for r in compare_members(data) if r['id']=='2')
    assert row['wed_contribution']==15 and not row['wed_contribution_complete']
    assert row['wed_complete'] and row['fri_contribution_complete']
    app=QApplication.instance() or QApplication([])
    panel=LegionBossPanel();panel.accept(data)
    index=next(i for i in range(panel.table.rowCount()) if panel.table.item(i,1).text()=='2')
    assert panel.table.item(index,9).text()=='≥15'
    panel.close()


def test_columns_and_sorting_use_raw_numbers_for_all_numeric_fields():
    from PySide6.QtCore import Qt
    from package.plugin_manager.legion_boss import MEMBER_COLUMNS
    app=QApplication.instance() or QApplication([])
    panel=LegionBossPanel()
    assert [title for _,title in MEMBER_COLUMNS][6:]==[
        '周三失败次数','周三击败怪群次数','周三击败玩家次数','周三获取贡献',
        '周五失败次数','周五击败怪群次数','周五击败玩家次数','周五获取贡献',
        '周日Boss伤害','周日Boss排名','周日预估贡献','当前总贡献']
    data=snapshot();data.update(members=[dict(id='2'),dict(id='10'),dict(id='20')],
        ranks=[dict(id='2',rank=2,score=90000000),dict(id='10',rank=10,score=200000000)],
        selfDamage=None,logComplete=False,
        logs=[battle_log(2,2,'monster',False) for _ in range(2)]+
             [battle_log(10,2,'monster',False) for _ in range(10)])
    panel.accept(data)
    def ids():return [panel.table.item(i,1).text() for i in range(3)]
    panel.table.sortItems(1,Qt.SortOrder.AscendingOrder)
    assert ids()==['2','10','20']
    panel.table.sortItems(6,Qt.SortOrder.AscendingOrder)
    assert ids()==['20','2','10']
    assert panel.table.item(2,6).text()=='≥10'
    assert panel.table.item(2,6).data(Qt.ItemDataRole.UserRole)==10
    panel.table.sortItems(14,Qt.SortOrder.AscendingOrder)
    assert ids()==['2','10','20']
    assert panel.table.item(0,14).text()=='9000万' and panel.table.item(1,14).text()=='2亿'
    panel.table.sortItems(15,Qt.SortOrder.AscendingOrder)
    assert ids()==['2','10','20']
    panel.table.sortItems(14,Qt.SortOrder.DescendingOrder)
    assert ids()==['10','2','20']
    panel.close()


def test_hidden_columns_export_and_total_sort_with_missing_values(tmp_path):
    import csv
    from PySide6.QtCore import Qt
    from package.plugin_manager.legion_boss import MEMBER_COLUMNS, export_members_csv
    app=QApplication.instance() or QApplication([])
    data=snapshot()
    data.update(members=[dict(id=str(i),name=str(i),sName='某服',job=1) for i in range(1,6)],
        ranks=[],selfDamage=None,bossOngoing=False,
        contributions=[dict(id='2',rank=1,score=6000),dict(id='3',rank=2,score=5800),dict(id='4',rank=4,score=0),dict(id='5',rank=3,score=900)])
    panel=LegionBossPanel();panel.accept(data)
    for i,(key,_) in enumerate(MEMBER_COLUMNS):
        assert panel.table.isColumnHidden(i)==(key in ('status','id','sName','job'))
    def ids():return [panel.table.item(i,1).text() for i in range(5)]
    assert ids()==['2','3','5','4','1']
    panel.table.sortItems(17,Qt.SortOrder.AscendingOrder)
    assert ids()==['4','5','3','2','1']
    panel.table.sortItems(17,Qt.SortOrder.DescendingOrder)
    assert ids()==['2','3','5','4','1']
    panel.accept(data)
    assert ids()==['2','3','5','4','1']
    path=tmp_path/'members.csv';export_members_csv(path,data,panel.rows)
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        assert '玩家ID' in reader.fieldnames
        assert not {'Boss参与情况','参与情况','服务器','职位'} & set(reader.fieldnames)
        assert len(list(reader))==5
    panel.close()
