import asyncio
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from package.plugin_manager.legion_scan_store import LegionScanStore
from package.plugin_manager.legion_scan import LegionScanPanel,LegionScanner
from package.plugin_manager.season_insight import SeasonInsightPanel
from package.plugin_manager.store import PluginConfigStore
from package.plugin_manager.runtime import PluginRuntime

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

def groups():
    return [{'id':'42','name':'血月阴司','members':[{'id':12000100,'name':'旧名字','fightPower':100,'sName':'540服'}, {'id':12000101,'name':'另一人'}]}]

def test_import_persistent_idempotent_preserves_live_data_and_no_ranges(tmp_path):
    db=LegionScanStore(tmp_path/'scan.db')
    db.record(12000100,dict(id=12000100,name='新名字',fightPower=999,legionId='77',legionName='新阴司'))
    assert db.import_bloodmoon(groups())==2
    assert db.import_bloodmoon(groups())==2
    task=db.tasks()[0]
    assert task['source']=='bloodmoon' and db.candidate(task) is None
    live=db.members(task['id'],'77')[0]
    assert live['name']=='新名字' and live['power']==999
    assert len(db.queued_members(10))==1
    db=LegionScanStore(db.path)
    assert len(db.tasks())==1 and db.candidate(db.tasks()[0]) is None
    assert db.stale_marked_player()['id']==12000101
    with db.connect() as con:
        con.execute("UPDATE scan_players SET checked_at='2000-01-01'")
    # Imported members remain watched after moving to an unmarked low-power legion.
    assert db.stale_marked_player()['id']==12000100
    assert not LegionScanStore(db.path,platform='douyin').tasks()

def test_import_transaction_rolls_back_invalid_power(tmp_path):
    db=LegionScanStore(tmp_path/'scan.db')
    rows=groups();rows[0]['members'][1]['fightPower']='broken'
    with pytest.raises(ValueError):db.import_bloodmoon(rows)
    assert db.tasks()==[] and not db.queued_members(10)

def test_import_existing_scan_keeps_cursor_and_can_promote_import(tmp_path):
    db=LegionScanStore(tmp_path/'scan.db')
    info=dict(id='42',name='阴司',members=[dict(id=12000100+i,job=j) for i,j in enumerate((1,2,2))])
    db.import_bloodmoon(groups())
    task=db.create_task(info)
    assert task['source']=='scan' and task['cursor']==0
    assert db.candidate(task)==12000100
    db.record(12000100,dict(id=12000100,legionId='42'),task)
    db.import_bloodmoon(groups())
    assert db.tasks()[0]['cursor']==1

def test_button_selected_and_whole_battle_scope(app,tmp_path):
    panel=SeasonInsightPanel(PluginConfigStore(tmp_path/'plugins.json'))
    panel.account='微信:1:42';panel.war={'warId':'w'}
    panel.cache[panel.account]={'ranks':{'w':{'legions':[{'id':42,'name':'甲'}], 'roles':[{'id':12000100,'legionId':42},{'id':12000110,'legionId':43}]}},
        'legion_statistics':{'w:42':dict(warId='w',legionId=42,legionName='甲',rows=[{'id':12000101}]),
        'other:42':dict(warId='other',legionId=42,rows=[{'id':12000999}])}}
    payloads=[];panel.sync_requested.connect(payloads.append)
    panel.selected_legion={'id':42};panel.sync_legion.click()
    assert len(payloads)==1
    assert {r['id'] for r in payloads[-1]['groups'][0]['members']}=={12000100,12000101}
    panel.selected_legion=None;panel.sync_legion.click()
    assert {str(g['id']) for g in payloads[-1]['groups']}=={'42','43'}
    panel.close()

def test_scheduler_updates_imported_members_and_daily_rechecks(app,tmp_path):
    async def run():
        panel=LegionScanPanel(tmp_path/'scan.db')
        calls=[]
        async def lookup(op,ids):
            pids=ids if isinstance(ids,list) else [ids]
            calls.extend(pids)
            values=[dict(id=int(pid),name='最新玩家',fightPower=123,legionId='42') for pid in pids]
            return [dict(id=pid,value=value) for pid,value in zip(pids,values)] if isinstance(ids,list) else values[0]
        async def read(lid):return dict(id=lid,name='最新阴司',members=[],fightPower=1)
        scanner=LegionScanner(SimpleNamespace(legion_scan_call=lookup,legion_read=read),SimpleNamespace(installed='s',closing=False),panel)
        scanner.timer.stop()
        scanner.import_bloodmoon(groups())
        assert scanner.enabled
        await scanner.step()
        assert len(calls)==2 and not scanner.db.queued_members(10)
        await scanner.step() # refresh legion
        await scanner.step() # today's members skipped; no range scan
        assert len(calls)==2
        with scanner.db.connect() as con:con.execute("UPDATE scan_players SET checked_at='2000-01-01'")
        await scanner.step()
        assert len(calls)==3
        panel.close()
    asyncio.run(run())

def test_runtime_platform_guard_and_sync_feedback(app,tmp_path):
    panel=SeasonInsightPanel(PluginConfigStore(tmp_path/'plugins.json'))
    scan=LegionScanPanel(tmp_path/'scan.db')
    scanner=LegionScanner(SimpleNamespace(platform_name='微信'),SimpleNamespace(installed=None,closing=False),scan)
    scanner.timer.stop()
    runtime=SimpleNamespace(window=SimpleNamespace(pages={'season_insight':panel}),legion=SimpleNamespace(scanner=scanner),platform_name='微信')
    PluginRuntime.sync_season_members(runtime,dict(account='抖音:1:42',groups=groups()))
    assert not scanner.db.tasks() and '不一致' in panel.message.text()
    PluginRuntime.sync_season_members(runtime,dict(account='微信:1:42',groups=groups()))
    assert len(scanner.db.tasks())==1 and '2 名' in panel.message.text()
    panel.close();scan.close()
