import asyncio
import pytest
from package.plugin_manager.resident import ResidentGame
from package.daily_tasks.scheduler import RetryableTaskError, ExecutionUncertain

CASES = [('free_summon', ()), ('free_summon_state', ()), ('pet_hatch_claim', (1,)),
         ('pet_hatch_start', (400001,)), ('pet_hatch_state', ([400001],)),
         ('pet_fodder_state', ()), ('pet_fodder_merge', ({},)), ('arena_state', ())]

@pytest.mark.parametrize('method,args', CASES)
def test_explicitly_unexecuted_operations_retry(method, args):
    class Transport:
        def __init__(self): self.calls = []
        async def call(self, op, payload=None):
            self.calls.append(op)
            if len(self.calls) == 1: raise RetryableTaskError('UI not ready; not executed')
            return {'confirmed': True}
    t = Transport()
    result = asyncio.run(getattr(ResidentGame(t), method)(*args))
    assert result['confirmed']
    assert t.calls == [method, method]

@pytest.mark.parametrize('method,args', CASES)
def test_uncertain_operations_are_not_replayed(method, args):
    class Transport:
        def __init__(self): self.calls = []
        async def call(self, op, payload=None):
            self.calls.append(op)
            raise ExecutionUncertain('response not confirmed')
    t = Transport()
    with pytest.raises(ExecutionUncertain):
        asyncio.run(getattr(ResidentGame(t), method)(*args))
    assert t.calls == [method]
