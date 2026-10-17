import win32gui, win32process

def pname(pid):
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return '?'
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.psapi.GetModuleBaseNameW(h, None, buf, 260)
        ctypes.windll.kernel32.CloseHandle(h)
        return buf.value
    except Exception:
        return '?'

def cb(hwnd, res):
    if not win32gui.IsWindowVisible(hwnd):
        return
    t = win32gui.GetWindowText(hwnd)
    cls = win32gui.GetClassName(hwnd)
    r = win32gui.GetWindowRect(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    n = pname(pid)
    res.append((pid, n, cls, t, r[2] - r[0], r[3] - r[1]))
    return True

res = []
win32gui.EnumWindows(cb, res)
for pid, n, cls, t, w, h in sorted(res, key=lambda x: -x[4] * x[5]):
    if 'douyin' in n.lower() or 'douyin' in t.lower() or '抖音' in t or w * h > 300000:
        print(f'pid={pid} {n} cls={cls} "{t}" {w}x{h}')
