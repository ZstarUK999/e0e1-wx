"""Two-phase Douyin mini-game opener (separate processes: focus, then click).

Usage:
  _open_game.py focus                -> restore/maximise + force foreground, prints rect
  _open_game.py click <sx> <sy>      -> click at absolute SCREEN coords
  _open_game.py wait [secs]          -> wait until :5678 is up
"""
import sys, time, socket, ctypes
import win32gui, win32con, win32api, win32process

PORT = 5678


def find_game_window():
    res = []
    def cb(h, _):
        try:
            c = win32gui.GetClassName(h)
            t = win32gui.GetWindowText(h)
        except Exception:
            return True
        if c == 'Chrome_WidgetWin_1' and t == '抖音':
            res.append(h)
        return True
    win32gui.EnumWindows(cb, None)
    return res[0] if res else None


def focus():
    hwnd = find_game_window()
    if not hwnd:
        print('no-window'); return 1
    if win32gui.IsIconic(hwnd):
        win32gui.SendMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
        time.sleep(1.5)
    k, u = ctypes.windll.kernel32, ctypes.windll.user32
    this_t = k.GetCurrentThreadId()
    fg = u.GetForegroundWindow()
    fg_t = win32process.GetWindowThreadProcessId(fg)[0]
    tgt_t = win32process.GetWindowThreadProcessId(hwnd)[0]
    if fg_t and fg_t != this_t:
        u.AttachThreadInput(this_t, fg_t, True)
    if tgt_t and tgt_t != this_t:
        u.AttachThreadInput(this_t, tgt_t, True)
    u.BringWindowToTop(hwnd)
    u.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    u.SetForegroundWindow(hwnd)
    u.SetFocus(hwnd)
    if tgt_t and tgt_t != this_t:
        u.AttachThreadInput(this_t, tgt_t, False)
    if fg_t and fg_t != this_t:
        u.AttachThreadInput(this_t, fg_t, False)
    time.sleep(0.8)
    r = win32gui.GetWindowRect(hwnd)
    print('hwnd=%d rect=%s fg=%d' % (hwnd, r, u.GetForegroundWindow() == hwnd))
    return 0


def click(sx, sy):
    ctypes.windll.user32.SetProcessDPIAware()
    win32api.SetCursorPos((int(sx), int(sy)))
    time.sleep(0.4)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    print('clicked', (int(sx), int(sy)), 'cursor', win32api.GetCursorPos())
    return 0


def port_up():
    s = socket.socket(); s.settimeout(1.0)
    try:
        s.connect(('127.0.0.1', PORT)); return True
    except Exception:
        return False
    finally:
        s.close()


def wait(secs=150):
    for i in range(int(secs) // 2):
        if port_up():
            print('MINI-GAME UP after ~%ds' % (i * 2))
            return 0
        time.sleep(2)
    print('game did not start (:5678 down)')
    return 1


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'focus'
    if cmd == 'focus':
        sys.exit(focus())
    elif cmd == 'click':
        sys.exit(click(float(sys.argv[2]), float(sys.argv[3])))
    elif cmd == 'wait':
        sys.exit(wait(float(sys.argv[2]) if len(sys.argv) > 2 else 150))
