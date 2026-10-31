"""血月战场功能的测试：假 transport + 真面板，不连接微信与 CDP。"""
import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from package.plugin_manager.features import SeasonFeature
from package.plugin_manager.panels import BloodmoonPanel
from package.plugin_manager.state import RuntimeState
from package.plugin_manager.store import PluginConfigStore


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeTransport:
    def __init__(self, flags=None, march=None, candidates=None, receipts=None):
        self.calls = []
        self.flags = flags or {"ok": True, "source": "season_map", "server_now": 1, "groups": []}
        self.march = march or {"ok": True, "move": None, "speed_up": {"available": False, "reasons": ["自己不在行军中"], "times": 0}}
        self.candidates = candidates or {"ok": True, "node": {"x": 1, "y": 2}, "self_state": 1,
                                         "self_plan_power": 1000, "attack": [], "defense": []}
        self.receipts = receipts or {}

    async def season_inject(self):
        self.calls.append("season_inject")
        return True

    async def season_call(self, name, payload=None):
        self.calls.append((name, payload))
        if name in ('automationConfigure','automationEvents') and name not in self.receipts:
            return {'ok':True,'events':[],'cursor':0,'attack_status':'JS自主运行',
                    'speed_status':'JS自主运行','attack_latency':{'sample_count':0}}
        if name == "flags":
            return self.flags
        if name == "march":
            return self.march
        if name == "candidates":
            return self.candidates
        if name in self.receipts:
            result = self.receipts[name]
            if name == 'attack' and isinstance(result, dict) and result.get('ok') is True:
                return dict(result, dispatched=True, request_sent=True)
            return result
        return {"ok": True, "dispatched": True, "request_sent": True}


def build(transport, tmp_path):
    store = PluginConfigStore(tmp_path / "plugin.json")
    panel = BloodmoonPanel(store)
    state = RuntimeState()
    state.installed = "resident"
    return SeasonFeature(transport, state, panel, store)


def config(**overrides):
    bloodmoon = {"enabled": True,
                 "flag_probe": {"refresh_seconds": 5, "top_members": 3},
                 "speed_up": {"enabled": False, "max_times": 3, "safety_margin_seconds": 2, "poll_seconds": 2},
                 "attack": {"enabled": False, "power_ratio": 100, "power_limit": 0, "max_battles": 10, "wait_seconds": 3},
                 "stealth_mark": {"enabled": False}}
    bloodmoon.update(overrides)
    return {"bloodmoon": bloodmoon}


def test_flags_grouped_by_legion_and_sorted_by_power(app, tmp_path):
    transport = FakeTransport(flags={"ok": True, "source": "season_map", "groups": [
        {"legionId": 2, "title": "阴司乙", "power": 300, "members": [
            {"roleId": 3, "name": "丙", "power": 50, "flag": "风旗", "flagLv": 2, "stateName": "待命", "stealth": False, "note": "克水旗"},
            {"roleId": 1, "name": "甲", "power": 200, "flag": "水旗", "flagLv": 0, "stateName": "行军", "stealth": True, "note": ""},
        ]},
        {"legionId": 1, "title": "阴司甲", "power": 900, "members": [
            {"roleId": 2, "name": "乙", "power": 800, "flag": "火旗", "flagLv": 1, "stateName": "待命", "stealth": False, "note": ""},
        ]},
    ]})
    feature = build(transport, tmp_path)

    asyncio.run(feature.probe_once())

    rows = feature.panel.probe_tree
    assert rows.topLevelItemCount() == 2
    first = rows.topLevelItem(0)
    assert first.text(0) == "阴司甲（1人）"
    # 组内按战力降序
    second = rows.topLevelItem(1)
    assert [second.child(i).text(0) for i in range(second.childCount())] == ["甲", "丙"]
    assert second.child(0).text(2) == "水旗"
    assert "隐身中" in second.child(0).text(3)
    assert "战旗" in feature.panel.probe_subject.text()


def test_preview_source_says_flags_not_sent(app, tmp_path):
    transport = FakeTransport(flags={"ok": True, "source": "preview_signup", "groups": [
        {"legionId": 7, "title": "本阴司报名（bTime 7）", "power": 0,
         "members": [{"roleId": 11, "name": "#11", "power": 0, "flag": "未下发", "note": "战旗未下发"}]},
    ]})
    feature = build(transport, tmp_path)

    asyncio.run(feature.probe_once())

    assert "战旗未下发" in feature.panel.probe_subject.text()
    assert feature.panel.probe_tree.topLevelItem(0).child(0).text(2) == "未下发"


def test_stealth_marks_follow_master_and_child_switch(app, tmp_path):
    transport = FakeTransport()
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(stealth_mark={"enabled": True})))
    assert ("marks", {"on": True}) in transport.calls

    asyncio.run(feature.poll(config(stealth_mark={"enabled": False})))
    assert ("marks", {"on": False}) in transport.calls
    assert sum(isinstance(c, tuple) and c[0] == "marks" for c in transport.calls) == 2
    assert ("march", {"interval_seconds": 0}) not in transport.calls
    assert ("candidates", {"compact": True}) not in transport.calls
    asyncio.run(feature.poll(config(enabled=False)))
    assert ("stop", None) in transport.calls


def test_config_partial_patch_keeps_sibling_values(app, tmp_path):
    store = PluginConfigStore(tmp_path / "plugin.json")
    store.set_bloodmoon({"speed_up": {"enabled": True}})
    store.set_bloodmoon({"speed_up": {"max_times": 7}})
    speed = store.snapshot()["bloodmoon"]["speed_up"]
    assert speed == {"enabled": True, "max_times": 7, "safety_margin_seconds": 0, "poll_seconds": 2, "interval_seconds": 0}


def test_config_rejects_bad_values(app, tmp_path):
    store = PluginConfigStore(tmp_path / "plugin.json")
    for bad in ({"attack": {"power_ratio": 0}}, {"attack": {"max_battles": -1}},
                {"flag_probe": {"refresh_seconds": 0}}, {"stealth_mark": {"enabled": 1}}):
        with pytest.raises(ValueError):
            store.set_bloodmoon(bad)


def test_disabled_master_switch_does_not_inject(app, tmp_path):
    transport = FakeTransport()
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(enabled=False)))

    assert transport.calls == []


def test_reset_waits_for_action_lock(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    async def scenario():
        async with feature._lock:
            task = asyncio.create_task(feature.handle('reset', {}))
            await asyncio.sleep(0)
            assert not feature.transport.calls
            assert not task.done()
        await task
    asyncio.run(scenario())
    assert ('reset', None) in feature.transport.calls


def test_power_limit_supports_real_game_scale_and_integer_roundtrip(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    value = 12345678901
    feature.store.set_bloodmoon({'attack': {'power_limit': value}})
    feature.panel.sync(feature.store.snapshot())
    assert feature.panel.attack_limit.value() == value
    assert feature.panel._attack_patch()['attack']['power_limit'] == value
    assert type(feature.panel._attack_patch()['attack']['power_limit']) is int


def test_member_summary_honours_top_members_setting(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    feature.store.set_bloodmoon({'flag_probe': {'top_members': 5}})
    members = [{'name': f'm{i}', 'flag': f'f{i}', 'power': 700-i*100} for i in range(7)]
    feature.panel.set_flags([{'title': 'group', 'members': members}], 'source')
    row = feature.panel.probe_tree.topLevelItem(0)
    assert 'm4·f4' in row.text(2) and 'm5·f5' not in row.text(2)
    assert row.childCount() == 7
    assert not row.isExpanded()
    assert '战力 700' in row.text(2)
    row.setExpanded(True)
    assert row.child(6).text(0) == 'm6'


def test_ready_poll_preserves_probe_running_button_state(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    feature.store.set_bloodmoon({'enabled': True})
    feature.panel.set_ready(True)
    feature.panel.set_probe_running(True)
    feature.panel.set_ready(True)
    assert not feature.panel.probe_start.isEnabled()
    assert feature.panel.probe_stop.isEnabled()


def test_decision_log_contains_branch_inputs_and_marks_error(app, tmp_path, caplog):
    from package.plugin_manager.features import season as season_module
    season_module._DECISION_LOG.clear()
    transport = FakeTransport(receipts={'diagnose': {'ok': True, 'mark_error': {'message': 'node destroyed'}}})
    feature = build(transport, tmp_path)
    with caplog.at_level('DEBUG', logger='plugin_manager'):
        asyncio.run(feature.poll(config(stealth_mark={'enabled': True})))
    assert '"max_times": 3' in caplog.text
    assert '"installed": true' in caplog.text
    assert 'node destroyed' in caplog.text


def test_master_off_blocks_manual_probe_and_stops_running_probe(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    feature.panel.set_ready(True)
    assert not feature.panel.probe_start.isEnabled()
    assert not hasattr(feature.panel, "speed_enabled")
    assert not hasattr(feature.panel, "attack_enabled")
    assert not hasattr(feature.panel, "mark_enabled")
    assert feature.panel.diagnose_button.isEnabled()
    asyncio.run(feature.handle('probe', {'on': True}))
    assert not feature.transport.calls
    feature.set_probing(True)
    asyncio.run(feature.poll({'bloodmoon': {'enabled': False}}))
    assert not feature._probing


def test_master_toggle_preserves_parameters_without_child_switches(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    feature.store.set_bloodmoon({'enabled': True, 'speed_up': {'enabled': True}})
    feature.panel.set_ready(True)
    assert not hasattr(feature.panel, "speed_enabled")
    feature.store.set_bloodmoon({'enabled': False})
    assert not hasattr(feature.panel, "speed_enabled")
    assert feature.store.snapshot()['bloodmoon']['speed_up']['enabled'] is True
    assert '全部血月功能暂停' in feature.panel.master_status.text()


def test_new_config_defaults_to_fifteen_speedups(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    assert feature.store.snapshot()['bloodmoon']['speed_up']['max_times'] == 15
    assert feature.panel.speed_times.value() == 15
    assert feature.panel.attack_max.value() == 20
    assert feature.panel.speed_interval.value() == 0
    feature.panel.speed_interval.setValue(7)
    feature.store.set_bloodmoon(feature.panel._speed_patch())
    assert feature.store.snapshot()['bloodmoon']['speed_up']['interval_seconds'] == 7
    with pytest.raises(ValueError):
        feature.store.set_bloodmoon({'speed_up': {'interval_seconds': -1}})


def test_real_power_display_units_preserve_top_three_order(app, tmp_path):
    powers = [123456789, 90000000, 80000000, 99999]
    transport = FakeTransport(flags={'ok': True, 'source': 'season_map', 'groups': [
        {'title': '阴司甲', 'power': sum(powers), 'members': [
            {'roleId': i, 'name': '玩家'+str(i), 'power': power, 'flag': '水旗'}
            for i, power in enumerate(powers)]}]})
    feature = build(transport, tmp_path)
    asyncio.run(feature.probe_once())
    row = feature.panel.probe_tree.topLevelItem(0)
    assert not row.isExpanded()
    assert '1.23亿' in row.text(2) and '玩家2' in row.text(2)
    assert '玩家3' not in row.text(2)
    assert [row.child(i).text(0) for i in range(4)] == ['玩家0','玩家1','玩家2','玩家3']


def test_member_power_labels_distinguish_missing_base_season_and_total():
    row = SeasonFeature._member_row({'name': '甲', 'power': 10000000,
        'season_power': 2000000, 'total_power': 12000000})
    assert row['power'] == '1000.0万'
    assert '赛季战力：200.0万' in row['note']
    assert '综合战力：1200.0万' in row['note']
    assert SeasonFeature._member_row({'power': None})['power'] == '未下发'


def test_routine_decision_logs_are_debug_throttled_and_info_has_no_heartbeat(monkeypatch, caplog):
    from package.plugin_manager.features import season as module
    module._DECISION_LOG.clear()
    clock = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    with caplog.at_level('INFO', logger='plugin_manager'):
        for index in range(100):
            module._decision('poll', {'tick': index})
        module._decision('target_selected', {'roleId': 1})
        clock[0] = 60
        module._decision('target_selected', {'roleId': 1})
        module._decision('target_selected', {'roleId': 2})
    assert '血月决策 poll ' not in caplog.text
    assert sum('target_selected' in record.message for record in caplog.records) == 2
    caplog.clear()
    module._DECISION_LOG.clear()
    clock[0] = 0
    with caplog.at_level('DEBUG', logger='plugin_manager'):
        module._decision('poll', {'tick': 1})
        clock[0] = 10
        module._decision('poll', {'tick': 2})
        clock[0] = 30
        module._decision('poll', {'tick': 3})
    assert len(caplog.records) == 2
    assert all(record.levelname == 'DEBUG' for record in caplog.records)


def test_attack_order_switch_saves_immediately_and_restores(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    panel, store = feature.panel, feature.store
    assert not panel.attack_lowest_first.isChecked()
    assert store.snapshot()['bloodmoon']['attack']['lowest_power_first'] is False
    panel.attack_lowest_first.setChecked(True)
    assert store.snapshot()['bloodmoon']['attack']['lowest_power_first'] is True
    restored = PluginConfigStore(store.path)
    assert restored.snapshot()['bloodmoon']['attack']['lowest_power_first'] is True
    assert BloodmoonPanel(restored).attack_lowest_first.isChecked()
    store.set_bloodmoon({'attack': {'lowest_power_first': False}})
    assert not panel.attack_lowest_first.isChecked()
    assert panel._attack_patch()['attack']['lowest_power_first'] is False


@pytest.mark.parametrize('invalid', [0, 1, 'false', None])
def test_attack_order_requires_boolean(app, tmp_path, invalid):
    feature = build(FakeTransport(), tmp_path)
    with pytest.raises(ValueError, match='lowest_power_first'):
        feature.store.set_bloodmoon({'attack': {'lowest_power_first': invalid}})


@pytest.mark.parametrize('invalid', [True, '0.25', -0.1, 3600.001, float('nan'), float('inf')])
def test_speed_interval_rejects_invalid_numeric_values(app, tmp_path, invalid):
    feature = build(FakeTransport(), tmp_path)
    with pytest.raises(ValueError, match='interval_seconds'):
        feature.store.set_bloodmoon({'speed_up': {'interval_seconds': invalid}})


def test_shared_attack_lead_config_saves_and_restores(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    assert feature.panel.attack_lead.value() == 400
    feature.panel.attack_lead.setValue(750)
    feature.store.set_bloodmoon(feature.panel._attack_patch())
    restored = PluginConfigStore(feature.store.path)
    assert restored.snapshot()['bloodmoon']['attack']['lead_ms'] == 750
    assert BloodmoonPanel(restored).attack_lead.value() == 750
    feature.store.set_bloodmoon({'attack': {'lead_ms': 0}})
    assert feature.panel.attack_lead.value() == 0
    for invalid in (-1, 10001, 0.2, True):
        with pytest.raises(ValueError, match='lead_ms'):
            feature.store.set_bloodmoon({'attack': {'lead_ms': invalid}})


def test_dynamic_lead_switch_persists_and_syncs(app, tmp_path):
    feature=build(FakeTransport(),tmp_path)
    assert feature.store.snapshot()['bloodmoon']['attack']['dynamic_lead'] is False
    feature.panel.attack_dynamic_lead.setChecked(True)
    assert feature.store.snapshot()['bloodmoon']['attack']['dynamic_lead'] is True
    assert feature.panel._attack_patch()['attack']['dynamic_lead'] is True
    restored=type(feature.store)(feature.store.path)
    assert restored.snapshot()['bloodmoon']['attack']['dynamic_lead'] is True
    feature.store.set_bloodmoon({'attack':{'dynamic_lead':False}})
    assert feature.panel.attack_dynamic_lead.isChecked() is False


@pytest.mark.parametrize('invalid', [0, 1, 'true', None])
def test_dynamic_lead_rejects_non_bool(app, tmp_path, invalid):
    feature=build(FakeTransport(),tmp_path)
    with pytest.raises(ValueError, match='dynamic_lead'):
        feature.store.set_bloodmoon({'attack':{'dynamic_lead':invalid}})


def test_attack_interval_roundtrips_ui_and_store(app, tmp_path):
    feature=build(FakeTransport(),tmp_path)
    assert feature.store.snapshot()['bloodmoon']['attack']['interval_ms']==200
    feature.panel.attack_interval.setValue(75)
    feature.store.set_bloodmoon(feature.panel._attack_patch())
    restored=PluginConfigStore(feature.store.path)
    assert restored.snapshot()['bloodmoon']['attack']['interval_ms']==75
    assert BloodmoonPanel(restored).attack_interval.value()==75


@pytest.mark.parametrize('invalid', [0,-1,10001,1.5,True,'200',None])
def test_attack_interval_rejects_invalid_config(app, tmp_path, invalid):
    feature=build(FakeTransport(),tmp_path)
    with pytest.raises(ValueError,match='interval_ms'):
        feature.store.set_bloodmoon({'attack':{'interval_ms':invalid}})


def test_configuration_sent_once_and_events_are_low_frequency(app, tmp_path, monkeypatch):
    clock=[1000.0]
    monkeypatch.setattr('time.monotonic',lambda:clock[0])
    transport=FakeTransport();feature=build(transport,tmp_path)
    setting=config(attack={'enabled':True,'interval_ms':75},speed_up={'enabled':True,'interval_seconds':.25})
    for stamp in (1000,1000.1,1000.2,1000.9,1001,1001.1,1002):
        clock[0]=stamp;asyncio.run(feature.poll(setting))
    names=[c[0] for c in transport.calls if isinstance(c,tuple)]
    assert names.count('automationConfigure')==1
    assert names.count('automationEvents')==2
    assert not set(names)&{'attack','speedUp','candidates','march'}
    payload=next(c[1] for c in transport.calls if isinstance(c,tuple) and c[0]=='automationConfigure')
    assert payload['attack']['interval_ms']==75
    assert payload['speed_up']['interval_seconds']==.25
    assert feature.scan_interval_ms==1000


def test_only_relevant_config_changes_are_sent(app, tmp_path):
    transport=FakeTransport();feature=build(transport,tmp_path)
    setting=config(attack={'enabled':True,'lead_ms':400,'dynamic_lead':False})
    asyncio.run(feature.poll(setting))
    setting['bloodmoon']['flag_probe']['top_members']=10
    asyncio.run(feature.poll(setting))
    assert sum(c[0]=='automationConfigure' for c in transport.calls if isinstance(c,tuple))==1
    setting['bloodmoon']['attack']['dynamic_lead']=True
    asyncio.run(feature.poll(setting))
    assert sum(c[0]=='automationConfigure' for c in transport.calls if isinstance(c,tuple))==2


def test_compact_events_update_ui_and_cursor_once(app, tmp_path, caplog):
    transport=FakeTransport();feature=build(transport,tmp_path)
    result={'ok':True,'events':[{'seq':1,'kind':'battle_entered','detail':{'battles':3}}],
        'cursor':1,'battles':3,'attack_status':'已进入战斗','speed_status':'等待行军',
        'attack_latency':{'sample_count':2,'mean_one_way_ms':50.5},'effective_lead_ms':51}
    with caplog.at_level('INFO',logger='plugin_manager'):
        feature._display_automation(result);feature._display_automation(result)
    assert caplog.text.count('battle_entered')==1
    assert feature._battles==3 and feature._event_cursor==1
    assert 'RTT/2：50.5ms' in feature.panel.attack_latency_status.text()
    assert '51ms' in feature.panel.attack_latency_status.text()
    assert feature.panel.attack_status.text()=='已进入战斗'


def test_event_channel_error_never_sends_attacks_or_replays_config(app, tmp_path, monkeypatch):
    clock=[1000.0];monkeypatch.setattr('time.monotonic',lambda:clock[0])
    class BrokenEvents(FakeTransport):
        async def season_call(self,name,payload=None):
            if name=='automationEvents':self.calls.append((name,payload));raise TimeoutError('busy bridge')
            return await super().season_call(name,payload)
    transport=BrokenEvents();feature=build(transport,tmp_path);setting=config(attack={'enabled':True})
    asyncio.run(feature.poll(setting));clock[0]+=1;asyncio.run(feature.poll(setting))
    names=[c[0] for c in transport.calls if isinstance(c,tuple)]
    assert names.count('automationConfigure')==1
    assert not set(names)&{'attack','speedUp','candidates','march'}
    assert feature._automation_config is not None


def test_failed_configuration_is_retried_without_per_action_commands(app, tmp_path):
    transport=FakeTransport(receipts={'automationConfigure':{'ok':False}});feature=build(transport,tmp_path)
    asyncio.run(feature.poll(config(attack={'enabled':True})))
    assert feature._automation_config is None
    transport.receipts['automationConfigure']={'ok':True}
    asyncio.run(feature.poll(config(attack={'enabled':True})))
    assert feature._automation_config is not None
    assert sum(c[0]=='automationConfigure' for c in transport.calls if isinstance(c,tuple))==2


def test_live_config_switch_pushes_without_waiting_for_poll(app, tmp_path):
    feature=build(FakeTransport(),tmp_path)
    async def scenario():
        feature.store.set_bloodmoon({'enabled':True,'attack':{'enabled':True}})
        await feature.poll(feature.store.snapshot())
        feature.store.set_bloodmoon({'attack':{'enabled':False}})
        await feature._config_task
    asyncio.run(scenario())
    calls=[c[1] for c in feature.transport.calls if isinstance(c,tuple) and c[0]=='automationConfigure']
    assert len(calls)==2 and calls[-1]['attack']['enabled'] is False
    assert calls[0]['controller']==calls[1]['controller']


def test_stop_and_session_reset_discard_configuration_cache(app, tmp_path):
    feature=build(FakeTransport(),tmp_path)
    asyncio.run(feature.poll(config(attack={'enabled':True},speed_up={'enabled':True})))
    assert feature._automation_config is not None
    asyncio.run(feature.poll(config(enabled=False)))
    assert ('stop',None) in feature.transport.calls and feature._automation_config is None
    feature.reset()
    assert feature._event_cursor==0 and not feature._injected


def test_debug_is_file_only_and_challenges_errors_are_console_visible(app, tmp_path):
    import io,logging
    from package.plugin_manager.logging_setup import start_file_logging
    logger=logging.getLogger('plugin_manager');console=io.StringIO()
    handler=logging.StreamHandler(console);logger.addHandler(handler)
    session=start_file_logging(tmp_path/'runtime.log')
    feature=build(FakeTransport(),tmp_path)
    try:
        feature._display_automation({'events':[
            {'seq':1,'kind':'attack_scan','level':'DEBUG','detail':{'message':'高频扫描详情'}},
            {'seq':2,'kind':'challenge_sent','level':'INFO','detail':{'message':'发起挑战','roleId':2}},
            {'seq':3,'kind':'speed_stopped','level':'ERROR','detail':{'reason':'回包异常导致停止'}}], 'cursor':3})
    finally:
        session.close();logger.removeHandler(handler)
    text=(tmp_path/'runtime.log').read_text(encoding='utf-8')
    assert all(message in text for message in ('高频扫描详情','发起挑战','回包异常导致停止'))
    assert '高频扫描详情' not in console.getvalue()
    assert '发起挑战' in console.getvalue() and '回包异常导致停止' in console.getvalue()
    assert session.file_handler.maxBytes==20*1024*1024 and session.file_handler.backupCount==5


def test_script_log_stream_change_resets_event_cursor(app, tmp_path, caplog):
    feature=build(FakeTransport(),tmp_path)
    feature._event_stream='old';feature._event_cursor=500
    with caplog.at_level('INFO',logger='plugin_manager'):
        feature._display_automation({'stream_id':'new','events':[{'seq':1,'kind':'challenge_sent'}],'cursor':1})
    assert 'challenge_sent' in caplog.text
    assert feature._event_stream=='new' and feature._event_cursor==1
