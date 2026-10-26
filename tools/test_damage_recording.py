import asyncio
import copy
import json
import subprocess
import threading
from pathlib import Path

import pytest

from package.plugin_manager.damage_report.analysis import RecordingStream,analyze_recording
from package.plugin_manager.damage_report import write_outputs
from tools.test_damage_feature_performance import fixture


@pytest.fixture(scope='module')
def oracle():
    output=subprocess.check_output(['node','tools/test_damage_recording.cjs','--json'],cwd=Path(__file__).resolve().parents[1])
    return json.loads(output)


def test_python_analysis_matches_previous_game_aggregation_and_factors(oracle):
    old=oracle['legacy'];new=analyze_recording(oracle['raw'])
    for key in ('totalDamage','bossDamage','categories','skills','books','branches','activeBranches','perSecondTop','perSecondBossTop','events'):
        assert new['self'][key]==old['self'][key],key
    assert new['pvp']['derived']==old['pvp']['derived']
    assert new['pvp']['attrSeconds']==old['pvp']['attrSeconds']
    assert len(new['self']['factorRows'])==len(old['self']['factorRows'])
    for a,b in zip(new['self']['factorRows'],old['self']['factorRows']):
        for key in ('skillId','category','group','factors','parts','inputs','settlement','formulaMode','damage','hits'):
            assert a[key]==b[key],(key,a,b)
    # No synthetic skills are executed to manufacture a per-second factor.
    assert new['self']['factorSnapshots']==[]
    assert new['self']['curves'][-1]['bossPerSecond']==[40,60,80,10,70]


def delta(raw):
    packet=copy.deepcopy(raw);packet.pop('catalog')
    packet['self'].update(eventStart=len(raw['self']['events']),hitStart=len(raw['self']['hits']),events=[],hits=[])
    packet['pvp'].update(sampleStart=1,attrStart=1,samples=[dict(raw['pvp']['samples'][-1],selfScore=123)],attrSeconds=[])
    return packet


def test_incremental_merge_is_retry_safe_and_keeps_last_sample_correction(oracle):
    stream=RecordingStream();raw=oracle['raw']
    assert stream.cursor('a') is None
    first=stream.merge(raw,'a');cursor=stream.cursor('a')
    assert cursor['self']['events']==5 and not cursor['includeCatalog']
    packet=delta(raw);merged=stream.merge(packet,'a')
    assert merged['self']['events']==first['self']['events']
    assert merged['pvp']['samples'][-1]['selfScore']==123
    assert stream.merge(packet,'a')==merged  # Retrying a response cannot duplicate rows.
    before=stream.cursor('a');bad=copy.deepcopy(packet);bad['self']['eventStart']=999
    with pytest.raises(ValueError):stream.merge(bad,'a')
    assert stream.cursor('a')==before
    assert stream.cursor('new-context') is None
    replacement=copy.deepcopy(raw);replacement['stream']+=1;replacement['self']['events']=[]
    stream.merge(replacement,'a')
    assert stream.cursor('a')['self']['events']==0


def test_incremental_stream_resets_for_new_battle(oracle):
    stream=RecordingStream();stream.merge(oracle['raw'],'a')
    packet=copy.deepcopy(oracle['raw']);packet['self']['instanceId']=99
    packet['self']['events']=packet['self']['events'][:1];packet['self']['hits']=[]
    packet['pvp'].update(instanceKey='new-battle',samples=[],attrSeconds=[])
    result=stream.merge(packet,'a')
    assert len(result['self']['events'])==1 and not result['pvp']['samples']


def test_raw_recording_can_rebuild_json_csv_and_html_offline(oracle,tmp_path):
    outputs=write_outputs(oracle['raw'],tmp_path,'fixture',write_csv=True)
    saved=json.loads(next(p for p in outputs if p.suffix=='.json').read_text(encoding='utf-8'))
    assert saved['recordingSchema']==1 and saved['catalog']
    csv=next(p for p in outputs if p.suffix=='.csv').read_text(encoding='utf-8')
    assert '测试天书' in csv and '雷法尊者' in csv
    html=next(p for p in outputs if p.suffix=='.html').read_text(encoding='utf-8')
    assert '"totalDamage":260' in html
    second=write_outputs(saved,tmp_path,'rebuilt',save_json=False)
    assert second[0].read_text(encoding='utf-8')==html


def test_feature_analyzes_raw_packets_on_worker_and_sends_acknowledged_cursor(oracle,monkeypatch):
    from package.plugin_manager.features import damage
    original=damage.analyze_recording;threads=[];cursors=[];main=threading.get_ident()
    def analyze(data):threads.append(threading.get_ident());return original(data)
    monkeypatch.setattr(damage,'analyze_recording',analyze)
    async def run():
        feature,transport=fixture()
        async def status():return dict(recordOnly=True,hooked=1,sides={'self':dict(instanceId=1,eventCount=transport.count)})
        async def snapshot(cursor=None):
            cursors.append(cursor)
            return oracle['raw'] if cursor is None else delta(oracle['raw'])
        transport.damage_status=status;transport.damage_snapshot=snapshot
        await feature.take();transport.count+=1;feature._next_snapshot=0;await feature.take()
        assert feature._pending['self']['totalDamage']==260
        assert len(feature._pending['self']['events'])==5
        assert cursors[0] is None and cursors[1]['self']['events']==5
    asyncio.run(run())
    assert threads and all(value!=main for value in threads)


def test_native_fast_forward_both_sides_survive_python_analysis():
    output=subprocess.check_output(['node','tools/test_damage_friend_skip.cjs','--record-only','--json'],cwd=Path(__file__).resolve().parents[1])
    data=analyze_recording(json.loads(output))
    for key in ('self','other'):
        assert data[key]['totalDamage']==300 and data[key]['eventCount']==20
        assert sum(row['hits'] for row in data[key]['factorRows'])==20
        assert data[key]['initialAttributes']['attributes']['1']==100
    assert data['pvp']['finalSelfScore']==1300 and data['pvp']['skipped']


def test_bloodmoon_factors_zero_settlement_and_missing_hp_are_processed_offline(oracle):
    raw=copy.deepcopy(oracle['raw']);raw['self']['battleType']=20
    hit=raw['self']['hits'][0]
    hit.update(isSpCrit=True,hitCount=10,spCritAoeLimit=3)
    hit['inputs']['self'].update({'200103':.6,'200107':.4,'200111':.2})
    hit['inputs']['target'].update({'200104':.2,'200108':.1,'200112':.05})
    hit['context'].update(stamina=dict(skillDamage=.8,finalDamage=.7),targetHpCurrent=None)
    data=analyze_recording(raw);factors=data['self']['factorRows'][0]['factors']
    assert factors['season']==pytest.approx(1.4)
    assert factors['spCrit']==pytest.approx(1.45) and factors['spCritAoe']
    assert factors['staminaSkill']==.8 and factors['staminaFinal']==.7
    zero=data['self']['factorRows'][-1]
    assert zero['damage']==0 and zero['factors']['settlement']==0
    assert data['self']['totalDamage']==260


def test_stop_during_background_analysis_cannot_restore_stale_panel_data(oracle,monkeypatch):
    from package.plugin_manager.features import damage
    original=damage.analyze_recording;started=threading.Event();release=threading.Event()
    def analyze(data):
        started.set();assert release.wait(3);return original(data)
    monkeypatch.setattr(damage,'analyze_recording',analyze)
    async def run():
        feature,transport=fixture()
        async def status():return dict(recordOnly=True,hooked=1,sides={'self':dict(instanceId=1,eventCount=1)})
        async def snapshot(cursor=None):return oracle['raw']
        transport.damage_status=status;transport.damage_snapshot=snapshot
        task=asyncio.create_task(feature.take())
        while not started.is_set():await asyncio.sleep(.001)
        feature._capture_generation+=1;release.set();await task
        assert feature._pending is None and feature._last is None
    asyncio.run(run())


def test_catalog_is_prefetched_while_idle_once(oracle):
    async def run():
        feature,transport=fixture();calls=[]
        async def status():return dict(recordOnly=True,hooked=0,sides={})
        async def snapshot(cursor=None):
            calls.append(cursor);packet=copy.deepcopy(oracle['raw']);packet['self']=packet['other']=None
            packet['pvp'].update(instanceKey=None,samples=[],attrSeconds=[])
            return packet
        transport.damage_status=status;transport.damage_snapshot=snapshot
        await feature.take();await feature.take()
        assert len(calls)==1 and feature._pending is None
        assert feature._recording_stream.cursor(transport.context_id)['includeCatalog'] is False
    asyncio.run(run())
