import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from package.plugin_manager.runtime import PluginRuntime
from package.plugin_manager import startup_launch


def test_wechat_prepares_debug_without_launching_and_connects_after_manual_open(tmp_path, monkeypatch):
    from tools.test_plugin_runtime import make_controller
    app = QApplication.instance() or QApplication([])
    async def unexpected(*args, **kwargs):
        raise AssertionError('Selecting WeChat must not navigate or open the game')
    monkeypatch.setattr(startup_launch, 'ensure_game_started', unexpected)
    async def run():
        c, service, transport, window = make_controller(tmp_path, process=False)
        try:
            c._startup_checked = False
            c._next_startup_retry = float('inf')
            c.session.prepare_reopen = unexpected
            assert await c._ensure_startup()
            assert c._startup_checked and c._next_startup_retry == 0
            assert len(service.starts) == 1
            assert '手动' in window.action_label.text()
            for _ in range(3):
                await c.poll()
            assert not transport.calls and len(service.starts) == 1
            assert c.state.installed is None
            # The user opens the game: the normal connection/injection path resumes.
            c.session.process_ready = lambda: True
            c.session._next_process_check = 0
            service.update(status='running', worker_alive=True, miniapp=True, frida=True,
                           cdp_port=62000, miniapp_epoch=1)
            await c.poll()
            assert c.state.installed == 'one'
            assert ('install', None) in transport.calls
            assert sum(op == 'install' for op, _ in transport.calls) == 1
        finally:
            await c.shutdown()
            window.close()
            app.processEvents()
    asyncio.run(run())


@pytest.mark.parametrize('platform', ['抖音', '应用宝'])
def test_other_platforms_keep_their_existing_startup_flow(monkeypatch, platform):
    calls = []
    async def ready():pass
    async def launch(name, **kwargs):
        calls.append((name, kwargs.get('before_open')))
    monkeypatch.setattr(startup_launch, 'ensure_game_started', launch)
    runtime = SimpleNamespace(_startup_checked=False, _next_startup_retry=0,
        platform_name=platform, state=SimpleNamespace(closing=False),
        session=SimpleNamespace(request_debug=lambda: calls.append('debug'), prepare_reopen=ready),
        window=SimpleNamespace(action_label=SimpleNamespace(setText=lambda text: None)))
    assert asyncio.run(PluginRuntime._ensure_startup(runtime))
    assert calls[-1] == (platform, ready if platform == '应用宝' else None)
    assert runtime._startup_checked
