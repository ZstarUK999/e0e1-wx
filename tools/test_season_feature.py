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
        if name == "flags":
            return self.flags
        if name == "march":
            return self.march
        if name == "candidates":
            return self.candidates
        if name in self.receipts:
            return self.receipts[name]
        return {"ok": True, "confirmed": True}


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


def test_speed_up_clicks_only_when_legal(app, tmp_path):
    transport = FakeTransport(march={"ok": True, "server_now": 1,
                                     "move": {"remain_ms": 60000, "to": {"x": 3, "y": 4}},
                                     "speed_up": {"available": True, "reasons": [], "times": 0}},
                              receipts={"speedUp": {"ok": True, "confirmed": True, "times": 1}})
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(speed_up={"enabled": True, "max_times": 2, "safety_margin_seconds": 2, "poll_seconds": 2})))

    assert ("speedUp", {"safety_margin_seconds": 2, "max_times": 2}) in transport.calls
    assert "已加速" in feature.panel.speed_status.text()


def test_speed_up_stops_on_reject(app, tmp_path):
    transport = FakeTransport(march={"ok": True, "move": {"remain_ms": 60000, "to": {"x": 3, "y": 4}},
                                     "speed_up": {"available": True, "reasons": [], "times": 0}},
                              receipts={"speedUp": {"ok": False, "status": "rejected", "message": "加速道具不足"}})
    feature = build(transport, tmp_path)
    setting = config(speed_up={"enabled": True, "max_times": 5, "safety_margin_seconds": 0, "poll_seconds": 2})

    asyncio.run(feature.poll(setting))
    feature._next_speed = 0.0  # 跳过轮询节流，验证被拒后确实不再点
    asyncio.run(feature.poll(setting))

    assert sum(1 for c in transport.calls if isinstance(c, tuple) and c[0] == "speedUp") == 1
    assert "已停止" in feature.panel.speed_status.text()


def test_attack_picks_strongest_beatable_target(app, tmp_path):
    candidates = {"ok": True, "node": {"x": 1, "y": 2}, "self_state": 1, "self_plan_power": 1000,
                  "attack": [{"roleId": 5, "name": "弱", "power": 400, "planPower": 400, "attackable": True, "reasons": []},
                             {"roleId": 6, "name": "强", "power": 900, "planPower": 900, "attackable": True, "reasons": []},
                             {"roleId": 7, "name": "太强", "power": 2000, "planPower": 2000, "attackable": True, "reasons": []},
                             {"roleId": 8, "name": "同阵营", "power": 100, "planPower": 100, "attackable": False,
                              "reasons": ["同阵营"]}],
                  "defense": []}
    transport = FakeTransport(candidates=candidates, receipts={"attack": {"ok": True, "confirmed": True, "roleId": 6, "name": "强"}})
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(attack={"enabled": True, "power_ratio": 100, "power_limit": 0,
                                            "max_battles": 10, "wait_seconds": 0})))

    attack_calls = [c for c in transport.calls if isinstance(c, tuple) and c[0] == "attack"]
    assert attack_calls and attack_calls[0][1] == {"roleId": 6, "power_ratio": 100, "power_limit": 0}
    assert "已挑战" in feature.panel.attack_status.text()


def test_attack_skips_when_self_not_idle(app, tmp_path):
    transport = FakeTransport(candidates={"ok": True, "self_state": 3, "self_state_name": "战斗",
                                          "self_plan_power": 1000, "attack": [], "defense": []})
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(attack={"enabled": True, "power_ratio": 100, "power_limit": 0,
                                            "max_battles": 0, "wait_seconds": 0})))

    assert not [c for c in transport.calls if isinstance(c, tuple) and c[0] == "attack"]
    assert "战斗" in feature.panel.attack_status.text()


def test_no_second_challenge_before_server_confirms_battle(app, tmp_path):
    candidates = {"ok": True, "node": {"x": 1, "y": 2}, "self_state": 1, "self_plan_power": 1000,
                  "attack": [{"roleId": 6, "name": "强", "power": 900, "planPower": 900, "attackable": True, "reasons": []}],
                  "defense": []}
    transport = FakeTransport(candidates=candidates, receipts={"attack": {"ok": True, "confirmed": True, "roleId": 6, "name": "强"}})
    feature = build(transport, tmp_path)
    setting = config(attack={"enabled": True, "power_ratio": 100, "power_limit": 0, "max_battles": 0, "wait_seconds": 0})

    asyncio.run(feature.poll(setting))
    feature._attack_wait_until = 0.0
    asyncio.run(feature.poll(setting))  # 服务端还没把状态同步成战斗，不能发第二场

    assert sum(1 for c in transport.calls if isinstance(c, tuple) and c[0] == "attack") == 1
    assert "等待服务端同步" in feature.panel.attack_status.text()

    feature.candidates = {"ok": True, "self_state": 3, "self_state_name": "战斗", "self_plan_power": 1000,
                          "attack": [], "defense": []}
    transport.candidates = feature.candidates
    feature._attack_wait_until = 0.0
    asyncio.run(feature.poll(setting))
    assert not feature._attack_pending


def test_stealth_marks_follow_master_and_ignore_legacy_child_switch(app, tmp_path):
    transport = FakeTransport()
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(stealth_mark={"enabled": True})))
    assert ("marks", {"on": True}) in transport.calls

    asyncio.run(feature.poll(config(stealth_mark={"enabled": False})))
    assert ("marks", {"on": False}) not in transport.calls
    assert sum(isinstance(c, tuple) and c[0] == "marks" for c in transport.calls) == 1
    assert ("march", None) in transport.calls
    assert ("candidates", None) in transport.calls
    asyncio.run(feature.poll(config(enabled=False)))
    assert ("stop", None) in transport.calls


def test_config_partial_patch_keeps_sibling_values(app, tmp_path):
    store = PluginConfigStore(tmp_path / "plugin.json")
    store.set_bloodmoon({"speed_up": {"enabled": True}})
    store.set_bloodmoon({"speed_up": {"max_times": 7}})
    speed = store.snapshot()["bloodmoon"]["speed_up"]
    assert speed == {"enabled": True, "max_times": 7, "safety_margin_seconds": 2, "poll_seconds": 2}


def test_config_rejects_bad_values(app, tmp_path):
    store = PluginConfigStore(tmp_path / "plugin.json")
    for bad in ({"attack": {"power_ratio": 0}}, {"attack": {"max_battles": -1}},
                {"flag_probe": {"refresh_seconds": 0}}, {"stealth_mark": {"enabled": 1}}):
        with pytest.raises(ValueError):
            store.set_bloodmoon(bad)


def test_reset_clears_stopped_state(app, tmp_path):
    transport = FakeTransport(march={"ok": True, "move": {"remain_ms": 60000, "to": {"x": 3, "y": 4}},
                                     "speed_up": {"available": True, "reasons": [], "times": 0}},
                              receipts={"speedUp": {"ok": False, "status": "uncertain", "message": "结果未知"}})
    feature = build(transport, tmp_path)
    setting = config(speed_up={"enabled": True, "max_times": 5, "safety_margin_seconds": 0, "poll_seconds": 2})

    asyncio.run(feature.poll(setting))
    assert feature._speed_stopped
    asyncio.run(feature.handle("reset", {}))
    assert not feature._speed_stopped
    assert ("reset", None) in transport.calls


def test_disabled_master_switch_does_not_inject(app, tmp_path):
    transport = FakeTransport()
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(enabled=False)))

    assert transport.calls == []


@pytest.mark.parametrize('op', ['attack', 'speedUp'])
@pytest.mark.parametrize('receipt', [None, [], 'bad receipt', {'ok': True}, {'ok': True, 'confirmed': False}])
def test_action_requires_explicit_confirmation_and_never_retries(app, tmp_path, op, receipt):
    transport = FakeTransport(
        march={'ok': True, 'move': {'remain_ms': 60000}, 'speed_up': {'available': True, 'times': 0}},
        candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
                    'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True}]},
        receipts={op: receipt})
    feature = build(transport, tmp_path)
    setting = config(**({'attack': {'enabled': True}} if op == 'attack' else {'speed_up': {'enabled': True}}))
    asyncio.run(feature.poll(setting))
    feature._next_speed = feature._attack_wait_until = 0
    asyncio.run(feature.poll(setting))
    assert sum(isinstance(c, tuple) and c[0] == op for c in transport.calls) == 1
    assert feature._attack_stopped if op == 'attack' else feature._speed_stopped
    # 总开关同时运行两种自动操作；只检查被测攻击失败时不计场次。
    if op == 'attack':
        assert feature._battles == 0


@pytest.mark.parametrize('op', ['attack', 'speedUp'])
def test_action_transport_timeout_stops_without_replay(app, tmp_path, op):
    class LostReply(FakeTransport):
        async def season_call(self, name, payload=None):
            if name == op:
                self.calls.append((name, payload))
                raise TimeoutError('reply lost after dispatch')
            return await super().season_call(name, payload)
    transport = LostReply(
        march={'ok': True, 'move': {'remain_ms': 60000}, 'speed_up': {'available': True, 'times': 0}},
        candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
                    'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True}]})
    feature = build(transport, tmp_path)
    setting = config(**({'attack': {'enabled': True}} if op == 'attack' else {'speed_up': {'enabled': True}}))
    asyncio.run(feature.poll(setting))
    feature._next_speed = feature._attack_wait_until = 0
    asyncio.run(feature.poll(setting))
    assert sum(isinstance(c, tuple) and c[0] == op for c in transport.calls) == 1
    assert feature._attack_stopped if op == 'attack' else feature._speed_stopped


@pytest.mark.parametrize('mine', [None, 0, -1])
def test_unknown_or_nonpositive_own_power_never_selects_target(mine):
    snapshot = {'self_plan_power': mine, 'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True}]}
    assert SeasonFeature._pick(snapshot, {'power_limit': 10000}) is None


@pytest.mark.parametrize('power', [None, 0, -1])
def test_unknown_or_nonpositive_enemy_power_never_selected(power):
    snapshot = {'self_plan_power': 1000, 'attack': [{'roleId': 6, 'planPower': power, 'attackable': True}]}
    assert SeasonFeature._pick(snapshot, {}) is None


@pytest.mark.parametrize('result', [None, {'ok': False}, 'invalid'])
def test_remote_reset_failure_keeps_local_latch(app, tmp_path, result):
    feature = build(FakeTransport(receipts={'reset': result}), tmp_path)
    feature._speed_stopped = 'unknown speed'
    feature._attack_stopped = 'unknown attack'
    feature._attack_pending = True
    feature._battles = 4
    asyncio.run(feature.handle('reset', {}))
    assert feature._speed_stopped == 'unknown speed'
    assert feature._attack_stopped == 'unknown attack'
    assert feature._attack_pending and feature._battles == 4


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


def test_read_only_transport_failure_can_recover(app, tmp_path):
    class ReadFailure(FakeTransport):
        broken = True
        async def season_call(self, name, payload=None):
            if name == 'candidates' and self.broken:
                raise TimeoutError('read timed out')
            return await super().season_call(name, payload)
    transport = ReadFailure(candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
                                       'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True}]})
    feature = build(transport, tmp_path)
    setting = config(attack={'enabled': True})
    asyncio.run(feature.poll(setting))
    assert not feature._attack_stopped
    transport.broken = False
    feature._attack_wait_until = 0
    asyncio.run(feature.poll(setting))
    assert feature._attack_pending


def test_attack_result_trace_is_logged(app, tmp_path, caplog):
    transport = FakeTransport(
        candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
                    'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True}]},
        receipts={'attack': {'ok': False, 'status': 'rejected', 'message': 'blocked',
                             'trace': [{'stage': 'button_check', 'reason': 'not_interactable'}]}})
    feature = build(transport, tmp_path)
    with caplog.at_level('INFO', logger='plugin_manager'):
        asyncio.run(feature.poll(config(attack={'enabled': True})))
    assert 'roleId=6' in caplog.text
    assert 'ratio=' in caplog.text
    assert 'rejected' in caplog.text and 'not_interactable' in caplog.text
    assert '停止自动攻击' in caplog.text


def test_no_target_reason_uses_absolute_cap():
    snapshot = {'self_plan_power': 1000, 'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True}]}
    assert '1 人战力不低于阈值' in SeasonFeature._no_target_reason(snapshot, {'power_limit': 500})


def test_toggling_does_not_erase_uncertainty_or_pending(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    feature._speed_stopped = 'unknown speed'
    feature._attack_stopped = 'unknown attack'
    feature._attack_pending = True
    feature._battles = 4
    asyncio.run(feature._poll_speed({'speed_up': {'enabled': False}}))
    asyncio.run(feature._poll_attack({'attack': {'enabled': False}}))
    assert feature._speed_stopped == 'unknown speed'
    assert feature._attack_stopped == 'unknown attack'
    assert feature._attack_pending and feature._battles == 4


@pytest.mark.parametrize('self_state', [None, 2, 4])
def test_only_actual_battle_state_confirms_challenge(app, tmp_path, self_state):
    transport = FakeTransport(candidates={'ok': True, 'self_state': self_state})
    feature = build(transport, tmp_path)
    import time
    feature._attack_pending = True
    feature._attack_since = time.monotonic()
    asyncio.run(feature._poll_attack({'attack': {'enabled': True, 'wait_seconds': 5}}))
    assert feature._attack_pending
    assert not feature._attack_seen_battle
    assert not [c for c in transport.calls if isinstance(c, tuple) and c[0] == 'attack']


@pytest.mark.parametrize('self_state', [None, 1, 2])
def test_unconfirmed_challenge_times_out_for_any_nonbattle_state(app, tmp_path, self_state):
    transport = FakeTransport(candidates={'ok': True, 'self_state': self_state})
    feature = build(transport, tmp_path)
    import time
    feature._attack_pending = True
    feature._attack_since = time.monotonic() - 61
    asyncio.run(feature._poll_attack({'attack': {'enabled': True}}))
    assert feature._attack_pending
    assert feature._attack_stopped


def test_ready_after_battle_attacks_without_legacy_wait(app, tmp_path, monkeypatch):
    monkeypatch.setattr('time.monotonic', lambda: 1000.0)
    transport = FakeTransport(candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
        'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True}]})
    feature = build(transport, tmp_path)
    feature._attack_seen_battle = True
    asyncio.run(feature._poll_attack({'attack': {'enabled': True, 'wait_seconds': 60,
        'power_ratio': 10, 'power_limit': 950}}))
    assert ('attack', {'roleId': 6, 'power_ratio': 100, 'power_limit': 950}) in transport.calls
    assert feature._attack_pending


def test_unknown_or_march_after_seen_battle_does_not_start_wait(app, tmp_path):
    feature = build(FakeTransport(candidates={'ok': True, 'self_state': 2}), tmp_path)
    feature._attack_seen_battle = True
    asyncio.run(feature._poll_attack({'attack': {'enabled': True, 'wait_seconds': 5}}))
    assert feature._attack_seen_battle
    assert not [c for c in feature.transport.calls if isinstance(c, tuple) and c[0] == 'attack']


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


def test_zero_rounded_threshold_never_means_unlimited():
    snapshot = {'self_power': 1, 'attack': [{'roleId': 6, 'power': 900, 'attackable': True}]}
    assert SeasonFeature._pick(snapshot, {'power_ratio': 10}) is None


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




@pytest.mark.parametrize('during', ['march', 'candidates', 'speedUp'])
def test_master_disabled_during_await_prevents_next_action(app, tmp_path, during):
    class TurningOff(FakeTransport):
        feature = None
        async def season_call(self, name, payload=None):
            result = await super().season_call(name, payload)
            if name == during:
                self.feature.store.set_bloodmoon({'enabled': False})
            return result
    transport = TurningOff(
        march={'ok': True, 'move': {'remain_ms': 60000}, 'speed_up': {'available': True}},
        candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
            'attack': [{'roleId': 6, 'planPower': 500, 'attackable': True}]})
    feature = build(transport, tmp_path)
    transport.feature = feature
    feature.store.set_bloodmoon({'enabled': True})
    asyncio.run(feature.poll(config()))
    if during == 'candidates':
        assert not any(isinstance(c, tuple) and c[0] in ('attack', 'speedUp') for c in transport.calls)
    if during == 'march':
        assert not any(isinstance(c, tuple) and c[0] == 'speedUp' for c in transport.calls)


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


def test_extra_margin_does_not_attempt_or_latch_stopped(app, tmp_path):
    transport = FakeTransport(march={'ok': True, 'move': {'remain_ms': 11000},
        'speed_up': {'available': True, 'min_remain_seconds': 10}})
    feature = build(transport, tmp_path)
    asyncio.run(feature.poll(config()))
    assert not any(isinstance(c, tuple) and c[0] == 'speedUp' for c in transport.calls)
    assert not feature._speed_stopped


@pytest.mark.parametrize('action', ['speedUp', 'attack'])
@pytest.mark.parametrize('status', ['waiting', 'unavailable'])
def test_unsent_ui_wait_does_not_permanently_stop_automation(app, tmp_path, action, status):
    transport = FakeTransport(
        march={'ok': True, 'move': {'remain_ms': 60000}, 'speed_up': {'available': True}},
        candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
            'attack': [{'roleId': 6, 'planPower': 500, 'attackable': True}]},
        receipts={action: {'ok': False, 'status': status, 'request_sent': False, 'message': 'UI冷却中'}})
    feature = build(transport, tmp_path)
    asyncio.run(feature.poll(config()))
    assert not (feature._speed_stopped if action == 'speedUp' else feature._attack_stopped)
    transport.receipts[action] = {'ok': True, 'confirmed': True, 'times': 1}
    feature._next_speed = feature._attack_wait_until = 0
    asyncio.run(feature.poll(config()))
    assert sum(isinstance(c, tuple) and c[0] == action for c in transport.calls) == 2


def test_sent_unavailable_is_not_retried(app, tmp_path):
    transport = FakeTransport(march={'ok': True, 'move': {'remain_ms': 60000},
        'speed_up': {'available': True}}, receipts={'speedUp': {'ok': False,
        'status': 'unavailable', 'request_sent': True, 'message': '已发请求'}})
    feature = build(transport, tmp_path)
    asyncio.run(feature.poll(config()))
    assert feature._speed_stopped
    feature._next_speed = 0
    asyncio.run(feature.poll(config()))
    assert sum(isinstance(c, tuple) and c[0] == 'speedUp' for c in transport.calls) == 1



def test_battle_end_window_scans_early_but_sends_only_after_idle(app, tmp_path):
    transport = FakeTransport(candidates={'ok': True, 'self_state': 3, 'server_now': 1000000,
        'battle_end_time': 1000200, 'self_plan_power': 1000,
        'attack': [{'roleId': 6, 'planPower': 500, 'attackable': True}]})
    feature = build(transport, tmp_path)
    asyncio.run(feature.poll(config()))
    assert feature.scan_interval_ms == 50
    assert not any(isinstance(c, tuple) and c[0] == 'attack' for c in transport.calls)
    transport.candidates['self_state'] = 1
    transport.candidates['server_now'] = 1000201
    asyncio.run(feature.poll(config()))
    assert ('attack', {'roleId': 6, 'power_ratio': 100, 'power_limit': 0}) in transport.calls
    assert feature.scan_interval_ms == 100



def test_moving_target_rejection_defers_only_target_and_keeps_scanning(app, tmp_path):
    transport = FakeTransport(candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
        'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True},
                   {'roleId': 7, 'planPower': 800, 'attackable': True}]},
        receipts={'attack': {'ok': False, 'status': 'target_unavailable', 'request_sent': True,
            'roleId': 6, 'retry_after_ms': 2000, 'message': '目标行军中'}})
    feature = build(transport, tmp_path)
    asyncio.run(feature.poll(config()))
    assert not feature._attack_stopped
    assert 6 in feature._deferred_targets
    transport.receipts['attack'] = {'ok': True, 'confirmed': True}
    asyncio.run(feature.poll(config()))
    attacks = [c for c in transport.calls if isinstance(c,tuple) and c[0]=='attack']
    assert [c[1]['roleId'] for c in attacks] == [6,7]
    assert feature._attack_pending



def test_member_power_labels_distinguish_missing_base_season_and_total():
    row = SeasonFeature._member_row({'name': '甲', 'power': 10000000,
        'season_power': 2000000, 'total_power': 12000000})
    assert row['power'] == '1000.0万'
    assert '赛季战力：200.0万' in row['note']
    assert '综合战力：1200.0万' in row['note']
    assert SeasonFeature._member_row({'power': None})['power'] == '未下发'



def test_attack_runs_before_speed_probe_and_mark_diagnostics(app, tmp_path):
    transport = FakeTransport(candidates={'ok': True, 'self_state': 1, 'self_plan_power': 1000,
        'attack': [{'roleId': 6, 'planPower': 800, 'attackable': True}]})
    feature = build(transport, tmp_path)
    feature.set_probing(True)
    asyncio.run(feature.poll(config()))
    names = [c[0] for c in transport.calls if isinstance(c,tuple)]
    assert names.index('attack') < names.index('march')
    assert names.index('attack') < names.index('flags')
    assert names.index('attack') < names.index('diagnose')


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
