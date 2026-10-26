import asyncio

import pytest

from package.plugin_manager import transport


def test_damage_stop_retains_persistent_identifier_until_confirmed(monkeypatch):
    async def run():
        client = transport.PluginTransport()
        client._damage_persistent = 'registration-1'
        calls = []
        async def disable(bridge, script, *, persistent_identifier):
            calls.append(persistent_identifier)
            if len(calls) == 1:
                raise RuntimeError('connection lost')
            return {'ok': True, 'enabled': False}
        monkeypatch.setattr(transport, 'disable_runtime_js_file', disable)
        with pytest.raises(RuntimeError, match='connection lost'):
            await client.damage_stop()
        assert client._damage_persistent == 'registration-1'
        await client.damage_stop()
        assert client._damage_persistent == ''
        assert calls == ['registration-1', 'registration-1']
    asyncio.run(run())
