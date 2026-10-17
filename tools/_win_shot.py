"""Capture a window (by pid) to PNG. Usage: _win_shot.py <pid> <out.bmp>"""
import sys, ctypes
import win32gui, win32ui, win32process


def find_hwnds(pid):
    res = []
    def cb(h, _):
        try:
            _, p = win32process.GetWindowThreadProcessId(h)
        except Exception:
            return True
        if p == pid and win32gui.IsWindowVisible(h):
            r = win32gui.GetWindowRect(h)
            if r[2] - r[0] > 400 and r[3] - r[1] > 300:
                res.append((h, r))
        return True
    win32gui.EnumWindows(cb, None)
    return res


def shot(hwnd, out):
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    r = win32gui.GetWindowRect(hwnd)
    w, h = r[2] - r[0], r[3] - r[1]
    src = win32gui.GetDC(0)
    mfcDC = win32ui.CreateDCFromHandle(src)
    saveDC = mfcDC.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfcDC, w, h)
    saveDC.SelectObject(bmp)
    ctypes.windll.gdi32.BitBlt(saveDC.GetSafeHdc(), 0, 0, w, h,
                               mfcDC.GetSafeHdc(), r[0], r[1], 0x00CC0020)
    bmp.SaveBitmapFile(saveDC, out)
    try:
        saveDC.DeleteDC(); mfcDC.DeleteDC()
    except Exception:
        pass
    win32gui.ReleaseDC(0, src)
    return (w, h, r)


if __name__ == '__main__':
    pid = int(sys.argv[1])
    out = sys.argv[2]
    hs = find_hwnds(pid)
    if not hs:
        print('no window for pid', pid)
        sys.exit(1)
    hwnd, r = max(hs, key=lambda x: (x[1][2] - x[1][0]) * (x[1][3] - x[1][1]))
    print('windows:', [(h, rr) for h, rr in hs])
    print('captured hwnd', hwnd, shot(hwnd, out), '->', out)
