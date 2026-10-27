"""Reopen the release game from WeChat's 最近使用 UI, without URL shortcuts."""
from __future__ import annotations
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
from . import wechat_position_cache as positions

LOG=logging.getLogger('plugin_manager')


def _save_position(kind,value):
    try:positions.save(kind,value)
    except OSError as exc:LOG.warning('微信位置缓存保存失败，仍可正常定位：%s',exc)


async def _recent_ui(mode, sidebar=None, entry_cache=None):
    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    extra=[]
    if sidebar:
        for key in ('x','y','width','height','window_class'):
            extra.extend(['-Sidebar'+''.join(w.title() for w in key.split('_')),str(sidebar[key])])
    with tempfile.TemporaryDirectory(prefix="wechat-entry-") as folder:
        if entry_cache is not None:
            source=Path(folder)/"entry.json"
            source.write_text(json.dumps(entry_cache),encoding="utf-8")
            extra.extend(["-EntryCachePath",str(source)])
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
            if not mode.startswith('Cached'):LOG.error('微信入口识别失败：阶段=%s；诊断=%s',mode,json.dumps(result.get('diagnostics',{}),ensure_ascii=False))
            raise RuntimeError(result.get('message','微信最近使用入口操作失败'))
        if result.get("cache"):_save_position("entry",result["cache"])
        return result

async def _native_ui(mode,label=None,cache=None):
    """Bound the native probe in a child process, including Frida attach/RPC/detach."""
    command=[sys.executable]
    if not getattr(sys,'frozen',False):
        command.append(str(Path(__file__).resolve().parents[2]/'plugin_main.py'))
    command.extend(['--wechat-native-ui',mode])
    if label:command.extend(['--control-label',label])
    with tempfile.TemporaryDirectory(prefix='wechat-native-') as folder:
        result_path=Path(folder)/'result.json'
        command.extend(['--native-result',str(result_path)])
        if cache is not None:
            source=Path(folder)/'positions.json'
            source.write_text(json.dumps(cache),encoding='utf-8')
            command.extend(['--position-cache',str(source)])
        proc=await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            out,err=await asyncio.wait_for(proc.communicate(),timeout=25)
        except BaseException:
            if proc.returncode is None:proc.kill()
            await proc.communicate()
            raise
        try:result=json.loads(result_path.read_text(encoding='utf-8'))
        except (OSError,ValueError,UnicodeError):
            raise RuntimeError('Frida微信控件定位未返回正常结果：'+err.decode('utf-8',errors='replace')[-400:])
        if proc.returncode or not result.get('ok'):raise RuntimeError(result.get('message','Frida微信控件定位失败'))
        if mode in ('Scan','Snapshot'):_save_position('native',result)
        elif result.get('snapshot'):_save_position('native',result['snapshot'])
        if mode in ('Click','CachedClick'):LOG.info('Frida微信控件导航：%s，位置=%s',label,result['control']['screenCenter'])
        elif mode=='Close':LOG.info('微信旧游戏窗口已确认关闭')
        return result


_position_refresh = None


async def _refresh_positions():
    async def native():
        try:await _native_ui('Scan')
        except Exception as exc:LOG.debug('后台原生控件位置更新未完成：%s',exc)
    async def entry():
        try:await _recent_ui('Scan')
        except Exception as exc:LOG.debug('后台游戏入口位置更新未完成：%s',exc)
    await asyncio.gather(native(),entry())


def _start_position_refresh():
    global _position_refresh
    if _position_refresh is None or _position_refresh.done():
        _position_refresh=asyncio.create_task(_refresh_positions(),name='wechat-position-refresh')
    return _position_refresh


async def cancel_position_refresh():
    global _position_refresh
    task=_position_refresh
    _position_refresh=None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)


async def _cached_prepare(cached):
    entry=cached.get('entry')
    if entry:
        try:return await _recent_ui('CachedPrepare',entry_cache=entry)
        except Exception as exc:LOG.debug('缓存游戏入口需更新：%s',exc)
    native=cached.get('native')
    if native:
        labels={c.get('label') for c in native.get('controls',[])}
        label='小程序' if '小程序' in labels else '发现' if '发现' in labels else None
        if label:
            try:
                await _native_ui('CachedClick',label,cache=native)
                if entry:
                    try:return await _recent_ui('CachedPrepare',entry_cache=entry)
                    except Exception:pass
                return await _recent_ui('EntryPrepare')
            except Exception as exc:LOG.debug('缓存微信导航需更新：%s',exc)
    return None


async def _wait_recent():
    for _ in range(10):
        if (await _recent_ui('Probe')).get('found'):return True
        await asyncio.sleep(.3)
    return False


async def _prepare_native_entry(*,force_scan=False):
    if not force_scan:
        cached=positions.load()
        if cached.get('entry') or cached.get('native'):
            _start_position_refresh()
            prepared=await _cached_prepare(cached)
            if prepared:
                LOG.info('微信入口预检查通过：已使用缓存位置，后台更新控件位置')
                return prepared
    # An already-open page needs no native navigation or version-dependent scan.
    if (await _recent_ui('Probe')).get('found'):
        return await _recent_ui('EntryPrepare')
    snapshot=await _native_ui('Snapshot')
    labels={c.get('label') for c in snapshot.get('controls',[])}
    if '小程序' in labels:
        await _native_ui('Click','小程序')
    elif '发现' in labels:
        await _native_ui('Click','发现')
        if await _wait_recent():return await _recent_ui('EntryPrepare')
        # Discover may expose its small-program tab through the embedded web UI.
        snapshot=await _native_ui('Snapshot')
        if any(c.get('label')=='小程序' for c in snapshot.get('controls',[])):
            await _native_ui('Click','小程序')
        else:
            await _recent_ui('Navigate')
    else:
        raise RuntimeError('Frida未找到微信小程序或发现入口；未关闭游戏')
    if not await _wait_recent():raise RuntimeError('点击微信入口后，最近使用页面仍未就绪')
    return await _recent_ui('EntryPrepare')


async def prepare_wechat_game(*,runner=None,sidebar=None):
    if runner:await runner('Prepare')
    else:await _prepare_native_entry()
    LOG.info('微信重开预检查通过：Frida原生控件及最近使用文本入口')


async def reopen_wechat_game(*,runner=None,before_open=None,sidebar=None):
    if runner:
        await runner('WaitClosed')
    else:
        await _prepare_native_entry()
        await _native_ui('Close')
    if before_open:await before_open()
    if runner:
        await runner('Open')
    else:
        await open_wechat_game()
    LOG.info('已点击微信最近使用中的普通版遗弃之地，等待大厅确认')


async def _wait_game_window():
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if (await _native_ui('Status'))['windows']:return True
        await asyncio.sleep(.5)
    return False


async def open_wechat_game():
    cached=positions.load()
    refresh=_start_position_refresh() if cached.get('entry') or cached.get('native') else None
    await _prepare_native_entry()
    if (await _native_ui('Status'))['windows']:
        raise RuntimeError('游戏窗口已经存在，停止重复打开')
    try:
        if cached.get('entry'):
            await _recent_ui('CachedOpen',entry_cache=cached['entry'])
            LOG.info('已使用缓存位置打开游戏，等待窗口确认')
        else:
            await _recent_ui('EntryOpen')
        if await _wait_game_window():return
        raise RuntimeError('15秒内未确认游戏窗口')
    except Exception as exc:
        # A lost acknowledgement or a late window must never cause a second launch.
        if (await _native_ui('Status'))['windows']:return
        LOG.warning('缓存或首次打开游戏未确认：%s；使用新扫描位置重试',exc)
    if refresh is not None:await refresh
    await _prepare_native_entry(force_scan=True)
    if (await _native_ui('Status'))['windows']:return
    await _recent_ui('EntryOpen')
    if await _wait_game_window():return
    raise RuntimeError('重新扫描位置后仍未确认游戏窗口，已结束本轮两次尝试')


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
