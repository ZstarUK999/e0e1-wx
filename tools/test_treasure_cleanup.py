import asyncio
from types import SimpleNamespace

from package.plugin_manager.features.treasure import TreasureFeature


def test_injection_and_disable_stop_timer_and_retry_cleanup():
    async def run():
        calls = []
        fail = [False]
        async def inject():
            calls.append('inject')
        async def overlay(on):
            calls.append(on)
            if fail[0]:
                raise TimeoutError('unresponsive')
        transport = SimpleNamespace(treasure_inject=inject, treasure_overlay=overlay)
        panel = SimpleNamespace(set_enabled=lambda value: None, set_message=lambda value: None)
        feature = TreasureFeature(transport, SimpleNamespace(installed='session', closing=False), panel)
        await feature.poll({'treasure': {'enabled': True, 'overlay': False}})
        assert calls == ['inject', False], 'injection starts a timer even when overlay is unchecked'
        await feature.poll({'treasure': {'enabled': True, 'overlay': True}})
        assert calls[-1] is True
        fail[0] = True
        await feature.poll({'treasure': {'enabled': False}})
        assert feature._overlay is True
        fail[0] = False
        await feature.poll({'treasure': {'enabled': False}})
        assert calls[-2:] == [False, False]
        count = len(calls)
        await feature.poll({'treasure': {'enabled': False}})
        assert len(calls) == count
        await feature.poll({'treasure': {'enabled': True, 'overlay': True}})
        assert calls[-1] is True
        assert calls.count('inject') == 1
    asyncio.run(run())
