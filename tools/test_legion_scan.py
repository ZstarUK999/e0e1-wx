import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication

from package.plugin_manager.legion_scan_store import LegionScanStore, SCAN_SIZE
from package.plugin_manager.legion_scan import LegionScanPanel,LegionScanner


def guild(lid='42',power=400000000):
    return {'id':lid,'name':'测试阴司'+lid,'fightPower':power,'members':[
        {'id':str(12000100+i),'name':'成员'+str(i),'fightPower':100+i,'job':job,'sName':str(540+i)+'服','sId':540+i}
        for i,job in enumerate((1,2,2))]}


def player(pid, lid='42', server=550):
    return {'id':str(pid),'name':'玩家','fightPower':123456,'legionId':lid,'legionName':'测试阴司'+lid,'sId':server,'sName':f'{server}服'}


def test_last_online_nullable_persistent_relative_and_beijing_tooltip(tmp_path):
    from package.plugin_manager.legion_scan import relative_online
    from PySide6.QtCore import Qt
    app=QApplication.instance() or QApplication([])
    panel=LegionScanPanel(tmp_path/'online.db');task=panel.db.create_task(guild())
    assert all(m['last_online_ms'] is None for m in panel.db.members(task['id'],'42'))
    stamp=1792691916767
    panel.db.record(12000100,{**player(12000100),'lastOnlineTime':stamp,'online':False})
    assert LegionScanStore(panel.db.path).members(task['id'],'42')[0]['last_online_ms']==stamp
    assert relative_online(None)=='未更新'
    assert relative_online(stamp,False,stamp/1000+120)=='2分钟前'
    assert relative_online(stamp,False,stamp/1000+7200)=='2小时前'
    assert relative_online(stamp,False,stamp/1000+172800)=='2天前'
    assert relative_online(stamp,True,stamp/1000+7200)=='刚刚'
    panel.refresh();root=panel.tree.topLevelItem(0);panel.expand(root);branch=root.child(0);panel.expand(branch)
    rows=[branch.child(i) for i in range(branch.childCount())]
    updated=next(r for r in rows if r.data(0,Qt.ItemDataRole.UserRole)==('player',12000100))
    assert '2026-10-23 01:58:36 北京时间'==updated.toolTip(5)
    assert any(row.text(5)=='未更新' for row in rows)
    panel.close()


def test_inserted_member_update_preempts_after_inflight_query_and_then_resumes(tmp_path):
    app=QApplication.instance() or QApplication([])
    async def run():
        panel=LegionScanPanel(tmp_path/'insert.db');panel.db.create_task(guild())
        panel.db.set_workers(1);panel.db.set_min_power(10**12)
        started=asyncio.Event();release=asyncio.Event();calls=[]
        async def lookup(op,pid):
            calls.append(pid)
            if len(calls)==1:started.set();await release.wait()
            return {**player(pid),'lastOnlineTime':1792691916767,'online':False}
        state=SimpleNamespace(installed='s',closing=False)
        scanner=LegionScanner(SimpleNamespace(legion_scan_call=lookup),state,panel)
        scanner.job=asyncio.create_task(scanner.step());await started.wait()
        scanner.insert_member_update('42')
        assert len(panel.db.queued_members(10))==3
        release.set();await scanner.job
        assert panel.db.tasks()[0]['cursor']==1
        for _ in range(3):await scanner.step()
        assert calls==['12000100','12000100','12000101','12000102']
        assert panel.db.tasks()[0]['cursor']==1 and not panel.db.queued_members(1)
        await scanner.step()
        assert calls[-1]=='12000101' and panel.db.tasks()[0]['cursor']==2
        assert all(m['last_online_ms'] for m in panel.db.members(panel.db.tasks()[0]['id'],'42'))
        panel.db.enqueue_members('42')
        assert len(LegionScanStore(panel.db.path).queued_members(10))==3
        panel.close()
    asyncio.run(run())


def test_player_inspection_ignores_previous_selection_and_shows_server_errors():
    from package.plugin_manager.runtime import PluginRuntime
    async def run():
        shown=[];messages=[];calls=[]
        fake=SimpleNamespace(state=SimpleNamespace(installed='s',closing=False),_player_target_id='12300100')
        panel=SimpleNamespace(message=SimpleNamespace(setText=messages.append))
        fake.window=SimpleNamespace(pages={'player':panel},set_player_information=lambda *args:shown.append(args))
        async def call(op,args):
            calls.append((op,args))
            if args['target_id']=='12300100':fake._player_target_id='12300101'
            return {'subject':args['target_id'],'text':'资料'+args['target_id']}
        fake.transport=SimpleNamespace(call=call)
        await PluginRuntime._fetch_scanned_player(fake)
        assert len(calls)==2 and shown==[('资料12300101','12300101')]
        async def error(*args):raise RuntimeError('未找到对方数据 (330015)')
        fake.transport.call=error
        await PluginRuntime._fetch_scanned_player(fake)
        assert '330015' in messages[-1] and len(shown)==1
    asyncio.run(run())


def expand_range(db, low, high):
    db.record(low,player(low))
    db.record(high,player(high))
    db.calibrate()
    return db.tasks()[0]


def test_hundred_id_batches_and_persisted_interval(tmp_path):
    db=LegionScanStore(tmp_path/'scan.db');info=guild()
    for m in info['members']:m['id']=str(int(m['id'])+50000)
    task=db.create_task(info)
    task=expand_range(db,12000000,12099999)
    ids=[db.candidate({**task,'cursor':i}) for i in range(403)]
    assert ids[3:103]==list(range(12050103,12050203))
    assert ids[103:203]==list(range(12050099,12049999,-1))
    assert ids[203:303]==list(range(12050203,12050303))
    assert ids[303:403]==list(range(12049999,12049899,-1))
    db.set_interval(2.5);db.set_min_power(450000000)
    assert LegionScanStore(db.path).interval()==2.5
    assert db.min_power()==450000000
    db.set_workers(10);assert LegionScanStore(db.path).workers()==10
    with pytest.raises(ValueError):db.set_workers(11)


def test_parallel_partial_failure_keeps_successes_and_displays_server_error(tmp_path):
    app=QApplication.instance() or QApplication([])
    async def run():
        path=tmp_path/'parallel.db';panel=LegionScanPanel(path);task=panel.db.create_task(guild())
        panel.db.set_min_power(10**12)
        panel.db.set_workers(3);calls=[]
        async def lookup(op,ids):
            calls.append((op,ids))
            if op=='player':return player(ids)
            return [{'id':ids[0],'error':'服务器请求过于频繁 (9999)'},
                    {'id':ids[1],'value':player(ids[1])},{'id':ids[2],'value':None}]
        state=SimpleNamespace(installed='s',closing=False)
        scan=LegionScanner(SimpleNamespace(legion_scan_call=lookup),state,panel)
        scan.refreshed_legions.add('42')
        await scan.step()
        assert panel.db.tasks()[0]['cursor']==0
        assert '服务器请求过于频繁 (9999)' in panel.status.text()
        assert panel.db.receipt(task,1)[0] and panel.db.receipt(task,2)[0]
        # Simulated application restart: durable successes must not be re-requested.
        panel2=LegionScanPanel(path)
        resumed=LegionScanner(scan.transport,state,panel2);resumed.refreshed_legions.add('42')
        await resumed.step()
        assert calls[-1]==('player','12000100')
        assert panel2.db.tasks()[0]['cursor']==3
        panel.close();panel2.close()
    asyncio.run(run())


def test_independent_tick_only_queries_ready_session(tmp_path):
    app=QApplication.instance() or QApplication([])
    async def run():
        panel=LegionScanPanel(tmp_path/'tick.db');panel.db.create_task(guild());panel.db.set_workers(1)
        calls=[]
        async def read(lid):calls.append(lid);return guild(lid)
        state=SimpleNamespace(installed='s',closing=False)
        scanner=LegionScanner(SimpleNamespace(legion_read=read),state,panel)
        scanner.schedule();await asyncio.sleep(0);assert not calls
        scanner.set_ready('s');scanner.schedule()
        await asyncio.sleep(0);await scanner.wait_operation()
        assert calls==['42']
        state.installed='different';scanner.schedule();await asyncio.sleep(0)
        assert calls==['42']
        panel.close()
    asyncio.run(run())


@pytest.mark.parametrize('failures,successes,batches',[(1,0,3),(5,5,1)])
def test_many_errors_stop_persistently_until_manual_resume(tmp_path,failures,successes,batches):
    app=QApplication.instance() or QApplication([])
    async def run():
        panel=LegionScanPanel(tmp_path/'halt.db');panel.db.create_task(guild())
        state=SimpleNamespace(installed='s',closing=False)
        async def forbidden(*args):raise AssertionError('stopped scans must not send requests')
        transport=SimpleNamespace(legion_read=forbidden,legion_scan_call=forbidden)
        scanner=LegionScanner(transport,state,panel)
        for _ in range(batches):scanner.record_health(failures,successes,'服务器异常 (500)')
        assert '已停止扫描' in panel.status.text() and '服务器异常 (500)' in panel.status.text()
        await scanner.poll();await scanner.step();assert scanner.job is None
        another=LegionScanPanel(panel.db.path);resumed=LegionScanner(transport,state,another)
        assert resumed.halted
        resumed.set_ready('s');resumed.schedule();await asyncio.sleep(0);assert resumed.job is None
        resumed.resume_after_errors()
        assert not resumed.halted and not another.db.halt_reason()
        panel.close();another.close()
    asyncio.run(run())


def test_old_alternating_progress_migrates_without_repeating_ids(tmp_path):
    db=LegionScanStore(tmp_path/'scan.db');info=guild()
    for m in info['members']:m['id']=str(int(m['id'])+50000)
    task=db.create_task(info)
    task=expand_range(db,12000000,12099999)
    low,high=task['seed_low']-2,task['seed_high']+2
    with db.connect() as sql:
        for column in ('anchor_cursor','anchor_low','anchor_high'):
            sql.execute('ALTER TABLE scan_tasks DROP COLUMN '+column)
        sql.execute('UPDATE scan_tasks SET cursor=7,scanned_low=?,scanned_high=?',(low,high))
    db=LegionScanStore(db.path);task=db.tasks()[0]
    remaining=[db.candidate({**task,'cursor':i}) for i in range(7,100000)]
    assert remaining[:100]==list(range(high+1,high+101))
    assert remaining[100:200]==list(range(low-1,low-101,-1))
    assert len(set(remaining))==99993
    assert not set(range(low,high+1)).intersection(remaining)


def test_member_ids_expand_both_bounds_preserve_progress_receipts_and_restart(tmp_path):
    db=LegionScanStore(tmp_path/'expand.db');info=guild();task=db.create_task(info)
    task=expand_range(db,12000000,12099999)
    for _ in range(103):
        db.record(db.candidate(task),None,task);task=db.tasks()[0]
    old=dict(task);pending=db.candidate({**old,'cursor':104})
    db.save_receipt(old,104,pending,player(pending))
    # Members returned by a discovered legion can extend beyond the initial block.
    info['members'] += [{'id':'11999990','name':'左侧成员','job':9},
                        {'id':'12100010','name':'右侧成员','job':9}]
    db.save_legion(info);task=db.tasks()[0]
    assert (task['range_low'],task['range_high'])==(11999990,12100010)
    assert task['cursor']==103
    index=db.candidate_index(task,pending)
    assert db.receipt(task,index)[0] and db.candidate({**task,'cursor':index})==pending
    # An in-flight reply using the old cursor is remapped after calibration too.
    pid=db.candidate({**old,'cursor':105})
    db.save_receipt(old,105,pid,player(pid))
    assert db.receipt(task,db.candidate_index(task,pid))[0]
    completed=set(db.candidate({**old,'cursor':i}) for i in range(103))
    total=task['range_high']-task['range_low']+1
    rest=[db.candidate({**task,'cursor':i}) for i in range(103,total)]
    assert len(rest)==len(set(rest))
    assert not completed.intersection(rest)
    assert completed.union(rest)==set(range(11999990,12100011))
    again=LegionScanStore(db.path).tasks()[0]
    assert (again['range_low'],again['range_high'],again['cursor'])==(11999990,12100010,103)


def test_refresh_calibrates_using_known_members_of_discovered_legion(tmp_path):
    app=QApplication.instance() or QApplication([])
    panel=LegionScanPanel(tmp_path/'refresh.db');task=panel.db.create_task(guild())
    panel.db.record(12000100,player(12000100,'99'))
    with panel.db.connect() as sql:
        panel.db._player(sql,player(12120000,'99'))
        panel.db._player(sql,player(13000000,'unrelated'))
    panel.refresh()
    task=panel.db.tasks()[0]
    assert task['range_high']==12120000
    assert panel.tree.topLevelItem(0).text(1).startswith('0/119901')
    panel.close()


def test_power_units_and_numeric_sorting(tmp_path):
    from package.plugin_manager.power_format import format_power
    from package.plugin_manager.legion import LegionPanel
    assert format_power(621226869)=='6.21亿'
    assert format_power(123456)=='12.35万'
    assert format_power(0)=='0'
    assert format_power(None)=='—'
    app=QApplication.instance() or QApplication([])
    panel=LegionPanel(SimpleNamespace(path=tmp_path/'config.json'))
    info=guild();info['members'][0]['fightPower']=90000000;info['members'][1]['fightPower']=110000000
    panel.accept(info)
    assert panel.table.item(0,0).text()==info['members'][1]['id']
    assert panel.table.item(0,2).text()=='1.1亿'
    assert '总战力 4亿' in panel.summary.text()
    panel.close()


def test_launch_and_game_restart_automatically_resume_persisted_task(tmp_path):
    app=QApplication.instance() or QApplication([])
    async def run():
        path=tmp_path/'scan.db';db=LegionScanStore(path)
        task=db.create_task(guild());db.record(db.candidate(task),None,task)
        for member in guild()['members']:db.record(int(member['id']),player(member['id']))
        calls=[]
        async def read(lid):calls.append(('legion',lid));return guild(lid)
        async def lookup(op,pid):calls.append(('player',pid));return None
        panel=LegionScanPanel(path)
        panel.db.set_workers(1)
        state=SimpleNamespace(installed='first',closing=False)
        scanner=LegionScanner(SimpleNamespace(legion_read=read,legion_scan_call=lookup),state,panel)
        await scanner.poll();await scanner.wait_operation()
        assert calls==[('legion','42')]
        scanner.next_request=0
        await scanner.poll();await scanner.wait_operation()
        assert calls[-1]==('player','12000101')
        assert db.tasks()[0]['cursor']==2
        state.installed=None
        await scanner.poll();assert len(calls)==2
        state.installed='restarted'
        scanner.next_request=10**20
        await scanner.poll();await scanner.wait_operation()
        assert calls[-1]==('legion','42')
        scanner.next_request=0
        await scanner.poll();await scanner.wait_operation()
        assert calls[-1]==('player','12000102')
        assert db.tasks()[0]['cursor']==3
        panel.close()
    asyncio.run(run())


@pytest.mark.parametrize('base',[10000000,12000100,99999997])
def test_exact_100000_unique_ids_seed_first_then_outwards(tmp_path,base):
    db=LegionScanStore(tmp_path/'scan.db');info=guild()
    for i,m in enumerate(info['members']):m['id']=str(base+i)
    task=db.create_task(info)
    assert (task['range_low'],task['range_high'])==(base,base+2)
    start=base//100000*100000
    task=expand_range(db,start,start+99999)
    ids=[]
    for cursor in range(SCAN_SIZE):
        ids.append(db.candidate({**task,'cursor':cursor}))
    assert ids[:3]==[base,base+1,base+2]
    assert len(set(ids))==SCAN_SIZE
    assert min(ids)>=10000000 and max(ids)<=99999999
    assert db.candidate({**task,'cursor':SCAN_SIZE}) is None
    assert min(ids)==task['range_low'] and max(ids)==task['range_high']
    assert task['range_low']==base//100000*100000
    assert task['range_high']==base//100000*100000+99999


@pytest.mark.parametrize('scanned',[(12324125,12324243),(12274125,12374124),(12324125,12324125),(None,None)])
def test_old_ranges_migrate_to_seed_and_actual_progress(tmp_path,scanned):
    path=tmp_path/'scan.db';db=LegionScanStore(path);info=guild()
    for i,m in enumerate(info['members']):m['id']=str(12324125+i)
    task=db.create_task(info)
    low,high=scanned
    with db.connect() as sql:
        sql.execute('DELETE FROM scan_seed_bounds')
        sql.execute('UPDATE scan_tasks SET range_low=12274125,range_high=12374124,scanned_low=?,scanned_high=?,cursor=? WHERE id=?',
            (low,high,high-low+1 if low is not None else 0,task['id']))
    db=LegionScanStore(path);task=db.tasks()[0]
    expected_low=min(12324125,low if low is not None else 12324125)
    expected_high=max(12324127,high if high is not None else 12324127)
    assert (task['range_low'],task['range_high'])==(expected_low,expected_high)
    done=set(range(low,high+1)) if low is not None else set()
    remaining=[db.candidate({**task,'cursor':i}) for i in range(task['cursor'],expected_high-expected_low+1)]
    assert len(remaining)==len(set(remaining))
    assert not done.intersection(remaining)
    assert done.union(remaining)==set(range(expected_low,expected_high+1))
    assert LegionScanStore(path).tasks()[0]['cursor']==task['cursor']


def test_resume_transaction_missing_ids_and_platform_isolation(tmp_path):
    path=tmp_path/'scan.db';db=LegionScanStore(path)
    task=db.create_task(guild());pid=db.candidate(task)
    db.record(pid,player(pid),task)
    db=LegionScanStore(path);task=db.tasks()[0]
    assert task['cursor']==1 and db.candidate(task)==pid+1
    db.record(pid+1,None,task)
    assert db.tasks()[0]['cursor']==2
    assert db.create_task(guild())['cursor']==2
    with pytest.raises(ValueError):db.record(pid,player(pid),task)
    assert db.tasks()[0]['cursor']==2
    assert LegionScanStore(path,'douyin').tasks()==[]


def test_min_power_persistent_and_priority_updates(tmp_path):
    db=LegionScanStore(tmp_path/'scan.db');db.create_task(guild());db.mark('42',True)
    assert db.min_power()==300000000
    assert db.stale_legion(set())['id']=='42'  # 每次启动即使当天更新也要查询
    assert db.stale_legion({'42'}) is None
    assert db.stale_marked_player() is not None
    db.set_min_power(500000000)
    assert db.stale_legion(set())['id']=='42' and db.stale_marked_player() is not None
    db.mark('42',False)
    assert db.stale_legion(set()) is None and db.stale_marked_player() is None
    assert LegionScanStore(db.path).min_power()==500000000
    db.set_min_power(300000000)
    assert db.stale_legion(set())['id']=='42' and db.stale_marked_player() is not None
    row=db.stale_marked_player();db.record(row['id'],player(row['id']))
    assert db.stale_marked_player()['id']!=row['id']


def test_tree_guild_power_order_servers_and_member_moves(tmp_path):
    db=LegionScanStore(tmp_path/'scan.db');task=db.create_task(guild())
    db.record(12000100,player(12000100,'99',561))
    db.save_legion({**guild('99',900000000),'members':[]})
    groups=db.groups(task['id'])
    assert [r['id'] for r in groups]==['99','42']
    assert db.servers(task['id'])==(541,561)
    assert db.members(task['id'],'99')[0]['id']==12000100
    assert len(db.members(task['id'],'42'))==2


def test_gui_threshold_root_label_sort_and_resume_controls(tmp_path):
    app=QApplication.instance() or QApplication([])
    panel=LegionScanPanel(tmp_path/'scan.db')
    task=panel.db.create_task(guild());panel.refresh()
    root=panel.tree.topLevelItem(0)
    assert root.text(0)=='540–542服 · 测试阴司42'
    panel.expand(root)
    assert '测试阴司42' in root.child(0).text(0)
    panel.expand(root.child(0));assert root.child(0).childCount()==3
    panel.min_power.setValue(5.5);assert panel.db.min_power()==550000000
    panel.tree.setCurrentItem(root);panel.pause();assert panel.db.tasks()[0]['paused']==1
    panel.close()


def test_scheduler_metadata_before_marked_members_before_scan_and_error_resume(tmp_path,caplog):
    app=QApplication.instance() or QApplication([])
    async def run():
        panel=LegionScanPanel(tmp_path/'scan.db');panel.db.create_task(guild());panel.db.mark('42',True)
        panel.db.set_workers(1)
        calls=[]
        async def read(lid):calls.append(('legion',lid));return guild(lid)
        async def lookup(op,pid):calls.append(('player',pid));return player(pid)
        state=SimpleNamespace(installed='session',closing=False)
        transport=SimpleNamespace(legion_read=read,legion_scan_call=lookup)
        scan=LegionScanner(transport,state,panel)
        await scan.step();assert calls==[('legion','42')]
        for _ in range(3):await scan.step()
        assert panel.db.tasks()[0]['cursor']==0
        assert len(calls)==4
        await scan.step();assert panel.db.tasks()[0]['cursor']==1
        async def fail(*args):raise RuntimeError('限流')
        scan.transport.legion_scan_call=fail
        await scan.step();assert panel.db.tasks()[0]['cursor']==1
        assert '限流' in panel.db.tasks()[0]['error']
        assert '阴司扫描接口报错' in caplog.text and '扫描玩家' in caplog.text
        assert any(record.exc_info for record in caplog.records)
        panel.close()
    asyncio.run(run())
