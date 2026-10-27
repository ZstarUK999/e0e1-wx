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


def test_weighted_attacks_contribution_estimate_and_csv(tmp_path):
    import csv
    from package.plugin_manager.legion_boss import export_members_csv
    data=snapshot()
    data.update(logComplete=True,logTotal=6,logs=[
        dict(roleId='2',roundId=1,kind='player'),dict(roleId='2',roundId=1,kind='monster'),
        dict(roleId='2',roundId=3,kind='monster'),dict(roleId='2',roundId=3,kind='monster'),
        dict(roleId='3',roundId=6,kind='boss'),dict(roleId='2',roundId=3,kind='unknown')],
        contributions=[dict(id='2',rank=1,score=1234)],bossOngoing=True,
        bossRewardRules=[dict(**{'from':4,'to':5},points=12000)])
    rows=compare_members(data);r=next(r for r in rows if r['id']=='2')
    assert r['tue_monsters']==1 and r['tue_players']==1 and r['tue_attacks']==3
    assert r['thu_monsters']==2 and r['thu_attacks']==2
    assert r['total_contribution']==13234 and r['boss_bonus']==12000
    unknown=next(r for r in rows if r['id']=='3')
    assert unknown['participated'] and unknown['total_contribution'] is None
    r['name']='=danger,名字'
    path=tmp_path/'members.csv';export_members_csv(path,data,rows)
    with path.open(encoding='utf-8-sig',newline='') as f: exported=list(csv.DictReader(f))
    entry=next(r for r in exported if r['玩家ID']=='2')
    assert entry['名字']=="'=danger,名字" and entry['当前总贡献']=='13234'
    assert len(exported)==3 and entry['日志完整']=='是'
    data['bossOngoing']=False
    assert next(r for r in compare_members(data) if r['id']=='2')['total_contribution']==1234


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
