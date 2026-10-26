"""Progression accounting, realistic S3 regression, GUI and stale-session reads."""
import asyncio
from copy import deepcopy
from datetime import datetime
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from package.plugin_manager.flag_upgrade_model import BEIJING, forecast, defaults, WOOD
from package.plugin_manager.flag_upgrade import FlagUpgradePanel, FlagUpgradeFeature
from package.plugin_manager.store import PluginConfigStore


def timestamp(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=BEIJING).timestamp() * 1000)


def snapshot():
    costs = {10:60,20:120,30:180,40:240,50:300,60:360,70:420,80:480,90:540,
             100:620,110:720,120:820,130:920,140:1020,150:1120}
    stages = []
    distribution = [[3]*10, [3]*9+[2], [1]*3+[2]*2+[3]*5, [1]*3+[0]*7]
    for a, stars in enumerate(distribution):
        for i, star in enumerate(stars):
            stages.append({'id':a*10+i,'areaId':a,'area':str(a),'sort':i+1,'star':star,
                'unlockAt':timestamp('2026-09-29'),
                'rewards':[{WOOD:10,'10079':200}, {WOOD:20,'10079':400}, {WOOD:30,'10079':600}]})
    return {'roleId':'123456', 'platform':'抖音','name':'测试角色','asOf':timestamp('2026-10-26T23:30'),
        'season':{'id':3,'name':'第三赛季','start':timestamp('2026-09-29'),
                  'end':timestamp('2026-12-06T23:59:59'),'shopEnd':timestamp('2026-12-06T23:59:59')},
        'flagLevel':99,'resources':{WOOD:301,'10079':100000,'10003':100000000},
        'stages':stages,'todaySweeps':6,'freeSweeps':3,'paidSweepCosts':[200,400,600],
        'sweeps':[{'stars':0,'rewards':{WOOD:2}}, {'stars':84,'rewards':{WOOD:6}},
                  {'stars':111,'rewards':{WOOD:7}}],
        'levels':[{'level':n,'cost':[{'item':10080,'num':costs[n]}] if n in costs else [],'attrs':[]}
                  for n in range(151)],
        'flags':[], 'attributes':[],
        'bp':{'id':6066,'level':59,'exp':10,'active':[True,False,False],'claimed':[59,59,59],
              'levels':[{'level':n,'exp':100 if n<=50 else 150,
                 'rewards':[[],[{'item':10080,'num':35}] if n%10==9 else [],
                            [{'item':10080,'num':70}] if n%10==9 else []]} for n in range(1,81)]},
        'tasks':[], 'exchange':{'limit':10,'bought':0,'refresh':2,'rewards':{WOOD:20},
            'unlockAt':timestamp('2026-09-29'),'name':'展旗木','consume':[10055,600]},
        'gift':{'limit':2,'bought':0,'refresh':2,'rewards':{WOOD:80,'10079':1500},
            'unlockAt':timestamp('2026-09-29'),'name':'战旗材料礼包','price':12800},
        'battles':[timestamp('2026-10-31T20:00'),timestamp('2026-11-07T20:00'),
                   timestamp('2026-11-14T20:00'),timestamp('2026-11-21T20:00'),timestamp('2026-11-28T20:00')]}


def plan(s):
    return {**defaults(s),'end':'2026-11-28'}


def task(id, metric, kind='season', target=1, score=100, state=0, progress=0):
    return dict(id=id,name=metric,kind=kind,metric=metric,target=target,score=score,state=state,progress=progress)


def test_exact_conversation_no_double_count_current_day_or_first_clear():
    s=snapshot();p=plan(s);original=deepcopy(s)
    r=forecast(s,p)
    assert s==original
    assert r['income']['首通'][WOOD]==810
    assert r['income']['扫荡'][WOOD]==1338
    assert r['initial'][WOOD]+sum(x.get(WOOD,0) for x in r['income'].values())==2449
    assert r['level']==129 and r['resources'][WOOD]==289 and r['gap']==631
    assert next(x['date'] for x in r['rows'] if x['stars']>=111)=='2026-11-04'
    assert next(x['date'] for x in r['rows'] if x['stars']==120)=='2026-11-07'
    assert r['rows'][0]['sweeps']==0 and r['rows'][0]['stars']==84


def test_all_sources_and_weekly_caps_match_4459_not_double_purchase():
    s=snapshot();p=plan(s)
    p.update(active_tracks=[True,True,True],weekly_shop_wood=200,gift_total=10,
             days={'2026-11-23':{'bp':79}})
    r=forecast(s,p)
    assert r['income']['战令'][WOOD]==210
    assert r['income']['商店'][WOOD]==1000
    assert r['income']['礼包'][WOOD]==800
    assert r['level']==149 and r['resources'][WOOD]==359 and r['gap']==761
    s['exchange']['bought']=5;s['gift']['bought']=1
    r=forecast(s,p)
    assert r['income']['商店'][WOOD]==900
    assert r['income']['礼包'][WOOD]==720
    assert any('1个礼包' in w for w in r['warnings'])


def test_beijing_current_day_remaining_and_season_end_clamp():
    s=snapshot();s['todaySweeps']=3
    p=plan(s);p.update(include_today=True,end='2026-10-26',stars_per_day=0)
    r=forecast(s,p)
    assert r['income']['扫荡'][WOOD]==18
    s['asOf']=timestamp('2026-12-06T23:00');p['end']='2026-12-31';p['include_today']=False
    assert forecast(s,p)['end']=='2026-12-06'


def test_daily_quest_requires_affordable_upgrade_and_three_sweeps():
    s=snapshot();s['resources'][WOOD]=0;s['stages']=s['stages'][:28]
    for st in s['stages']:st['star']=3
    s['tasks']=[task(1,'dailyUpgrade','daily',score=30),task(2,'sweeps','daily',target=3,score=30)]
    p=plan(s);p.update(end='2026-10-27',stars_per_day=0)
    r=forecast(s,p)
    assert r['rows'][-1]['earned_xp']==30
    p['sweeps']=2
    assert forecast(s,p)['rows'][-1]['earned_xp']==0


def test_claimed_tasks_and_tracks_not_paid_twice_pending_xp_and_retroactive_unlock():
    s=snapshot();p=plan(s);p.update(end='2026-10-27',stars_per_day=0)
    s['bp']['active']=[True,True,True];p['active_tracks']=s['bp']['active']
    s['bp']['claimed']=[59,49,49]
    s['tasks']=[task(1,'stars',target=81,state=2),task(2,'stars',target=81,state=1)]
    r=forecast(s,p)
    assert r['income']['战令'][WOOD]==105
    assert sum(rw['earned_xp'] for rw in r['rows'])==100
    assert r['rows'][0]['income']['战令']==105


def test_stage_calendar_gates_and_difficulty_rewards():
    s=snapshot();p=plan(s);p.update(end='2026-10-27',stars_per_day=120)
    for st in s['stages']:
        if st['areaId']==3:st['unlockAt']=timestamp('2026-11-01')
    r=forecast(s,p)
    assert r['rows'][-1]['stars']==93
    assert r['income']['首通'][WOOD]==240


def test_real_material_mode_and_daily_extra_sources():
    s=snapshot();p=plan(s);p.update(end='2026-10-27',wood_only=False,stars_per_day=0)
    s['resources'][WOOD]=1000;s['resources']['10003']=0
    s['levels'][100]['cost'].append({'item':10003,'num':21200})
    r=forecast(s,p)
    assert r['level']==99
    p['extra_gold']=21200
    assert forecast(s,p)['level']==109


def test_gift_purchase_counts_for_recharge_quest_without_imaginary_charge():
    s=snapshot();s['tasks']=[task(7,'recharge','weekly',target=3000,score=150)]
    p=plan(s);p.update(end='2026-10-27',gift_total=1)
    r=forecast(s,p)
    assert sum(row['earned_xp'] for row in r['rows'])==150
    p['gift_total']=0
    assert sum(row['earned_xp'] for row in forecast(s,p)['rows'])==0


def test_challenge_tickets_and_gift_date_reservations():
    s=snapshot();s['tickets']=0;s['challenge']=[14001,3,15]
    p=plan(s);p.update(end='2026-10-28',stars_per_day=10,gift_total=1,
                      days={'2026-10-28':{'gifts':1}})
    r=forecast(s,p)
    assert r['rows'][1]['stars']==87 and r['rows'][2]['stars']==90
    assert [row['gift_count'] for row in r['rows']]==[0,0,1]
    assert r['cash_cost']==12800 and r['diamond_cost']==2400
    assert any('探渊券' in w for w in r['warnings'])


def test_daily_ceiling_ignores_legacy_preserve_setting_and_does_not_fake_upgrade_xp():
    s=snapshot();s['resources'][WOOD]=20000
    s['tasks']=[task(1,'dailyUpgrade','daily',score=30),task(2,'sweeps','daily',target=3,score=30)]
    p=plan(s)
    p['preserve_daily']=True
    r=forecast(s,p)
    assert r['rows'][0]['level']==150 and r['level']==150
    assert sum(row['earned_xp'] for row in r['rows'])==33*30


def test_daily_level_is_wood_ceiling_and_unused_wood_cannot_pay_next_break():
    s=snapshot();p=plan(s);p['preserve_daily']=True
    r=forecast(s,p)
    by_level={row['level']: row for row in s['levels']}
    for row in r['rows']:
        if row['level']<150:
            cost=sum(item['num'] for item in by_level[row['level']+1]['cost'] if item['item']==10080)
            assert cost>row['wood']
            assert row['level']%10==9


def test_transport_read_routes_share_script_and_never_execute_actions():
    from package.plugin_manager.transport import PluginTransport
    from package.plugin_manager.douyin import DouyinTransport
    async def run():
        cdp=object.__new__(PluginTransport);cdp.connected=True;cdp.context_id=7
        calls=[]
        async def evaluate(expression, context, **kwargs):
            calls.append((expression,context,kwargs));return {'roleId':'fixture'}
        cdp._evaluate=evaluate
        assert await cdp.flag_upgrade_read()=={'roleId':'fixture'}
        assert 'return await readFlagUpgrade(globalThis)' in calls[0][0]
        assert calls[0][1]==7
        cdp.connected=False
        with pytest.raises(RuntimeError,match='尚未连接'):await cdp.flag_upgrade_read()
        douyin=object.__new__(DouyinTransport)
        async def rpc(op,args,**kwargs):
            calls.append((op,args,kwargs));return {'roleId':'douyin'}
        douyin._rpc=rpc
        assert await douyin.flag_upgrade_read()=={'roleId':'douyin'}
        assert calls[-1][0]=='flag-upgrade-read' and calls[-1][1]=={}
    asyncio.run(run())


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def test_root_node_adjustments_persistence_and_account_isolation(app,tmp_path):
    from package.plugin_manager.window import PluginWindow
    store=PluginConfigStore(tmp_path/'plugins.json')
    window=PluginWindow(store)
    assert window.items['flag_upgrade'].parent() is None
    panel=window.pages['flag_upgrade'];panel.accept(snapshot())
    assert panel.result and panel.calculate.isEnabled()
    panel.end.setDate(QDate(2026,11,28));panel.shop.setValue(200);panel.gifts.setValue(10)
    panel.mid.setChecked(True);panel.best.setChecked(True)
    panel.schedule.item(28,3).setText('79')
    panel.recalculate()
    assert panel.result['level']==149
    assert panel.path.is_file()
    another=deepcopy(snapshot());another['roleId']='different'
    panel.accept(another)
    assert panel.shop.value()==0 and panel.gifts.value()==0
    assert all(panel.schedule.item(i,3).text()=='自动' for i in range(panel.schedule.rowCount()))
    panel.accept(snapshot())
    assert panel.shop.value()==200 and panel.gifts.value()==10
    panel.reset_plan()
    assert panel.shop.value()==0 and panel.schedule.item(28,3).text()=='自动'
    panel.clear_session()
    assert panel.snapshot is None and not panel.pull.isEnabled()
    window.close();window.deleteLater();app.processEvents()


def test_stale_snapshot_after_disconnect_is_discarded_and_close_cancels(app,tmp_path):
    async def run():
        panel=FlagUpgradePanel(PluginConfigStore(tmp_path/'plugins.json'))
        state=SimpleNamespace(installed='one',closing=False)
        gate=asyncio.Event()
        class Transport:
            async def flag_upgrade_read(self):
                await gate.wait();return snapshot()
        feature=FlagUpgradeFeature(Transport(),state,panel)
        feature.request();await asyncio.sleep(0)
        state.installed='two';gate.set();await feature.job
        assert panel.snapshot is None
        gate.clear();feature.request();await asyncio.sleep(0)
        await feature.close()
        assert feature.job.cancelled()
    asyncio.run(run())
