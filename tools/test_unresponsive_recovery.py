import asyncio
from package.plugin_manager.blank_recovery import BlankScreenRecovery


def test_persistent_unresponsive_restarts_without_screenshot_and_has_cooldown():
    async def run():
        now=[0];restarts=[]
        async def capture():raise AssertionError('stalled recovery must not depend on screenshot')
        async def restart():restarts.append(now[0])
        r=BlankScreenRecovery(clock=lambda:now[0],capture=capture,restart=restart)
        for t in range(0,61,5):
            now[0]=t
            await r.poll(active=True,disconnected=True,kicked=False,closing=False,unresponsive=True)
            if t<60:assert not restarts
        assert restarts==[60]
        now[0]=65
        await r.poll(active=True,disconnected=True,kicked=False,closing=False,unresponsive=True)
        assert restarts==[60]
    asyncio.run(run())


def test_success_resets_timeout_confirmation():
    async def run():
        now=[0];restarts=[]
        async def capture():return None
        async def restart():restarts.append(now[0])
        r=BlankScreenRecovery(clock=lambda:now[0],capture=capture,restart=restart)
        for t,stalled in [(0,True),(30,True),(45,False),(50,True),(80,True),(105,True)]:
            now[0]=t
            await r.poll(active=True,disconnected=stalled,kicked=False,closing=False,unresponsive=stalled)
        assert not restarts
        now[0]=110
        await r.poll(active=True,disconnected=True,kicked=False,closing=False,unresponsive=True)
        assert restarts==[110]
    asyncio.run(run())


def test_kick_or_shutdown_does_not_restart():
    async def run():
        now=[0]
        async def restart():raise AssertionError('must not restart')
        r=BlankScreenRecovery(clock=lambda:now[0],restart=restart)
        for t in [0,60,120]:
            now[0]=t
            await r.poll(active=True,disconnected=True,kicked=True,closing=False,unresponsive=True)
            await r.poll(active=True,disconnected=True,kicked=False,closing=True,unresponsive=True)
    asyncio.run(run())


def test_runtime_rechecks_stale_timeout_before_restarting():
    from types import SimpleNamespace
    from package.plugin_manager.runtime import PluginRuntime
    async def run():
        seen=[]
        async def poll(**kwargs):seen.append(kwargs['unresponsive'])
        async def evaluate(*args,**kwargs):return True
        fake=SimpleNamespace(transport=SimpleNamespace(unresponsive=True,connected=True,context_id=7,_evaluate=evaluate),
            blank_recovery=SimpleNamespace(poll=poll),wechat_reconnect=None,state=SimpleNamespace(closing=False))
        await PluginRuntime._check_blank_game(fake,True)
        assert seen==[False]
        async def timeout(*args,**kwargs):raise TimeoutError()
        fake.transport._evaluate=timeout
        await PluginRuntime._check_blank_game(fake,True)
        assert seen==[False,True]
    asyncio.run(run())
