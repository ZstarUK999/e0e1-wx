"""Root switch persistence and cross-panel compatibility."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QSpinBox
from package.plugin_manager.battle_assist import default_battle_assist, validate_battle_assist
from package.plugin_manager.store import PluginConfigStore
from package.plugin_manager.window import PluginWindow

def test_legacy_speed_defaults_off():
    data=default_battle_assist();data.pop('auto_speed')
    assert validate_battle_assist(data)['auto_speed'] is False

@pytest.mark.parametrize('bad',[0,1,'true',None,{}])
def test_speed_requires_boolean(bad):
    data=default_battle_assist();data['auto_speed']=bad
    with pytest.raises(ValueError):validate_battle_assist(data)

def test_root_speed_survives_other_panels(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=PluginConfigStore(tmp_path/'plugins.json');window=PluginWindow(store)
    root=window.pages['battle_assist'];chain=window.pages['control_chain'];zk=window.pages['zhongkui']
    speed=root.findChild(QCheckBox,'battle_assist.auto_speed')
    assert speed is not None and not speed.isChecked()
    assert "解锁3倍速按钮" in speed.text()
    assert "不会自动切换或锁定倍率" in speed.toolTip()
    assert chain.findChild(QCheckBox,'battle_assist.auto_speed') is None
    speed.setChecked(True)
    chain.findChild(QCheckBox,'battle_assist.enabled').setChecked(True)
    chain.findChild(QSpinBox,'battle_assist.110300.count').setValue(7)
    zk.findChild(QCheckBox,'zhongkui.enabled').setChecked(True)
    assert speed.isChecked() and store.snapshot()['battle_assist']['auto_speed']
    saved=PluginConfigStore(store.path).snapshot()['battle_assist']
    assert saved['auto_speed'] and saved['enabled'] and saved['zhongkui']['enabled']
    assert saved['books']['110300']['count']==7
    saved['auto_speed']=False;store.set_battle_assist(saved);assert not speed.isChecked()
    window.deleteLater();app.processEvents()
