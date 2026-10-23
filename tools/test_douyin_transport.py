"""No Douyin/WeChat execution; test cache integrity and mailbox identity."""
import asyncio
import json
import os
import time
import subprocess
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest

from package.plugin_manager.douyin import APPID, MARKER, DouyinCache, DouyinTransport, atomic_json
from package.plugin_manager.transport import ContextDestroyed


def cache_fixture(tmp_path):
    root = tmp_path / 'microGameCache'
    target = root / 'resource/packages' / APPID / '0.1.71/game.js'
    target.parent.mkdir(parents=True)
    original = b'var x=1;__tt_define__("game.js",(function(e,t){"use strict";globalThis.fixture=true;}));'
    target.write_bytes(original)
    cache = DouyinCache(tmp_path / 'settings', root)
    return cache, target, original


def live(cache, runtime='one', **patch):
    value = {'token': cache.token, 'build': cache.build, 'runtime': runtime, 'appid': APPID,
             'at': time.time()*1000, 'game': True, 'hall': True, 'resident': None, 'protocol':'static-v1'}
    value.update(patch)
    atomic_json(cache.mailbox('state'), value)


def test_cache_patch_idempotent_and_preserves_original(tmp_path):
    cache, target, original = cache_fixture(tmp_path)
    assert cache.prepare()
    assert MARKER in target.read_bytes()
    assert not cache.prepare()
    assert (cache.settings / '0.1.71.original.js').read_bytes() == original
    target.write_bytes(target.read_bytes()+b'changed')
    with pytest.raises(RuntimeError, match='已变化'):
        cache.prepare()


def test_cache_unsupported_shape_and_version_change(tmp_path):
    cache, target, original = cache_fixture(tmp_path)
    target.write_bytes(b'unsupported')
    with pytest.raises(RuntimeError, match='结构已变化'):
        cache.prepare()
    target.write_bytes(original)
    cache.prepare()
    new_target = target.parent.parent / '0.1.72/game.js'
    new_target.parent.mkdir()
    new_target.write_bytes(original)
    assert cache.prepare() and cache.version == '0.1.72'


def test_restore_requires_owned_patch_and_matching_original(tmp_path):
    cache, target, original = cache_fixture(tmp_path)
    cache.prepare()
    assert cache.restore() == [str(target)]
    assert target.read_bytes() == original
    assert cache.restore() == []
    cache.prepare()
    target.write_bytes(target.read_bytes()+b'foreign')
    with pytest.raises(RuntimeError, match='其他修改'):
        cache.restore()


def test_wrong_token_build_app_and_stale_heartbeat_rejected(tmp_path):
    cache, _, _ = cache_fixture(tmp_path)
    cache.prepare()
    for patch in ({'token': 'wrong'}, {'build': 'wrong'}, {'appid': 'other'}, {'at': 0}):
        live(cache, **patch)
        assert cache.status() is None
    live(cache)
    assert cache.status()['runtime'] == 'one'
    cache.mailbox('state').write_text('{partial', encoding='utf-8')
    assert cache.status()['runtime'] == 'one', 'partial heartbeat must not destroy a live session'


def test_timeout_not_replayed_and_late_receipt_can_be_confirmed(tmp_path):
    async def run():
        cache, _, _ = cache_fixture(tmp_path)
        cache.prepare(); live(cache)
        transport = DouyinTransport(cache)
        await transport.connect()
        with pytest.raises(asyncio.TimeoutError):
            await transport._rpc('ping', timeout_ms=50)
        command = json.loads(cache.mailbox('command').read_text(encoding='utf-8'))
        with pytest.raises(RuntimeError, match='前次'):
            await transport._rpc('do-not-replay')
        assert json.loads(cache.mailbox('command').read_text(encoding='utf-8'))['id'] == command['id']
        atomic_json(cache.mailbox('response'), {**{key: command[key] for key in ('token','runtime','id')}, 'ok': True, 'value': 2})
        await transport.wait_idle()
        assert transport._pending_file is None
    asyncio.run(run())


def test_response_correlation_and_context_replacement(tmp_path):
    async def run():
        cache, _, _ = cache_fixture(tmp_path)
        cache.prepare(); live(cache)
        transport = DouyinTransport(cache)
        await transport.connect()
        pending = {'token':cache.token,'runtime':'one','id':'request'}
        transport._pending_file = pending
        atomic_json(cache.mailbox('response'), {**pending,'id':'old','ok':True,'value':999})
        with pytest.raises(asyncio.TimeoutError):
            await transport._reply(pending, 30)
        live(cache, runtime='two')
        with pytest.raises(ContextDestroyed):
            await transport.wait_idle()
        assert transport._pending_file is None and transport.context_id is None
    asyncio.run(run())


def test_selector_defers_services_until_choice(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from package.plugin_manager import app as assembly
    import package.plugin_manager.douyin as module
    app = QApplication.instance() or QApplication([])
    calls = []
    class Runtime:
        def __init__(self, window, **kwargs):
            calls.append(kwargs)
        def start(self):
            calls.append('started')
    monkeypatch.setattr(assembly.runtime_module, 'PluginRuntime', Runtime)
    instance = assembly.PluginApplication(tmp_path/'config.json', platform=None)
    window = instance._create_window()
    assert not calls
    assert set(window.platform_buttons) == {'wechat','douyin'}
    window.platform_buttons['douyin'].click()
    assert isinstance(calls[0]['transport'], module.DouyinTransport)
    assert isinstance(calls[0]['service'], module.DouyinService)
    assert calls[1] == 'started'
    calls[0]['service'].player_id_changed.emit('456')
    assert window.bound_id_label.text() == '绑定ID：456'
    assert window.pages['player'].bound_id.text() == '绑定ID：456'
    window.close()
    app.processEvents()


def test_real_node_python_bridge_reuses_resident_and_damage_script(tmp_path):
    import shutil
    node = shutil.which('node')
    if not node:
        pytest.skip('Node not installed')
    async def run():
        cache, _, _ = cache_fixture(tmp_path)
        cache.prepare()
        cache.user.mkdir(parents=True, exist_ok=True)
        config = tmp_path / 'node-fixture.json'
        bridge = tmp_path / 'compiled-static-bridge.js'
        bridge.write_text(cache.compiled_source(),encoding='utf-8')
        atomic_json(config, {'token':cache.token, 'build':cache.build, 'user':str(cache.user), 'bridge':str(bridge), 'largeReply':True})
        child = subprocess.Popen([node, str(Path(__file__).with_name('douyin_bridge_fixture.cjs')), str(config)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if cache.status():
                    break
                await asyncio.sleep(.05)
            assert cache.status(), child.poll()
            assert cache.status()['player_id'] == '123'
            transport = DouyinTransport(cache)
            await transport.connect()
            assert await transport._rpc('ping') == 2
            # 真实静态桥中执行开屏清理；动态 eval/Function 均被禁用。
            startup = await transport.dismiss_startup()
            assert startup['ready'] is False
            assert startup['message'] == '确认大厅稳定'
            assert (await transport.legion_read('42'))['name'] == '测试阴司'
            scanned = await transport.legion_scan_call('player','12000100')
            assert scanned['id'] == '12000100' and scanned['sName'] == '540服'
            batch=await transport.legion_scan_call('players',['12000100','12000101'])
            assert [row['value']['id'] for row in batch]==['12000100','12000101']
            assert (await transport.legion_scan_call('search','测试阴司'))['id'] == '42'
            result = await transport._rpc('damage-debug', timeout_ms=30000)
            assert result == {'text':'中文😀'*100000}
            for _ in range(30):
                if not cache.mailbox('response').exists():
                    break
                await asyncio.sleep(.05)
            assert not cache.mailbox('response').exists()

            assert (await transport.probe())['ready']
            sid = await transport.install()
            assert sid == transport.session_id
            assert await transport.call('configure', {}) is True
            enabled = await transport.damage_inject()
            assert enabled['enabled'] is True
            status = await transport.damage_status()
            assert status['running'] and status['hasCfg'] and status['hasBattleManager']
            assert isinstance(await transport.damage_snapshot(), dict)
            assert (await transport.damage_stop())['enabled'] is False
            assert (await transport.damage_status())['running'] is False
            assert await transport.call('stop') is True
            await transport.close()
        finally:
            child.terminate()
            child.communicate(timeout=5)
    asyncio.run(run())


def test_douyin_identity_signal_clears_on_disconnect_and_does_not_change_gate(tmp_path):
    from PySide6.QtWidgets import QApplication
    from package.plugin_manager.douyin import DouyinService
    app = QApplication.instance() or QApplication([])
    cache, _, _ = cache_fixture(tmp_path)
    cache.prepare()
    service = DouyinService(cache)
    ids=[]
    service.player_id_changed.connect(ids.append)
    live(cache, player_id='456')
    service._tick()
    service._tick()
    assert ids == ['456']
    live(cache, player_id='789')
    service._tick()
    assert ids == ['456','789']
    live(cache, at=0)
    service._tick()
    assert ids == ['456','789','']
    service.shutdown()
    app.processEvents()


def test_douyin_probe_renews_runtime_and_resident_bound_keepalive_lease(tmp_path):
    async def run():
        cache, _, _ = cache_fixture(tmp_path)
        cache.prepare()
        live(cache, runtime='lease-runtime', resident='lease-resident')
        transport = DouyinTransport(cache)
        await transport.connect()
        transport.session_id='lease-resident'
        transport._owned_ids.add('lease-resident')
        await transport.probe()
        lease = json.loads(cache.mailbox('lease').read_text(encoding='utf-8'))
        assert lease['token'] == cache.token
        assert lease['runtime'] == 'lease-runtime'
        assert lease['resident'] == 'lease-resident'
        assert 0 <= time.time()*1000-lease['at'] < 2000
    asyncio.run(run())



def test_shutdown_detaches_waiter_without_replaying_command(tmp_path):
    async def run():
        cache, _, _ = cache_fixture(tmp_path)
        cache.prepare();live(cache, resident='owned')
        transport = DouyinTransport(cache)
        await transport.connect();transport.session_id='owned'
        job=asyncio.create_task(transport._rpc('season-call', {'name':'candidates'}, timeout_ms=30000))
        await asyncio.sleep(.01)
        command=json.loads(cache.mailbox('command').read_text(encoding='utf-8'))
        transport.begin_shutdown()
        signal=json.loads(cache.mailbox('shutdown').read_text(encoding='utf-8'))
        assert signal['resident']=='owned' and signal['runtime']==transport.runtime
        transport.detach_for_shutdown()
        with pytest.raises(ContextDestroyed):
            await asyncio.wait_for(job,.5)
        assert transport._pending_file['id']==command['id']
        assert json.loads(cache.mailbox('command').read_text(encoding='utf-8'))['id']==command['id']
        with pytest.raises(ContextDestroyed):
            await transport._rpc('ping')
    asyncio.run(run())



def test_overlay_control_bypasses_busy_file_command_lock_and_checks_identity(tmp_path):
    async def run():
        cache,_,_=cache_fixture(tmp_path);cache.prepare()
        live(cache,resident='resident',automation={'run_id':'run','stop_requested':True})
        transport=DouyinTransport(cache);await transport.connect()
        transport.session_id='resident'
        async with transport._file_lock:
            reply=await asyncio.wait_for(transport.automation_overlay({'run_id':'run','active':True}),.2)
        assert reply['stop_requested']
        command=json.loads(cache.mailbox('automation').read_text(encoding='utf-8'))
        assert command['resident']=='resident' and command['runtime']==transport.runtime
        live(cache,resident='other')
        assert await transport.automation_overlay({'active':False}) is None
    asyncio.run(run())


def test_chunked_reply_resumes_after_timeout_without_replaying(tmp_path):
    async def run():
        cache,_,_=cache_fixture(tmp_path);cache.prepare();live(cache)
        transport=DouyinTransport(cache);await transport.connect()
        pending={'id':'large','runtime':transport.runtime}
        transport._pending_file=pending
        payload={'token':cache.token,'runtime':transport.runtime,'id':'large','ok':True,'value':'中文😀'*20000}
        text=json.dumps(payload,ensure_ascii=False)
        def part(index,data,final):
            atomic_json(cache.mailbox('response'),{'token':cache.token,'runtime':transport.runtime,
                'id':'large','chunked':True,'index':index,'data':data,'final':final})
        part(0,text[:10000],False)
        with pytest.raises(asyncio.TimeoutError):
            await transport._reply(pending,30)
        assert len(pending['_reply_parts'])==1
        assert transport._pending_file is pending
        part(1,text[10000:],True)
        assert await transport._reply(pending,100)==payload['value']
        assert transport._pending_file is None
        assert '_reply_parts' not in pending
        assert json.loads(cache.mailbox('response-ack').read_text())['index']==1
    asyncio.run(run())
