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


def test_stealth_marks_toggle_follows_config(app, tmp_path):
    transport = FakeTransport()
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(stealth_mark={"enabled": True})))
    assert ("marks", {"on": True}) in transport.calls

    asyncio.run(feature.poll(config(stealth_mark={"enabled": False})))
    assert ("marks", {"on": False}) in transport.calls


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


def test_wait_is_measured_from_observed_battle_end(app, tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr('time.monotonic', lambda: clock[0])
    candidates = {'ok': True, 'self_state': 3, 'self_plan_power': 1000,
                  'attack': [{'roleId': 6, 'planPower': 900, 'attackable': True}]}
    transport = FakeTransport(candidates=candidates)
    feature = build(transport, tmp_path)
    feature._attack_pending = True
    feature._attack_since = 999.0
    setting = {'attack': {'enabled': True, 'wait_seconds': 5, 'power_ratio': 80, 'power_limit': 700}}
    asyncio.run(feature._poll_attack(setting))
    assert not feature._attack_pending and feature._attack_seen_battle
    clock[0] = 1100.0
    asyncio.run(feature._poll_attack(setting))
    assert feature._attack_seen_battle
    clock[0] = 1103.0
    transport.candidates['self_state'] = 1
    asyncio.run(feature._poll_attack(setting))
    assert feature._attack_wait_until == 1108.0
    assert not feature._attack_seen_battle
    clock[0] = 1107.9
    asyncio.run(feature._poll_attack(setting))
    assert not [c for c in transport.calls if isinstance(c, tuple) and c[0] == 'attack']
    transport.candidates['attack'][0]['planPower'] = 600
    clock[0] = 1108.0
    asyncio.run(feature._poll_attack(setting))
    assert ('attack', {'roleId': 6, 'power_ratio': 80, 'power_limit': 700}) in transport.calls


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
    members = [{'name': f'm{i}', 'flag': f'f{i}'} for i in range(7)]
    feature.panel.set_flags([{'title': 'group', 'members': members}], 'source')
    row = feature.panel.probe_tree.topLevelItem(0)
    assert 'm4·f4' in row.text(2) and 'm5·f5' not in row.text(2)
    assert row.childCount() == 7


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
    with caplog.at_level('INFO', logger='plugin_manager'):
        asyncio.run(feature.poll(config(stealth_mark={'enabled': True})))
    assert '"max_times": 3' in caplog.text
    assert '"installed": true' in caplog.text
    assert 'node destroyed' in caplog.text


def test_master_off_blocks_manual_probe_and_stops_running_probe(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    feature.panel.set_ready(True)
    assert not feature.panel.probe_start.isEnabled()
    assert not feature.panel.speed_enabled.isEnabled()
    assert feature.panel.diagnose_button.isEnabled()
    asyncio.run(feature.handle('probe', {'on': True}))
    assert not feature.transport.calls
    feature.set_probing(True)
    asyncio.run(feature.poll({'bloodmoon': {'enabled': False}}))
    assert not feature._probing


def test_master_toggle_keeps_child_preferences_and_updates_controls(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    feature.store.set_bloodmoon({'enabled': True, 'speed_up': {'enabled': True}})
    feature.panel.set_ready(True)
    assert feature.panel.speed_enabled.isEnabled()
    feature.store.set_bloodmoon({'enabled': False})
    assert not feature.panel.speed_enabled.isEnabled()
    assert feature.store.snapshot()['bloodmoon']['speed_up']['enabled'] is True
    assert '全部血月功能暂停' in feature.panel.master_status.text()


def test_new_config_defaults_to_fifteen_speedups(app, tmp_path):
    feature = build(FakeTransport(), tmp_path)
    assert feature.store.snapshot()['bloodmoon']['speed_up']['max_times'] == 15
    assert feature.panel.speed_times.value() == 15


