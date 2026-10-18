import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from package.plugin_manager.features.damage import DamageFeature


def test_runtime_profile_does_not_enable_damage(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    async def fast_sleep(_):
        pass
    monkeypatch.setattr(asyncio, 'sleep', fast_sleep)
    messages = []
    feature = DamageFeature.__new__(DamageFeature)
    feature._perf_running = False
    feature.state = SimpleNamespace(closing=False)
    feature.panel = SimpleNamespace(message=SimpleNamespace(setText=messages.append))
    feature.transport = SimpleNamespace(context_id=1, perf_start=AsyncMock(),
        perf_stop=AsyncMock(return_value={'metrics': {'season.candidates.sync': {'calls': 10}}}))
    feature._ensure_injected = AsyncMock()
    asyncio.run(feature.handle('perf', {}))
    feature._ensure_injected.assert_not_awaited()
    feature.transport.perf_start.assert_awaited_once()
    feature.transport.perf_stop.assert_awaited_once()
    reports = list((tmp_path/'logs/runtime_profiles').glob('*.json'))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding='utf-8'))['metrics']['season.candidates.sync']['calls'] == 10
    assert feature._perf_running is False


def test_duplicate_runtime_profile_is_ignored():
    feature = DamageFeature.__new__(DamageFeature)
    feature._perf_running = True
    feature.panel = SimpleNamespace(message=SimpleNamespace(setText=lambda _: None))
    feature.transport = SimpleNamespace(perf_start=AsyncMock())
    asyncio.run(feature._profile_runtime())
    feature.transport.perf_start.assert_not_awaited()
