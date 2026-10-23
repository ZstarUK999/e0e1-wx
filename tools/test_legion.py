import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from package.plugin_manager.legion import LegionHistory,LegionPanel

def test_history_and_selector(tmp_path):
    app=QApplication.instance() or QApplication([])
    panel=LegionPanel(SimpleNamespace(path=tmp_path/'plugins.json'))
    row={'id':'123','name':'测试阴司','members':[{'id':'99','name':'甲','fightPower':9},{'id':'98','name':'乙','fightPower':100}]}
    panel.accept(row)
    assert panel.selector.count()==1 and panel.table.rowCount()==2
    assert panel.table.item(0,0).text()=='98'
    assert LegionHistory(tmp_path/'legion_history.json').rows['123']['name']=='测试阴司'
    selected=[];panel.requested.connect(selected.append)
    panel._request();assert selected==['123']
    panel.selector.setEditText('456');panel._request();assert selected[-1]=='456'
    panel.selector.setEditText('-1');panel._request();assert len(selected)==2
    again=LegionPanel(SimpleNamespace(path=tmp_path/'plugins.json'))
    assert again.selected=='123' and again.table.rowCount()==2
    panel.close();again.close()

def test_corrupt_history(tmp_path):
    path=tmp_path/'history.json';path.write_text('bad',encoding='utf-8')
    assert LegionHistory(path).rows=={}
