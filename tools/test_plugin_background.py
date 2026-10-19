import os
import subprocess
import sys
import threading
from pathlib import Path
import pytest
from package.plugin_manager.background import BackgroundExecutor

def test_executor_cancels_queued_work_and_rejects_new_jobs():
    gate=threading.Event();started=threading.Event();executor=BackgroundExecutor(1)
    first=executor.submit(lambda:(started.set(),gate.wait(2)))
    assert started.wait(1)
    second=executor.submit(lambda:42)
    executor.shutdown();assert second.cancelled()
    with pytest.raises(RuntimeError):executor.submit(lambda:0)
    gate.set();first.result(1)

def test_closed_qasync_loop_does_not_leave_process_waiting_for_io():
    root=Path(__file__).resolve().parents[1]
    code='''
import asyncio,time
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop
from package.plugin_manager.background import BackgroundExecutor
app=QApplication([])
loop=QEventLoop(app);asyncio.set_event_loop(loop)
loop.set_default_executor(BackgroundExecutor())
async def run():
    # Simulate an HTTP library that ignores async cancellation while blocked.
    loop.run_in_executor(None,time.sleep,60)
    await asyncio.sleep(.05)
with loop:loop.run_until_complete(run())
print('event loop closed')
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
    assert 'event loop closed' in result.stdout
