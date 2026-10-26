"""应用宝渠道：复用 CDP 游戏传输，独立发现、启动与调试端口。"""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import psutil

from package.devtools.androws import is_androws_path
from .transport import PluginTransport, TARGET_APPID


class AndrowsTransport(PluginTransport):
    platform_name = '应用宝'
    channel = 'androws'


def androws_ready():
    for proc in psutil.process_iter(['name', 'exe']):
        if str(proc.info.get('name', '')).casefold() == 'wechatappex.exe' and is_androws_path(proc.info.get('exe')):
            return True
    return False


def launcher_path():
    # Prefer the installed protocol command, including installations on other drives.
    import winreg
    import ctypes
    from ctypes import wintypes
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'androws\shell\open\command') as key:
            command = winreg.QueryValueEx(key, '')[0]
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
        count = ctypes.c_int()
        argv = shell.CommandLineToArgvW(command, ctypes.byref(count))
        if argv:
            try:
                path = Path(argv[0])
                if path.name.casefold() == 'androwslauncher.exe' and path.is_file():
                    return path
            finally:
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.LocalFree.argtypes = [ctypes.c_void_p]
                kernel.LocalFree.restype = ctypes.c_void_p
                kernel.LocalFree(argv)
    except OSError:
        pass
    path = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Tencent/Androws/Application/AndrowsLauncher.exe'
    if not path.is_file():
        raise RuntimeError('未找到应用宝启动器，请先安装并打开应用宝')
    return path


def launch_game():
    uri = f'androws://client/launchWithShortcut?pkgname={TARGET_APPID}&gameType=2&tray=1&silent=0'
    subprocess.Popen([str(launcher_path()), uri], creationflags=subprocess.CREATE_NO_WINDOW)


async def ensure_game_started(*, before_open=None):
    # A running WMPF process alone is not evidence of a running game. Install
    # hooks first, then invoke the exact app's official entry once.
    if not await asyncio.to_thread(androws_ready):
        await asyncio.to_thread(launch_game)
        for _ in range(40):
            await asyncio.sleep(.25)
            if await asyncio.to_thread(androws_ready):
                break
        else:
            raise RuntimeError('应用宝小游戏运行环境未启动，请在应用宝中打开《遗弃之地》')
    if before_open:
        await before_open()
    await asyncio.to_thread(launch_game)
    return True
