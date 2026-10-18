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

    reports = list(tmp_path.glob("*vs*_*.html"))
    assert len(reports) == 1
    assert panel._report_path == reports[0]


def test_damage_hint_warns_about_skipping_on_unsupported_modes(app, tmp_path):
    feature, _, _, _ = _feature(app, tmp_path, DamageFeature, DamagePanel)
    assert "好友切磋" in feature.hint(PVP_SNAPSHOT)
    other = {"pvp": {"skipped": True, "battleTypeName": "斗法"}}
    assert "只能拿到跳过之前" not in feature.hint(other)   # skipped 分支
    assert "服务端结算" in feature.hint(other)
    assert "好友切磋" in feature.hint({})                 # 还没进对局时的引导



def test_damage_report_preserves_replay_and_fashion_metadata():
    from package.plugin_manager.damage_report.serialize import slim
    player = {'name': '甲', 'fashions': [{'id': 5001, 'name': '雷法尊者'}]}
    side = {'battleType': 20, 'replay': {'isReplay': True, 'sessionId': 1},
            'players': {'self': player}, 'categories': [{'key': 'leifa', 'dmg': 123}]}
    result = slim({'mode': 'pvp', 'self': side, 'other': side}, False)
    assert result['replay']['isReplay'] is True
    assert result['players']['self']['fashions'][0]['name'] == '雷法尊者'
    assert result['other']['categories'][0]['key'] == 'leifa'


def test_damage_report_keeps_both_sides_factor_history_without_raw_events():
    from package.plugin_manager.damage_report import build_html, slim
    row = {'sec': 3, 'group': 'book', 'factors': {'damage': 1.5}, 'sourceRef': 0}
    sources = [{'self': {'104': [{'label': '实际 Buff', 'value': 0.5}]}}]
    side = {'factorRows': [row], 'factorSources': sources, 'factorsTruncated': False,
            'events': [{'dmg': 10}]}
    pvp = {'attrSeconds': [{'sec': 3, 'self': {'104': 0.5}, 'selfSources': sources[0]['self']}]}
    result = slim({'mode': 'pvp', 'self': side, 'other': side, 'pvp': pvp}, False)
    for payload in (result, result['other']):
        assert payload['factorRows'] == [row]
        assert payload['factorSources'] == sources
        assert payload['factorsTruncated'] is False
        assert 'events' not in payload
    assert result['pvp']['attrSeconds'][0]['selfSources'] == sources[0]['self']
    html = build_html(result)
    assert 'factor-all-seconds' in html
    assert '实际 Buff' in html


def test_damage_archives_have_match_names_and_do_not_overwrite(tmp_path):
    import json
    from package.plugin_manager.damage_report import write_outputs
    data = {'mode': 'pvp', 'self': {'players': {'self': {'name': '玩家甲:/..'}, 'other': {'sName': '玩家乙?'}}, 'events': []}}
    first = write_outputs(data, tmp_path, '20261017_120000', write_csv=True)
    second = write_outputs(data, tmp_path, '20261017_120000', write_csv=True)
    assert len({p.stem for p in first}) == 1
    assert len({p.stem for p in second}) == 1
    assert first[0].stem != second[0].stem
    assert first[0].name.startswith('玩家甲__vs玩家乙__20261017_120000')
    assert all(p.exists() and p.parent == tmp_path for p in first + second)
    assert json.loads(first[0].read_text(encoding='utf-8')) == data
    assert first[-1].suffix == second[-1].suffix == '.html'


def test_damage_history_defaults_to_latest_and_opens_selected_report(app, tmp_path):
    from PySide6.QtCore import Qt
    directory = tmp_path / 'logs' / 'damage_reports'
    directory.mkdir(parents=True)
    old = directory / '甲vs乙_20261016.html'
    new = directory / '丙vs丁_20261017.html'
    legacy = directory.parent / 'damage_curve_20261015.html'
    unrelated = directory.parent / 'desire_report.html'
    for index, path in enumerate((legacy, old, new, unrelated)):
        path.write_text('<html></html>', encoding='utf-8')
        os.utime(path, (100 + index, 100 + index))
    panel = DamagePanel(PluginConfigStore(tmp_path / 'plugins.json'))
    panel.set_report_directory(directory)
    assert panel._report_path == new
    assert panel.open_button.isEnabled()
    assert panel.report_history.topLevelItemCount() == 3
    chosen = panel.report_history.topLevelItem(1)
    panel.report_history.setCurrentItem(chosen)
    assert panel._report_path == old
    opened = []
    panel.open_report_requested.connect(lambda: opened.append(panel._report_path))
    panel.report_history.itemDoubleClicked.emit(chosen, 0)
    assert opened == [old]
    panel.refresh_report_history()
    assert panel._report_path == old
    panel.refresh_report_history(preferred=new)
    assert panel._report_path == new
    for path in (legacy, old, new):
        path.unlink()
    panel.refresh_report_history()
    assert panel._report_path is None
    assert not panel.open_button.isEnabled()


def test_damage_report_rerender_keeps_named_archive_pair(tmp_path):
    from package.plugin_manager.damage_report import write_outputs
    data = {'self': {'players': {'self': {'name': '甲'}, 'other': {'name': '乙'}}}}
    original = write_outputs(data, tmp_path, '20261017_120000')
    rerendered = write_outputs(data, tmp_path, '', save_json=False, basename=original[0].stem)
    assert rerendered == [original[-1]]
    assert len(list(tmp_path.glob('*.json'))) == len(list(tmp_path.glob('*.html'))) == 1


def test_damage_report_preserves_per_second_formula_snapshots():
    from package.plugin_manager.damage_report.serialize import slim

    sample = {"sec": 0, "sampleKind": "second", "factors": {"attack": 100, "coefficient": None}}
    data = {"mode": "pvp", "self": {"factorSnapshots": [sample]}, "other": {"factorSnapshots": [sample]}}
    payload = slim(data, False)
    assert payload["factorSnapshots"] == [sample]
    assert payload["other"]["factorSnapshots"] == [sample]
