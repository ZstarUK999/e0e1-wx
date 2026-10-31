"""Cached Windows input, with persistent read-only Frida discovery as the fallback.
One session/script per live Weixin process; no background scanning.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import time
import threading
import psutil


def user32():
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetThreadDpiAwarenessContext.argtypes=[W.HANDLE]
    user.SetThreadDpiAwarenessContext.restype=W.HANDLE
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    user.IsWindow.argtypes=[W.HWND];user.IsWindow.restype=W.BOOL
    user.IsIconic.argtypes=[W.HWND];user.IsIconic.restype=W.BOOL
    user.IsWindowVisible.argtypes=[W.HWND];user.IsWindowVisible.restype=W.BOOL
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


def wechat_window_pids(user):
    """Window ownership disambiguates bootstrap/helpers, including minimized windows."""
    if user is None:return set()
    pids=set()
    callback_type=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    def accept(hwnd,_):
        title=ctypes.create_unicode_buffer(256)
        user.GetWindowTextW(hwnd,title,256)
        if title.value in ('微信','WeChat','Weixin') and (user.IsWindowVisible(hwnd) or user.IsIconic(hwnd)):
            pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value:pids.add(pid.value)
        return True
    callback=callback_type(accept)
    user.EnumWindows.argtypes=[callback_type,W.LPARAM];user.EnumWindows.restype=W.BOOL
    if not user.EnumWindows(callback,0):raise RuntimeError('无法枚举微信主窗口')
    return pids


def select_wechat_pid(processes,window_pids):
    rows=[]
    for process in processes:
        try:
            info=process.info
            if (info.get('name') or '').casefold()=='weixin.exe':
                rows.append((process.pid,info.get('cmdline')))
        except (psutil.Error,OSError):continue
    owners={pid for pid,_ in rows if pid in window_pids}
    if len(owners)==1:return next(iter(owners))
    if len(owners)>1:
        raise RuntimeError('检测到多个微信主窗口所属进程：'+','.join(map(str,sorted(owners))))
    # During window creation, use a unique non-helper process as a bounded fallback.
    candidates=[]
    for pid,args in rows:
        if args is None:continue
        if not any(str(arg).casefold()=='--type' or str(arg).casefold().startswith('--type=') for arg in args):
            candidates.append(pid)
    if len(candidates)==1:return candidates[0]
    if not rows:
        raise RuntimeError('微信主进程尚未运行或正在退出／更新，请打开微信，插件将自动重试')
    if not candidates:
        raise RuntimeError('微信主窗口尚未就绪，仅检测到辅助进程，等待自动重试')
    raise RuntimeError('微信主窗口尚未就绪，存在多个候选进程：'+','.join(map(str,sorted(candidates))))


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


def main_geometry(user,pid):
    """Query Windows in the helper, never by calling user32 from injected JS."""
    windows=[]
    callback_type=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    def accept(hwnd,_):
        title=ctypes.create_unicode_buffer(256);owner=W.DWORD()
        user.GetWindowTextW(hwnd,title,256)
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if (owner.value==pid and title.value in ('微信','WeChat','Weixin') and
                (user.IsWindowVisible(hwnd) or user.IsIconic(hwnd))):windows.append(int(hwnd))
        return True
    callback=callback_type(accept)
    user.EnumWindows.argtypes=[callback_type,W.LPARAM];user.EnumWindows.restype=W.BOOL
    if not user.EnumWindows(callback,0) or len(windows)!=1:
        raise RuntimeError('微信主窗口未唯一就绪，未执行原生控件扫描')
    hwnd=windows[0];rect=W.RECT();origin=W.POINT()
    if not user.GetClientRect(hwnd,ctypes.byref(rect)) or not user.ClientToScreen(hwnd,ctypes.byref(origin)):
        raise RuntimeError('微信主窗口位置不可用')
    user.GetDpiForWindow.argtypes=[W.HWND];user.GetDpiForWindow.restype=W.UINT
    return dict(hwnd=hex(hwnd),origin=dict(x=origin.x,y=origin.y),
                clientSize=dict(width=rect.right,height=rect.bottom),scale=user.GetDpiForWindow(hwnd)/96)


def probe_trace(phase, **details):
    from .wechat_position_cache import cache_path
    from datetime import datetime
    path=cache_path().with_name('wechat_native_probe.log')
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.stat().st_size>1024*1024:
            path.replace(path.with_suffix('.previous.log'))
        with path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(time=datetime.now().astimezone().isoformat(),phase=phase,**details),ensure_ascii=True)+'\n')
    except OSError:pass


class NativeProbe:
    """One session and script for the current Weixin process lifetime."""
    def __init__(self):
        self.lock=threading.RLock()
        self.identity=None
        self.session=None
        self.script=None

    def close(self):
        with self.lock:
            script,session=self.script,self.session
            self.script=self.session=self.identity=None
            if script is not None:
                try:script.unload()
                except Exception:pass
            if session is not None:
                try:session.detach()
                except Exception:pass

    def snapshot(self,pid,created,layout,geometry):
        with self.lock:
            invalid=(self.session is None or getattr(self.session,'is_detached',False) or
                     self.script is None or getattr(self.script,'is_destroyed',False))
            if self.identity!=(pid,created) or invalid:
                self.close()
                import frida
                probe_trace('attach-start',pid=pid)
                try:
                    self.session=frida.get_local_device().attach(pid)
                    if hasattr(self.session,'on'):
                        self.session.on('detached',lambda reason,crash=None:probe_trace(
                            'detached',pid=pid,reason=str(reason),crash=str(crash) if crash else None))
                    self.script=self.session.create_script(Path(__file__).with_name('wechat_native_controls.js').read_text(encoding='utf-8'))
                    if hasattr(self.script,'on'):
                        def message(value,data):
                            if value.get('type')=='send' and isinstance(value.get('payload'),dict):
                                payload=dict(value['payload']);phase=payload.pop('phase','script-message')
                                probe_trace(phase,pid=pid,**payload)
                            elif value.get('type')=='error':probe_trace('script-error',pid=pid,error=value.get('stack') or value.get('description'))
                        self.script.on('message',message)
                    self.script.load()
                    self.identity=(pid,created)
                    probe_trace('script-loaded',pid=pid)
                except BaseException:
                    self.close()
                    raise
            return self.script.exports_sync.snapshot(layout,geometry)


_probe=NativeProbe()


def close():
    _probe.close()


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
    if mode in ('CachedClick','CachedEntryClick'):
        if not isinstance(cache,dict):raise RuntimeError('微信位置缓存不存在')
        proc=psutil.Process(int(cache['pid']))
        created=(float(cache['processCreatedAt']) if mode=='CachedClick' else
                 (int(cache['processStart'])-621355968000000000)/10000000)
        if proc.name().lower()!='weixin.exe' or abs(proc.create_time()-created)>.001:
            raise RuntimeError('微信进程已变化，重新扫描位置')
        geometry=main_geometry(user,proc.pid)
        hwnd=int(geometry['hwnd'],16)
        if user.IsIconic(hwnd):user.ShowWindowAsync(hwnd,9)
        user.SetForegroundWindow(hwnd)
        time.sleep(.2)
        geometry=main_geometry(user,proc.pid)
        if mode=='CachedEntryClick':
            size={'width':cache['width'],'height':cache['height']}
            if int(cache['hwnd'])!=hwnd or abs(geometry['scale']-cache['dpi']/96)>.01:
                raise RuntimeError('缓存游戏窗口或DPI已变化')
            point={'x':round(geometry['origin']['x']+cache['x']),
                   'y':round(geometry['origin']['y']+cache['y'])}
            control={'label':label,'screenCenter':point}
        else:
            size=cache['clientSize']
            if int(cache['hwnd'],16)!=hwnd or any(
                    abs(geometry['scale']-cache.get(key,geometry['scale']))>.01 for key in ('scaleX','scaleY')):
                raise RuntimeError('缓存微信窗口或DPI已变化')
            old=choose_control(cache,label)
            control={**old,'screenCenter':{axis:old['screenCenter'][axis]-cache['origin'][axis]+geometry['origin'][axis]
                                         for axis in ('x','y')}}
        if geometry['clientSize']!=size:raise RuntimeError('微信尺寸已变化，重新扫描位置')
        # User-requested optimistic coordinate click; only a failed launch triggers discovery.
        click_control(user,geometry,control)
        return {'ok':True,'label':label,'control':control,'cached':True}
    deadline=time.monotonic()+20
    pid=select_wechat_pid(psutil.process_iter(['name','cmdline']),wechat_window_pids(user))
    created=psutil.Process(pid).create_time()
    geometry=main_geometry(user,pid)
    if mode!='Scan':
        hwnd=int(geometry['hwnd'],16)
        if user.IsIconic(hwnd):user.ShowWindowAsync(hwnd,9)
        user.SetForegroundWindow(hwnd)
        time.sleep(.2)
        geometry=main_geometry(user,pid)
    snapshot=_probe.snapshot(pid,created,cache.get('layout') if cache else None,geometry)
    snapshot['processCreatedAt']=created
    if mode=='Click':
        if time.monotonic()>deadline:raise RuntimeError('微信控件扫描耗时过长，取消过期点击')
        control=choose_control(snapshot,label)
        click_control(user,snapshot,control)
        return {'ok':True,'label':label,'control':control,'snapshot':snapshot}
    return dict(snapshot,ok=True)


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
