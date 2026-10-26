import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from package.devtools import androws
from package.devtools.bridge import RealDebugEngineBridge
from package.plugin_manager.androws import AndrowsTransport


def process(pid, ppid, path):
    return SimpleNamespace(pid=pid, name='WeChatAppEx.exe', parameters={'ppid':ppid, 'path':path})


def test_find_runtime_excludes_wechat_and_infers_inaccessible_main(monkeypatch):
    monkeypatch.setattr(androws.psutil, 'Process', lambda pid: SimpleNamespace(name=lambda:'WeChatAppEx.exe'))
    selected, dll = androws.find_runtime([
        process(1,10,r'C:\WeChat\RadiumWMPF\25799\WeChatAppEx.exe'),
        process(2,20,r'C:\Tencent\Androws\WmpfRuntime\5.10.7300.414\runtime\WeChatAppEx.exe'),
        process(3,20,r'C:\Tencent\Androws\WmpfRuntime\5.10.7300.414\runtime\WeChatAppEx.exe'),
    ])
    assert selected == 20
    assert dll.name == 'flue.dll'


def test_ambiguous_instances_are_rejected(monkeypatch):
    monkeypatch.setattr(androws.psutil, 'Process', lambda pid: SimpleNamespace(name=lambda:'WeChatAppEx.exe'))
    with pytest.raises(RuntimeError, match='唯一'):
        androws.find_runtime([process(i,i+20,r'C:\Tencent\Androws\WmpfRuntime\v\WeChatAppEx.exe') for i in (1,2)])


def test_unknown_or_mismatched_binary_never_uses_wechat_profile(tmp_path):
    dll=tmp_path/'flue.dll'; dll.write_bytes(b'unknown')
    with pytest.raises(RuntimeError, match='尚未适配'):
        androws.load_profile(dll,tmp_path)
    digest=hashlib.sha256(b'unknown').hexdigest()
    (tmp_path/'androws').mkdir()
    path=tmp_path/'androws'/f'{digest}.json'
    path.write_text(json.dumps({'SHA256':'wrong','Channel':'androws'}))
    with pytest.raises(RuntimeError, match='校验失败'):
        androws.load_profile(dll,tmp_path)


def test_channel_reaches_engine_without_changing_default(monkeypatch):
    import package.devtools.bridge as bridge
    seen=[]
    class Engine:
        def __init__(self,options,logger): seen.append(options.channel); self.status={}
        def on_status_change(self,cb): pass
        async def start(self): pass
    monkeypatch.setattr(bridge,'DebugEngine',Engine)
    async def run():
        await RealDebugEngineBridge().start({'channel':'androws'},9422,63000,lambda s:None)
        await RealDebugEngineBridge().start({},9421,62000,lambda s:None)
    asyncio.run(run())
    assert seen==['androws','wechat']


def test_androws_start_waits_for_hook_before_launch(monkeypatch):
    import package.plugin_manager.androws as channel
    calls=[]
    monkeypatch.setattr(channel,'androws_ready',lambda:True)
    monkeypatch.setattr(channel,'launch_game',lambda:calls.append('launch'))
    async def ready(): calls.append('hook')
    asyncio.run(channel.ensure_game_started(before_open=ready))
    assert calls==['hook','launch']


def test_failed_hook_does_not_open_game(monkeypatch):
    import package.plugin_manager.androws as channel
    calls=[]
    monkeypatch.setattr(channel,'androws_ready',lambda:True)
    monkeypatch.setattr(channel,'launch_game',lambda:calls.append('launch'))
    async def ready(): raise RuntimeError('bad fingerprint')
    with pytest.raises(RuntimeError,match='bad fingerprint'):
        asyncio.run(channel.ensure_game_started(before_open=ready))
    assert calls==[]


def test_androws_transport_is_separate_channel():
    assert AndrowsTransport.platform_name=='应用宝'
    assert AndrowsTransport.channel=='androws'
