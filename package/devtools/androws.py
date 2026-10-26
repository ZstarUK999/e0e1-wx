"""应用宝 WMPF 识别与按二进制指纹选择配置。"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import psutil


def is_androws_path(path: str) -> bool:
    path = str(path or '').replace('/', '\\').casefold()
    return '\\androws\\wmpfruntime\\' in path and path.endswith('\\wechatappex.exe')


def find_runtime(processes):
    """从已确认的应用宝子进程找父进程；不混入微信同名进程。"""
    children = [p for p in processes if p.name == 'WeChatAppEx.exe'
                and is_androws_path(p.parameters.get('path', ''))]
    parents = Counter(int(p.parameters.get('ppid') or 0) for p in children)
    candidates = []
    for pid, count in parents.items():
        if not pid:
            continue
        try:
            if psutil.Process(pid).name().casefold() == 'wechatappex.exe':
                candidates.append((pid, count))
        except psutil.Error:
            continue
    if len(candidates) != 1:
        raise RuntimeError('无法唯一识别应用宝小游戏主进程，请先打开应用宝中的《遗弃之地》')
    pid = candidates[0][0]
    paths = {Path(p.parameters['path']).parent / 'flue.dll' for p in children
             if int(p.parameters.get('ppid') or 0) == pid}
    if len(paths) != 1:
        raise RuntimeError('应用宝运行库路径不唯一，停止连接')
    return pid, paths.pop()


def load_profile(dll: Path, config_root: Path):
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()
    path = config_root / 'androws' / f'{digest}.json'
    if not path.is_file():
        raise RuntimeError(f'此应用宝运行库尚未适配（SHA256 {digest[:12]}），不会套用微信偏移')
    config = json.loads(path.read_text(encoding='utf-8'))
    if config.get('SHA256') != digest or config.get('Channel') != 'androws':
        raise RuntimeError('应用宝偏移配置校验失败')
    return config
