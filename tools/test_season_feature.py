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
                              receipts={"speedUp": {"ok": True, "times": 1}})
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(speed_up={"enabled": True, "max_times": 2, "safety_margin_seconds": 2, "poll_seconds": 2})))

    assert ("speedUp", {"safety_margin_seconds": 2}) in transport.calls
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
    transport = FakeTransport(candidates=candidates, receipts={"attack": {"ok": True, "roleId": 6, "name": "强"}})
    feature = build(transport, tmp_path)

    asyncio.run(feature.poll(config(attack={"enabled": True, "power_ratio": 100, "power_limit": 0,
                                            "max_battles": 10, "wait_seconds": 0})))

    attack_calls = [c for c in transport.calls if isinstance(c, tuple) and c[0] == "attack"]
    assert attack_calls and attack_calls[0][1] == {"roleId": 6}
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
    transport = FakeTransport(candidates=candidates, receipts={"attack": {"ok": True, "roleId": 6, "name": "强"}})
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
