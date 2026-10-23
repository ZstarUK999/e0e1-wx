from package.plugin_manager.restart_resume import RestartResume


def test_marker_requires_confirmed_launch_and_new_session_and_is_consumed_once():
    marker = RestartResume(clock=lambda: 10)
    marker.observe({'daily', 'desire', 'pet_fodder'}, 'old', healthy=True)
    marker.arm()
    assert marker.next_task('new') is None
    marker.launched = True
    assert marker.next_task('old') is None
    for task in ('desire', 'pet_fodder', 'daily'):
        assert marker.next_task('new') == task
        marker.consumed(task)
    assert marker.next_task('new') is None


def test_ended_task_not_resumed_but_recent_disconnect_failure_keeps_intent():
    now = [10]
    marker = RestartResume(clock=lambda: now[0])
    marker.observe({'desire'}, 'old', healthy=True)
    marker.observe(set(), 'old', healthy=True)
    marker.arm()
    assert not marker.pending
    marker.observe({'desire'}, 'old', healthy=True)
    marker.observe(set(), 'old', healthy=False)
    marker.arm()
    assert marker.pending == {'desire'}


def test_countdown_marker_survives_long_wait_and_user_stop_cancels():
    now = [10]
    marker = RestartResume(clock=lambda: now[0])
    marker.observe({'daily', 'desire'}, 'old', healthy=True)
    marker.arm()
    now[0] = 10000
    marker.observe(set(), None, healthy=False)
    marker.arm()
    marker.cancel('desire')
    marker.launched = True
    assert marker.next_task('new') == 'daily'
    marker.cancel('daily')
    assert marker.next_task('new') is None


def test_stale_unarmed_activity_does_not_start_task():
    now = [10]
    marker = RestartResume(clock=lambda: now[0])
    marker.observe({'desire'}, 'old', healthy=True)
    now[0] = 131
    marker.arm()
    assert not marker.pending


def test_second_restart_keeps_waiting_tasks_and_rearms_current_task():
    marker = RestartResume()
    marker.observe({'daily', 'desire'}, 'first', healthy=True)
    marker.arm()
    marker.launched = True
    marker.consumed('desire')
    marker.observe({'desire'}, 'second', healthy=True)
    marker.arm()
    assert marker.pending == {'daily', 'desire'}
    assert marker.next_task('second') is None
    marker.launched = True
    assert marker.next_task('second') is None
    assert marker.next_task('third') == 'desire'


def test_immediate_kick_restart_arms_before_launch():
    import asyncio
    from package.plugin_manager.reconnect import WechatReconnect
    async def run():
        marker = RestartResume()
        marker.observe({'desire'}, 'old', healthy=True)
        class Transport:
            def before_wechat_restart(self):marker.arm()
            async def wechat_reconnect_status(self, enabled):return {'kicked':True, 'event':'one'}
            async def wechat_restart_after_kick(self, event):
                assert marker.pending == {'desire'}
                marker.launched = True
                return True
        reconnect = WechatReconnect(Transport())
        await reconnect.poll({'wechat_reconnect':True, 'reconnect_seconds':0})
        assert marker.next_task('new') == 'desire'
        marker.arm()
        assert marker.launched
    asyncio.run(run())
