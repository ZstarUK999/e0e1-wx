import errno
from unittest.mock import MagicMock

from package.devtools import worker


def test_access_denied_is_not_reported_as_listener(monkeypatch):
    sock = MagicMock()
    sock.__enter__.return_value.bind.side_effect = PermissionError(errno.EACCES, 'forbidden')
    monkeypatch.setattr(worker.socket, 'socket', lambda *args: sock)
    message = worker.debug_port_unavailable_message(9421)
    assert '绑定被系统拒绝' in message and '排除端口' in message
    assert '请停止另一个' not in message


def test_actual_listener_error_remains_explicit(monkeypatch):
    sock = MagicMock()
    sock.__enter__.return_value.bind.side_effect = OSError(errno.EADDRINUSE, 'address already in use')
    monkeypatch.setattr(worker.socket, 'socket', lambda *args: sock)
    assert '已被占用' in worker.debug_port_unavailable_message(9421)


def test_reserved_default_uses_available_fallback(monkeypatch):
    sock = MagicMock()
    sock.__enter__.return_value.bind.side_effect = PermissionError(errno.EACCES, 'forbidden')
    monkeypatch.setattr(worker.socket, 'socket', lambda *args: sock)
    monkeypatch.setattr(worker, 'port_available', lambda port: port == 19422)
    assert worker.choose_debug_port(9421) == 19422


def test_available_default_stays_unchanged(monkeypatch):
    monkeypatch.setattr(worker, 'port_available', lambda port: port == 9421)
    assert worker.choose_debug_port(9421) == 9421


def test_existing_listener_does_not_spawn_second_debug_session(monkeypatch):
    import pytest
    sock = MagicMock()
    sock.__enter__.return_value.bind.side_effect = OSError(errno.EADDRINUSE, 'address already in use')
    monkeypatch.setattr(worker.socket, 'socket', lambda *args: sock)
    monkeypatch.setattr(worker, 'port_available', lambda port: False)
    with pytest.raises(RuntimeError, match='已被占用'):
        worker.choose_debug_port(9421)


def test_real_hook_callback_port_is_rewritten():
    from pathlib import Path
    from package.devtools.engine import render_hook_debug_port
    source = (Path(__file__).resolve().parents[1]/'tools/hook.js').read_text(encoding='utf-8')
    rendered = render_hook_debug_port(source,19421)
    assert 'const DEBUG_PORT = 19421;' in rendered
    assert 'const DEBUG_PORT = 9421;' not in rendered
    assert 'ws://localhost:${DEBUG_PORT}' in rendered


def test_custom_port_requires_verified_hook_declaration():
    import pytest
    from package.devtools.engine import render_hook_debug_port
    with pytest.raises(RuntimeError,match='回连端口声明未核实'):
        render_hook_debug_port('// missing callback setting',19421)
