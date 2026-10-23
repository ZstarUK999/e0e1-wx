from types import SimpleNamespace

import pytest

from package.devtools.service import DevtoolsService


@pytest.mark.parametrize('wait', [False, True])
def test_shutdown_reaps_stuck_worker_before_discarding_handle(wait):
    calls = []
    alive = [True]
    process = SimpleNamespace(
        is_alive=lambda: alive[0],
        join=lambda **kw: calls.append('join'),
        terminate=lambda: calls.append('terminate'),
        kill=lambda: (calls.append('kill'), alive.__setitem__(0, False)),
        close=lambda: calls.append('close'))
    service = SimpleNamespace(event_timer=SimpleNamespace(stop=lambda: None),
        command_queue=SimpleNamespace(put=lambda command: calls.append(command['type'])),
        process=process, cloud_calls=[], js_injection_states={}, route_states={},
        miniapp_jump_states={}, debug_toggle_states={})
    DevtoolsService.shutdown(service, wait=wait)
    assert calls == ['shutdown', 'join', 'terminate', 'join', 'kill', 'join', 'close']
    assert service.process is None
