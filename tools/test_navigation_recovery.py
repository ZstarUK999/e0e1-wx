import asyncio
from types import SimpleNamespace
import pytest
from package.daily_tasks.scheduler import RetryableTaskError, TaskDeferredError
from package.plugin_manager.resident import ResidentGame
from package.plugin_manager.transport import PluginTransport
from package.plugin_manager.douyin import DouyinTransport

@pytest.mark.parametrize('kind',['wechat','douyin'])
def test_recovered_navigation_clears_inflight_and_defers_without_replaying(kind):
    async def run():
        cdp=SimpleNamespace(is_connected=lambda:True,on=lambda *args:None)
        transport=PluginTransport(cdp=cdp) if kind=='wechat' else DouyinTransport.__new__(DouyinTransport)
        transport._lock=asyncio.Lock();transport._inflight=None;transport._generation=1
        transport.session_id='test-session';transport.context_id=7;transport.runtime=7;transport.connected=True;transport.cdp=cdp
        calls=[]
        async def receipt(*args,**kwargs):
            calls.append(1)
            return {'status':'unavailable','recovered_home':True,'message':'已返回大厅，本轮延后'}
        async def appid():return transport.TARGET_APPID
        async def prepare(*args):pass
        transport._appid=appid;transport._prepare_features=prepare
        transport._evaluate=receipt;transport._rpc=receipt
        game=ResidentGame(transport)
        with pytest.raises(TaskDeferredError):await game.tomb_targets('sanshi','fill')
        assert len(calls)==1
        assert transport._inflight is None
    asyncio.run(run())


def test_ordinary_rejection_still_has_three_attempts():
    async def run():
        calls=[]
        async def call(op,payload=None):
            calls.append(op)
            if op!='home':raise RetryableTaskError('尚未执行')
        game=ResidentGame(SimpleNamespace(call=call))
        with pytest.raises(RetryableTaskError):await game.tomb_targets('sanshi','fill')
        assert calls==['tomb_targets']*3+['home']
    asyncio.run(run())


def test_navigation_deferred_does_not_block_following_daily_task():
    import time
    from package.plugin_manager.automation import AutomationScheduler
    from package.daily_tasks.scheduler import TaskContext, TaskResult
    async def run():
        state=SimpleNamespace(installed='same-session',blocked='',blocked_session=None,closing=False,stop_operation=False)
        messages=[];connections=[];executed=[]
        label=SimpleNamespace(setText=messages.append)
        view=SimpleNamespace(game_connected=True,set_connection=lambda **kw:connections.append(kw),
            set_operation_running=lambda value:None,action_label=label,
            task_panels={key:SimpleNamespace(runtime_message=label) for key in ('sanshi_fill','pet_hatch')})
        tasks={key:SimpleNamespace(task_id=key,name=key,timeout_seconds=1,retry_seconds=60,
            schedule=SimpleNamespace(interval_seconds=60)) for key in ('sanshi_fill','pet_hatch')}
        async def deferred(*args,**kwargs):raise TaskDeferredError('页面异常，已返回大厅')
        async def next_task(*args,**kwargs):executed.append('pet_hatch');return TaskResult('success','已执行')
        scheduler=AutomationScheduler.__new__(AutomationScheduler)
        scheduler.state=state;scheduler.view=view;scheduler.transport=SimpleNamespace()
        scheduler._handlers={'sanshi_fill':SimpleNamespace(run=deferred),'pet_hatch':SimpleNamespace(run=next_task)}
        scheduler.daily_config=lambda:SimpleNamespace(tasks=tasks)
        scheduler._task_due={};scheduler._active_task=None;scheduler.stopping=False;scheduler.running=True
        await scheduler._run(TaskContext(tasks['sanshi_fill'],None,lambda:False),False)
        assert not state.blocked and not connections
        assert scheduler._task_due['sanshi_fill']>time.monotonic()
        await scheduler._run(TaskContext(tasks['pet_hatch'],None,lambda:False),False)
        assert executed==['pet_hatch'] and not state.blocked
    asyncio.run(run())
