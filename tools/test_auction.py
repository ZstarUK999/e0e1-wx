import asyncio
import ast
import json
import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from package.plugin_manager.auction import AuctionPanel
from package.plugin_manager import build_info
from package.plugin_manager.transport import PluginTransport
from package.plugin_manager.store import PluginConfigStore
from package.plugin_manager.window import PluginWindow
from tools import build_exe


def test_auction_panel():
    app=QApplication.instance() or QApplication([])
    p=AuctionPanel();p.set_ready(True)
    rows=[dict(key='7:0',name='拍品甲',price=100,id=1000000,start=11000,preview=True,result=-1),dict(key='8:0',name='拍品乙',price=200,id=1000001,start=11000,preview=True,result=-1)]
    p.show_status(dict(visible=True,now=10000,rows=rows,jobs=[],running=False))
    for i in range(2):p.table.item(i,0).setCheckState(Qt.Checked)
    calls=[];p.requested.connect(lambda op,args:calls.append((op,args)))
    p.start.click();assert calls==[('arm',{'keys':['7:0','8:0']})]
    p.show_status(dict(visible=True,now=10100,rows=rows,jobs=[],running=True))
    assert len(p.checked)==2 and not p.start.isEnabled()
    p.stop.click();assert calls[-1]==('stop',{})
    assert p.table.item(0,5).text()=='—'
    p.set_ready(False);assert not p.start.isEnabled() and not p.stop.isEnabled()
    p.timer.stop();p.deleteLater();app.processEvents()


def test_release_hidden(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(build_info,'_CACHED',build_info.BuildInfo('release','test',''))
    w=PluginWindow(PluginConfigStore(tmp_path/'config.json'))
    assert 'auction' not in w.pages and 'auction' not in w.items
    w.deleteLater();app.processEvents()
    class Dummy:pass
    try:asyncio.run(PluginTransport.auction_call(Dummy(),'status'))
    except RuntimeError as exc:assert '发行版' in str(exc)
    else:raise AssertionError('release transport must reject auction calls')


def test_build_excludes_release_script(tmp_path):
    for mode in ('release','debug'):
        info=tmp_path/'build.json';info.write_text(json.dumps({'mode':mode}),encoding='utf-8')
        command=build_exe.build_command(windowed=True,onefile=False,exclude_frida=True,keep_cryptography=True,features_file=None,build_file=info,certs_dir=None,exclude_grpc=True)
        included=any('auction_runtime.js' in part for part in command)
        assert included==(mode=='debug')


def test_modified_python_syntax():
    root=Path(__file__).resolve().parents[1]
    for name in ['package/plugin_manager/auction.py','package/plugin_manager/window.py','package/plugin_manager/runtime.py','package/plugin_manager/transport.py','tools/build_exe.py']:
        ast.parse((root/name).read_text(encoding='utf-8'))


def test_audit_persists_once(caplog):
    from package.plugin_manager.auction import AuctionFeature
    from types import SimpleNamespace
    app=QApplication.instance() or QApplication([])
    panel=AuctionPanel()
    feature=AuctionFeature(None,SimpleNamespace(installed=True,closing=False),panel)
    events=[dict(traceId='test-trace',seq=i+1,kind=kind,wallTime=100+i,serverTime=200+i) for i,kind in enumerate(['arm','list-send','list-reply','matched','buy-send','buy-reply','complete'])]
    result=dict(visible=False,rows=[],jobs=[],running=False,now=100,audit=events)
    with caplog.at_level('INFO',logger='plugin_manager'):
        feature._accept(result)
        feature._accept(result)
    messages=[record.message for record in caplog.records if '拍卖助手事件：' in record.message]
    assert len(messages)==len(events)
    for kind in ['list-send','list-reply','matched','buy-send','buy-reply','complete']:
        assert any(kind in message for message in messages)
    panel.timer.stop();panel.deleteLater();app.processEvents()
