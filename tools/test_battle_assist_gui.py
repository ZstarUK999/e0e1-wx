"""Offline integration: configuration persistence, validation and navigation."""
import os
import json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QSpinBox, QDoubleSpinBox, QPushButton, QLabel

from package.plugin_manager.battle_assist import BOOKS, DEFAULT_TIMING, default_battle_assist, validate_battle_assist
from package.plugin_manager.store import PluginConfigStore, default_config, validate_config
from package.plugin_manager.window import PluginWindow


def test_old_config_gets_disabled_defaults():
    config = default_config()
    config.pop("battle_assist")
    assert validate_config(config)["battle_assist"] == default_battle_assist()


def test_shijue_count_interval_settings(tmp_path):
    defaults=default_battle_assist();defaults.pop('shijue_settings')
    assert validate_battle_assist(defaults)['shijue_settings']=={'count':0,'interval':0.0}
    for key,bad in [('count',True),('count',-1),('interval',float('nan')),('interval',3601)]:
        data=default_battle_assist();data['shijue_settings'][key]=bad
        with pytest.raises(ValueError):validate_battle_assist(data)
    app=QApplication.instance() or QApplication([]);store=PluginConfigStore(tmp_path/'shijue.json');window=PluginWindow(store)
    panel=window.pages['control_chain']
    panel.findChild(QSpinBox,'battle_assist.shijue.count').setValue(3)
    panel.findChild(QDoubleSpinBox,'battle_assist.shijue.interval').setValue(2.5)
    assert PluginConfigStore(store.path).snapshot()['battle_assist']['shijue_settings']=={'count':3,'interval':2.5}
    assert window.pages['battle_assist'].findChild(QSpinBox,'battle_assist.shijue.count').value()==3
    window.deleteLater();app.processEvents()


def test_catalog_matches_all_books_and_shijue():
    fixture = json.loads(Path(__file__).with_name("fixtures").joinpath("battle_books.json").read_text(encoding="utf8"))
    assert {key for key, _, _ in BOOKS} | {111100} == {b["id"] for b in fixture["catalog"]}
    assert len(BOOKS) == 15


def test_old_settings_keep_counts_and_new_books_start_disabled():
    old = default_battle_assist()
    old["books"]["110300"] = {"enabled": True, "count": 7}
    for key in (110100, 110200, 110500, 110600):
        old["books"].pop(str(key))
    restored = validate_battle_assist(old)
    assert restored["books"]["110300"] == {"enabled": True, "count": 7, "interval": 0.0}
    for key in (110100, 110200, 110500, 110600):
        assert restored["books"][str(key)]["enabled"] is False


@pytest.mark.parametrize("value", [True, -1, 21, 2.5, "5"])
def test_invalid_count(value):
    config = default_battle_assist()
    config["books"]["110300"]["count"] = value
    with pytest.raises(ValueError):
        validate_battle_assist(config)


def test_unknown_book_and_runtime_state_rejected():
    config = default_battle_assist()
    config["books"]["999"] = {"enabled": True, "count": 5}
    with pytest.raises(ValueError):
        validate_battle_assist(config)
    config = default_battle_assist()
    config["shijue_running"] = True
    with pytest.raises(ValueError):
        validate_battle_assist(config)


def test_auto_count_supported_without_overwriting_manual_count():
    config = default_battle_assist()
    assert config["books"]["111600"]["count"] == 0
    config["books"]["110300"]["count"] = 7
    checked = validate_battle_assist(config)
    assert checked["books"]["111600"]["count"] == 0
    assert checked["books"]["110300"]["count"] == 7


def test_gui_navigation_and_persistence(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PluginConfigStore(tmp_path / "plugin.json")
    window = PluginWindow(store)
    root = window.items["battle_assist"]
    child = window.items["control_chain"]
    assert root.parent() is None
    assert root.text(0) == "PVE辅助"
    assert child.parent() is root
    assert child.text(0) == "控制链"
    panel = window.pages["control_chain"]
    for key, _, _ in BOOKS:
        assert panel.findChild(QCheckBox, f"battle_assist.{key}.enabled") is not None
        assert panel.findChild(QSpinBox, f"battle_assist.{key}.count") is not None
    assert panel.widget() is not None  # All fifteen rows remain accessible by scrolling.
    panel.findChild(QCheckBox, "battle_assist.enabled").setChecked(True)
    panel.findChild(QCheckBox, "battle_assist.110300.enabled").setChecked(True)
    panel.findChild(QSpinBox, "battle_assist.110300.count").setValue(7)
    panel.findChild(QDoubleSpinBox, "battle_assist.110300.interval").setValue(3.25)
    panel.findChild(QCheckBox, "battle_assist.shijue").setChecked(True)
    saved = PluginConfigStore(store.path).snapshot()["battle_assist"]
    assert saved["books"]["110300"] == {"enabled": True, "count": 7, "interval": 3.25}
    assert saved["enabled"] is True and saved["shijue"] is True
    assert "shijue_running" not in saved
    assert window.pages["battle_assist"].findChild(QSpinBox, "battle_assist.110300.count").value() == 7
    assert window.pages["battle_assist"].findChild(QDoubleSpinBox, "battle_assist.110300.interval").value() == 3.25
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("value", [True,-1,3601,float('nan'),float('inf'),"4",None])
def test_invalid_interval(value):
    data=default_battle_assist()
    data['books']['110300']['interval']=value
    with pytest.raises(ValueError):validate_battle_assist(data)


def test_auto_interval_full_value_and_reset_sync(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=PluginConfigStore(tmp_path/'timing.json')
    window=PluginWindow(store)
    panel=window.pages['control_chain']
    count=panel.findChild(QSpinBox,'battle_assist.111600.count')
    interval=panel.findChild(QDoubleSpinBox,'battle_assist.111600.interval')
    assert panel.findChild(QLabel,'battle_assist.111600.timing_preview') is None
    assert interval.text() == f'释放间隔{20/3}秒'  # Auto count defaults to 3 before any battle.
    count.setValue(3)
    panel.set_timing_preview([{'id':111600,'period':20,'duration':8,'level':8}])
    assert interval.text() == f'释放间隔{20/3}秒'
    interval.setValue(4.25)
    assert interval.text() == '释放间隔4.25秒'
    panel.findChild(QPushButton,'battle_assist.111600.reset_interval').click()
    assert interval.value()==0 and store.snapshot()['battle_assist']['books']['111600']['interval']==0
    assert window.pages['battle_assist'].findChild(QDoubleSpinBox,'battle_assist.111600.interval').value()==0
    assert interval.text() == f'释放间隔{20/3}秒'
    panel.set_timing_preview([])
    assert interval.text() == f'释放间隔{20/3}秒'
    window.deleteLater();app.processEvents()


def test_default_timing_matches_game_config():
    fixture=json.loads(Path(__file__).with_name('fixtures').joinpath('battle_books.json').read_text(encoding='utf8'))
    expected={str(c['book']):(c['period'],c['duration']) for c in fixture['cases']
              if c['level']==8 and not c['awakened'] and c['book']!=111100}
    assert DEFAULT_TIMING==expected


def test_zhongkui_defaults_validation_and_gui_persistence(tmp_path):
    defaults=default_battle_assist()
    assert defaults['zhongkui']=={'enabled':False,'show_monsters':True,'monster_count':5,'unlock_speed':True}
    old=default_battle_assist();old.pop('zhongkui')
    assert validate_battle_assist(old)['zhongkui']==defaults['zhongkui']
    for bad in [0,21,True,'5']:
        data=default_battle_assist();data['zhongkui']['monster_count']=bad
        with pytest.raises(ValueError):validate_battle_assist(data)
    app=QApplication.instance() or QApplication([])
    store=PluginConfigStore(tmp_path/'zk.json');window=PluginWindow(store)
    assert window.items['zhongkui'].text(0)=='钟馗伏魔'
    assert window.items['zhongkui'].parent() is window.items['battle_assist']
    panel=window.pages['zhongkui']
    panel.findChild(QCheckBox,'zhongkui.enabled').setChecked(True)
    panel.findChild(QSpinBox,'zhongkui.monster_count').setValue(7)
    # Saving the old control-chain page must preserve the new module settings.
    window.pages['control_chain'].findChild(QSpinBox,'battle_assist.110300.count').setValue(4)
    saved=PluginConfigStore(store.path).snapshot()['battle_assist']['zhongkui']
    assert saved['enabled'] and saved['monster_count']==7 and saved['unlock_speed']
    window.deleteLater();app.processEvents()


def test_zhongkui_gui_live_monsters_and_stale_snapshot(tmp_path):
    from PySide6.QtWidgets import QTableWidget, QLabel
    app=QApplication.instance() or QApplication([])
    store=PluginConfigStore(tmp_path/'zk-live.json');window=PluginWindow(store)
    panel=window.pages['zhongkui'];table=panel.findChild(QTableWidget,'zhongkui.monsters')
    status=panel.findChild(QLabel,'zhongkui.live_status')
    panel.set_monster_status({'active':True,'monsters':[
        {'name':'妖物甲','wave':2,'hp':125,'max':500,'ratio':.25},
        {'name':'妖物乙','wave':1,'hp':0,'max':100,'ratio':0,'deadUntil':2000}]})
    assert table.rowCount()==2 and table.item(0,0).text()=='妖物甲'
    assert table.item(0,2).text()=='125 / 500' and table.item(0,3).text()=='25.00%'
    assert table.item(1,4).text()=='已死亡' and '第2波' in status.text()
    panel.set_monster_status(None,stale=True)
    assert table.rowCount()==2 and '非实时' in status.text()
    panel.set_monster_status(None)
    assert table.rowCount()==0 and '等待' in status.text()
    window.deleteLater();app.processEvents()
