"""摸金与伤害两个功能插件的测试：假 transport + 真面板，不连接微信与 CDP。"""
import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from package.plugin_manager.features import DamageFeature, TreasureFeature
from package.plugin_manager.panels import DamagePanel, TreasurePanel
from package.plugin_manager.state import RuntimeState
from package.plugin_manager.store import PluginConfigStore


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.hooked = 1
        self.snapshot = {}

    async def treasure_inject(self):
        self.calls.append("treasure_inject")

    async def treasure_dump(self):
        self.calls.append("treasure_dump")
        return {"layers": [{"layerId": 2, "rows": 2, "cols": 2, "ascii": ["ab", "cd"]}],
                "members": [{"name": "甲"}]}

    async def treasure_overlay(self, on):
        self.calls.append(("overlay", on))
        return "标注已开" if on else "标注已关"

    async def treasure_status(self):
        self.calls.append("status")
        return "当前不在摸金"

    async def damage_inject(self):
        self.calls.append("damage_inject")
        return {"message": "已注入"}

    async def damage_status(self):
        return {"hooked": self.hooked}

    async def damage_snapshot(self):
        return self.snapshot

    async def damage_debug(self):
        return {"hook": True}

    async def damage_reset(self):
        return "已清空"

    async def damage_stop(self):
        self.calls.append("damage_stop")
        return "已停止"


PVP_SNAPSHOT = {
    "mode": "pvp",
    "pvp": {"finalSelfScore": 3.0, "finalOtherScore": 2.0, "winLine": 5, "skipSafe": True,
            "battleType": 26, "attrSeconds": [], "derived": [{"sec": 1, "share": 0.6, "weight": 1.0}]},
    "self": {"eventCount": 3, "totalDamage": 100, "instanceId": 9, "battleTypeName": "好友切磋",
             "categories": [{"label": "天书", "dmg": 60}], "books": [], "skills": [], "activeBranches": []},
}


def _feature(app, tmp_path, cls, panel_cls):
    store = PluginConfigStore(tmp_path / "plugins.json")
    panel = panel_cls(store)
    state = RuntimeState()
    state.installed = "resident-1"
    return cls(FakeTransport(), state, panel, store) if cls is DamageFeature else cls(FakeTransport(), state, panel), state, panel, store


def test_treasure_renders_layers_and_raw_dump(app, tmp_path):
    feature, state, panel, _ = _feature(app, tmp_path, TreasureFeature, TreasurePanel)
    text, subject = feature.render({"layers": [{"layerId": 2, "rows": 2, "cols": 2, "ascii": ["ab", "cd"]}],
                                    "members": [{"name": "甲"}]})
    assert "第2层 2×2" in text and "x=0 | ab" in text and "甲" in text
    assert "1层 / 4格" in subject
    assert feature.render("原始数据")[1] == "摸金地图（原始回执）"


def test_treasure_requests_need_live_session(app, tmp_path):
    feature, state, panel, _ = _feature(app, tmp_path, TreasureFeature, TreasurePanel)
    state.installed = None
    feature.request("dump")
    assert "需要游戏与插件就绪" in panel.message.text()
    assert feature.transport.calls == []


def test_treasure_poll_injects_once_and_toggles_overlay(app, tmp_path):
    feature, state, panel, _ = _feature(app, tmp_path, TreasureFeature, TreasurePanel)
    config = {"treasure": {"enabled": True, "overlay": True, "auto_dump": True, "refresh_seconds": 30}}

    async def run():
        await feature.poll(config)
        await feature.poll(config)
        await feature.poll({"treasure": {"enabled": True}})
    asyncio.run(run())

    assert feature.transport.calls.count("treasure_inject") == 1
    assert ("overlay", True) in feature.transport.calls
    assert ("overlay", False) in feature.transport.calls   # 关掉开关后同步回页面
    assert panel.text.toPlainText().startswith("第2层")


def test_damage_poll_stops_collection_when_disabled(app, tmp_path):
    feature, state, panel, _ = _feature(app, tmp_path, DamageFeature, DamagePanel)

    async def run():
        await feature.poll({"damage": {"enabled": True, "auto_csv": False}})
        assert feature._injected
        await feature.poll({"damage": {"enabled": False}})
    asyncio.run(run())

    assert feature.transport.calls.count("damage_stop") == 1
    assert not feature._injected
    assert panel.status.text() == "未启用（打开开关后自动开始）"


def test_damage_take_writes_report_when_battle_ends(app, tmp_path, monkeypatch):
    feature, state, panel, _ = _feature(app, tmp_path, DamageFeature, DamagePanel)
    from package.plugin_manager.features import damage as damage_module
    monkeypatch.setattr(damage_module, "REPORT_DIR", tmp_path)
    feature.transport.snapshot = dict(PVP_SNAPSHOT)

    async def run():
        await feature.take()
        assert "好友切磋" in panel.status.text()
        feature.transport.hooked = 0
        await feature.take()
    asyncio.run(run())

    reports = list(tmp_path.glob("damage_curve_*.html"))
    assert len(reports) == 1
    assert panel._report_path == reports[0]


def test_damage_hint_warns_about_skipping_on_unsupported_modes(app, tmp_path):
    feature, _, _, _ = _feature(app, tmp_path, DamageFeature, DamagePanel)
    assert "好友切磋" in feature.hint(PVP_SNAPSHOT)
    other = {"pvp": {"skipped": True, "battleTypeName": "斗法"}}
    assert "只能拿到跳过之前" not in feature.hint(other)   # skipped 分支
    assert "服务端结算" in feature.hint(other)
    assert "好友切磋" in feature.hint({})                 # 还没进对局时的引导
