"""Reopen the release game from WeChat's 最近使用 UI, without URL shortcuts."""
from __future__ import annotations
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import threading

LOG=logging.getLogger('plugin_manager')

async def _image_ui(mode):
    from .wechat_image_launch import run_stage
    cancel = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(run_stage, mode, cancel))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        try:await task
        except Exception:pass
        raise

async def _recent_ui(mode, sidebar=None):
    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    extra=[]
    if sidebar:
        for key in ('x','y','width','height','window_class'):
            extra.extend(['-Sidebar'+''.join(w.title() for w in key.split('_')),str(sidebar[key])])
    proc=await asyncio.create_subprocess_exec(str(executable),'-NoProfile','-NonInteractive','-STA',
        '-File',str(Path(__file__).with_name('wechat_recent.ps1')),'-Mode',mode,*extra,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        out,err=await asyncio.wait_for(proc.communicate(),timeout=20)
    except BaseException:
        if proc.returncode is None:proc.kill()
        await proc.communicate()
        raise
    try:result=json.loads(out.decode('utf-8-sig').strip())
    except (ValueError,UnicodeError):
        raise RuntimeError('微信最近使用入口识别失败：'+err.decode('utf-8',errors='replace')[-600:])
    if proc.returncode or not result.get('ok'):
        LOG.error('微信入口识别失败：阶段=%s；诊断=%s',mode,json.dumps(result.get('diagnostics',{}),ensure_ascii=False))
        raise RuntimeError(result.get('message','微信最近使用入口操作失败'))
    return result

async def prepare_wechat_game(*,runner=None,sidebar=None):
    if runner:await runner('Prepare')
    else:await _image_ui('Prepare')
    LOG.info('微信重开预检查通过：图像匹配入口')

async def reopen_wechat_game(*,runner=None,before_open=None,sidebar=None):
    async def native(mode):return await _image_ui(mode)
    run=runner or native
    await run('WaitClosed')
    if before_open:await before_open()
    await run('Open')
    LOG.info('已点击微信最近使用中的普通版遗弃之地，等待大厅确认')


def capture_wechat_sidebar():
    """Capture only a user-selected cursor point; no game actions or screen capture."""
    import ctypes
    from ctypes import wintypes as W
    import psutil
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetCursorPos.argtypes=[ctypes.POINTER(W.POINT)];user.GetCursorPos.restype=W.BOOL
    user.WindowFromPoint.argtypes=[W.POINT];user.WindowFromPoint.restype=W.HWND
    user.GetAncestor.argtypes=[W.HWND,W.UINT];user.GetAncestor.restype=W.HWND
    user.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
    user.GetClientRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];user.GetClientRect.restype=W.BOOL
    user.ScreenToClient.argtypes=[W.HWND,ctypes.POINTER(W.POINT)];user.ScreenToClient.restype=W.BOOL
    user.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int];user.GetClassNameW.restype=ctypes.c_int
    point=W.POINT()
    if not user.GetCursorPos(ctypes.byref(point)):raise RuntimeError('无法读取鼠标位置')
    window=user.GetAncestor(user.WindowFromPoint(point),2)
    pid=W.DWORD();user.GetWindowThreadProcessId(window,ctypes.byref(pid))
    if psutil.Process(pid.value).name().lower() not in ('weixin.exe','wechat.exe'):
        raise ValueError('鼠标必须位于微信主窗口的小程序侧栏图标上')
    rect=W.RECT();name=ctypes.create_unicode_buffer(256)
    if not user.GetClientRect(window,ctypes.byref(rect)) or not user.ScreenToClient(window,ctypes.byref(point)):
        raise RuntimeError('无法读取微信窗口位置')
    user.GetClassNameW(window,name,256)
    if not (0<=point.x<min(120,rect.right) and 0<=point.y<rect.bottom):
        raise ValueError('请选择微信左侧栏的小程序图标')
    return {'x':point.x,'y':point.y,'width':rect.right,'height':rect.bottom,'window_class':name.value}
