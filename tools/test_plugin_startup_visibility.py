import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

@pytest.mark.skipif(sys.platform!='win32',reason='Windows startup flags')
def test_hidden_launch_restores_own_qt_window(tmp_path):
    pythonw=Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.exists():pytest.skip('pythonw unavailable')
    output=tmp_path/'visible.json'
    script=tmp_path/'window_test.py'
    script.write_text('''import sys,json,ctypes
from pathlib import Path
from PySide6.QtWidgets import QApplication,QMainWindow
from PySide6.QtCore import QTimer
from package.plugin_manager.app import ensure_window_visible
app=QApplication([]);window=QMainWindow();window.setWindowTitle('Plugin startup visibility test')
window.show()
def check():
 try:
  ensure_window_visible(window)
  from ctypes import wintypes
  user32=ctypes.WinDLL('user32');user32.IsWindowVisible.argtypes=[wintypes.HWND]
  Path(sys.argv[1]).write_text(json.dumps({'visible':bool(user32.IsWindowVisible(int(window.winId())))}))
 finally:
  window.close();app.quit()
QTimer.singleShot(0,check)
QTimer.singleShot(3000,app.quit)
app.exec()
''',encoding='utf-8')
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    env=dict(os.environ);env.pop('QT_QPA_PLATFORM',None)
    root=Path(__file__).resolve().parents[1]
    env['PYTHONPATH']=str(root)+os.pathsep+env.get('PYTHONPATH','')
    child=subprocess.Popen([str(pythonw),str(script),str(output)],cwd=root,env=env,startupinfo=startup)
    try:child.wait(timeout=10)
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=3)
    assert child.returncode==0
    assert json.loads(output.read_text())['visible'] is True
