"""Isolated Frida read-only control discovery plus ordinary Windows input/close messages.

Only Weixin 4.1.15.55 x64 is profiled. Each helper owns its Frida session and
always detaches; it never replaces the plugin's WeChatAppEx hooks.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import time
import psutil


def user32():
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetThreadDpiAwarenessContext.argtypes=[W.HANDLE]
    user.SetThreadDpiAwarenessContext.restype=W.HANDLE
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    user.IsWindow.argtypes=[W.HWND];user.IsWindow.restype=W.BOOL
    user.IsIconic.argtypes=[W.HWND];user.IsIconic.restype=W.BOOL
    user.ShowWindowAsync.argtypes=[W.HWND,ctypes.c_int]
    user.SetForegroundWindow.argtypes=[W.HWND]
    user.GetForegroundWindow.restype=W.HWND
    user.GetClientRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
    user.ClientToScreen.argtypes=[W.HWND,ctypes.POINTER(W.POINT)]
    user.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
    user.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
    user.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    user.WindowFromPoint.argtypes=[W.POINT];user.WindowFromPoint.restype=W.HWND
    user.GetAncestor.argtypes=[W.HWND,W.UINT];user.GetAncestor.restype=W.HWND
    user.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
    return user


def game_windows(user=None):
    user=user or user32();windows=[]
    callback_type=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    def accept(hwnd,_):
        title=ctypes.create_unicode_buffer(256)
        user.GetWindowTextW(hwnd,title,256)
        if title.value!='遗弃之地':return True
        pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        try:
            proc=psutil.Process(pid.value)
            path=proc.exe().lower()
            if proc.name().lower()=='wechatappex.exe' and 'radiumwmpf' in path and 'wxwork' not in path:
                windows.append(int(hwnd))
        except (psutil.Error,OSError):pass
        return True
    callback=callback_type(accept)
    user.EnumWindows.argtypes=[callback_type,W.LPARAM];user.EnumWindows.restype=W.BOOL
    if not user.EnumWindows(callback,0):raise RuntimeError('无法枚举游戏窗口')
    return windows


def choose_control(snapshot,label):
    controls=[c for c in snapshot['controls'] if c.get('label')==label]
    # Text children can describe the same clickable parent; collapse matching geometry.
    unique={tuple(c['screenCenter'][k] for k in ('x','y')):c for c in controls}
    if len(unique)!=1:raise RuntimeError(f'微信控件 {label} 匹配到 {len(unique)} 个，停止点击')
    return next(iter(unique.values()))


def click_control(user,snapshot,control):
    hwnd=int(snapshot['hwnd'],16)
    if not user.IsWindow(hwnd) or user.GetForegroundWindow()!=hwnd:
        raise RuntimeError('微信主窗口未在前台，停止点击')
    rect=W.RECT();origin=W.POINT()
    if not user.GetClientRect(hwnd,ctypes.byref(rect)) or not user.ClientToScreen(hwnd,ctypes.byref(origin)):
        raise RuntimeError('微信主窗口位置不可用')
    if ({'x':origin.x,'y':origin.y}!=snapshot['origin'] or
        {'width':rect.right,'height':rect.bottom}!=snapshot['clientSize']):
        raise RuntimeError('微信窗口位置或尺寸已变化，需重新定位')
    point=W.POINT(control['screenCenter']['x'],control['screenCenter']['y'])
    if not (origin.x<=point.x<origin.x+rect.right and origin.y<=point.y<origin.y+rect.bottom):
        raise RuntimeError('控件中心不在微信窗口内')
    if user.GetAncestor(user.WindowFromPoint(point),2)!=hwnd:
        raise RuntimeError('微信控件被其他窗口遮挡，停止点击')
    if not user.SetCursorPos(point.x,point.y):raise RuntimeError('无法移动到微信控件')
    user.mouse_event(2,0,0,0,0);user.mouse_event(4,0,0,0,0)


def run(mode,label=None,cache=None):
    user=user32()
    if mode=='Status':return {'ok':True,'windows':game_windows(user)}
    if mode=='Close':
        windows=game_windows(user)
        if len(windows)>1:raise RuntimeError('检测到多个游戏窗口，无法确定要关闭的实例')
        for hwnd in windows:
            if not user.PostMessageW(hwnd,0x10,0,0):raise RuntimeError('游戏窗口关闭请求失败')
        end=time.monotonic()+15
        while game_windows(user):
            if time.monotonic()>=end:raise RuntimeError('游戏窗口15秒内未关闭，停止重开')
            time.sleep(.2)
        return {'ok':True,'phase':'closed'}
    if mode=='CachedClick':
        if not isinstance(cache,dict):raise RuntimeError('微信位置缓存不存在')
        proc=psutil.Process(int(cache['pid']))
        if proc.name().lower()!='weixin.exe' or proc.create_time()!=cache['processCreatedAt']:
            raise RuntimeError('微信进程已变化，重新扫描位置')
        hwnd=int(cache['hwnd'],16);pid=W.DWORD()
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value!=proc.pid:raise RuntimeError('微信窗口已变化')
        if user.IsIconic(hwnd):user.ShowWindowAsync(hwnd,9)
        user.SetForegroundWindow(hwnd);time.sleep(.2)
        rect=W.RECT();origin=W.POINT()
        if not user.GetClientRect(hwnd,ctypes.byref(rect)) or not user.ClientToScreen(hwnd,ctypes.byref(origin)):
            raise RuntimeError('微信窗口位置不可用')
        if {'width':rect.right,'height':rect.bottom}!=cache['clientSize']:
            raise RuntimeError('微信窗口尺寸已变化，重新扫描位置')
        user.GetDpiForWindow.argtypes=[W.HWND];user.GetDpiForWindow.restype=W.UINT
        if abs(user.GetDpiForWindow(hwnd)/96-float(cache['scaleX']))>.01:
            raise RuntimeError('微信窗口DPI已变化，重新扫描位置')
        previous=choose_control(cache,label)
        control=dict(previous,screenCenter={
            'x':previous['screenCenter']['x']-cache['origin']['x']+origin.x,
            'y':previous['screenCenter']['y']-cache['origin']['y']+origin.y})
        live=dict(cache,origin={'x':origin.x,'y':origin.y})
        click_control(user,live,control)
        return {'ok':True,'label':label,'control':control,'cached':True}
    import frida
    candidates=[p.pid for p in psutil.process_iter(['name','cmdline'])
        if (p.info['name'] or '').lower()=='weixin.exe'
        and not any(a.startswith('--type=') for a in p.info['cmdline'] or [])]
    if len(candidates)!=1:raise RuntimeError('无法唯一识别微信主进程')
    session=frida.get_local_device().attach(candidates[0])
    try:
        script=session.create_script(Path(__file__).with_name('wechat_native_controls.js').read_text(encoding='utf-8'))
        script.load()
        snapshot=script.exports_sync.snapshot()
        snapshot['processCreatedAt']=psutil.Process(candidates[0]).create_time()
        if mode=='Scan':return dict(snapshot,ok=True)
        hwnd=int(snapshot['hwnd'],16)
        if user.IsIconic(hwnd):user.ShowWindowAsync(hwnd,9)
        user.SetForegroundWindow(hwnd)
        time.sleep(.2)
        # Do not use the pre-activation geometry for input.
        snapshot=script.exports_sync.snapshot()
        snapshot['processCreatedAt']=psutil.Process(candidates[0]).create_time()
        if mode=='Click':
            control=choose_control(snapshot,label)
            click_control(user,snapshot,control)
            return {'ok':True,'label':label,'control':control,'snapshot':snapshot}
        return dict(snapshot,ok=True)
    finally:
        session.detach()


def helper_main(mode,label=None,result_path=None,cache_path=None):
    try:
        cache=json.loads(Path(cache_path).read_text(encoding="utf-8")) if cache_path else None
        result=run(mode,label,cache=cache) if cache_path else run(mode,label)
        code=0
    except Exception as exc:
        result={'ok':False,'message':str(exc)}
        code=1
    payload=json.dumps(result,ensure_ascii=True)
    if result_path:
        # Windowed PyInstaller executables have no stdout, even as a helper.
        Path(result_path).write_text(payload,encoding='utf-8')
    else:
        import sys
        if sys.stdout is not None:print(payload,flush=True)
    return code
