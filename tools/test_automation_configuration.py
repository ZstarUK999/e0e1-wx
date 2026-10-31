import asyncio
import copy
from datetime import datetime
from types import SimpleNamespace

import pytest

from package.daily_tasks.scheduler import BEIJING, RetryableTaskError, TaskContext, TaskResult
from package.daily_tasks.pet_hatch import PetHatchTask
from package.plugin_manager.automation import AutomationScheduler
from package.plugin_manager.store import default_config


def scheduler_fixture(tmp_path):
    config = default_config()
    for task in config['daily']['tasks'].values():
        task['enabled'] = False
    labels = {}
    def label(key):
        return SimpleNamespace(setText=lambda text: labels.update({key: text}))
    view = SimpleNamespace(
        store=SimpleNamespace(path=tmp_path/'plugins.json', snapshot=lambda: copy.deepcopy(config)),
        task_panels={key: SimpleNamespace(runtime_message=label(key)) for key in config['daily']['tasks']},
        action_label=label('action'), set_operation_running=lambda value: None,
        game_connected=True, set_connection=lambda **kwargs: None,
    )
    state = SimpleNamespace(installed='session', closing=False, blocked='', stop_operation=False)
    scheduler = AutomationScheduler(SimpleNamespace(), state, view)
    return scheduler, config, state, labels


def test_unselected_hatch_is_excluded_without_blocking_lower_priority_task_and_resumes_after_edit(tmp_path, caplog):
    scheduler, config, state, labels = scheduler_fixture(tmp_path)
    tasks = config['daily']['tasks']
    tasks['pet_hatch']['enabled'] = tasks['offline_reward']['enabled'] = True
    now = datetime(2026, 10, 29, 12, tzinfo=BEIJING)
    with caplog.at_level('INFO', logger='plugin_manager'):
        for _ in range(3):
            assert scheduler.pick(now) == 'offline_reward'
            assert scheduler.next_check(now)['task_id'] == 'offline_reward'
        assert caplog.text.count('任务跳过：阴契自动解封') == 1
        assert labels['pet_hatch'] == '请先选择要自动解封的阴契'
        scheduler._task_due['pet_hatch'] = 10**12
        tasks['pet_hatch']['params']['item_ids'] = [400001]
        assert scheduler.pick(now) == 'pet_hatch'
        assert scheduler._task_due['pet_hatch'] == 0
    assert not scheduler.busy and not state.blocked


def test_only_unconfigured_task_has_no_next_check_and_manual_run_touches_no_game(tmp_path):
    scheduler, config, state, labels = scheduler_fixture(tmp_path)
    config['daily']['tasks']['pet_hatch']['enabled'] = True
    now = datetime(2026, 10, 29, 12, tzinfo=BEIJING)
    assert scheduler.pick(now) is None
    assert scheduler.next_check(now) is None
    class NoGameAccess:
        def __getattr__(self, name):
            raise AssertionError('empty selection must not access game: ' + name)
    async def run():
        result = await PetHatchTask(NoGameAccess()).run(TaskContext(scheduler.daily_config().tasks['pet_hatch'], None, lambda: False))
        assert result.status == 'waiting'
    asyncio.run(run())


@pytest.mark.parametrize('retry', [False, True])
def test_wait_or_retry_releases_scheduler_and_honors_delay(tmp_path, monkeypatch, caplog, retry):
    from package.plugin_manager import automation
    scheduler, config, state, labels = scheduler_fixture(tmp_path)
    tasks = config['daily']['tasks']
    tasks['energy']['enabled'] = tasks['offline_reward']['enabled'] = True
    tasks['energy']['retry_seconds'] = 120
    monkeypatch.setattr(automation, 'time', SimpleNamespace(monotonic=lambda: 100.0))
    class Handler:
        async def run(self, context, **kwargs):
            if retry:
                raise RetryableTaskError('当前界面暂不可用')
            return TaskResult('waiting', '冷却未结束', 300)
    scheduler._handlers['energy'] = Handler()
    async def run():
        scheduler.begin('energy')
        await scheduler.wait_operation()
        assert not scheduler.busy and scheduler.active is None and not state.blocked
        assert scheduler._task_due['energy'] == 100 + (120 if retry else 300)
        assert scheduler.pick(datetime(2026, 10, 29, 12, tzinfo=BEIJING)) == 'offline_reward'
    with caplog.at_level('INFO', logger='plugin_manager'):
        asyncio.run(run())
    assert ('120.0秒后再检查' if retry else '状态=waiting') in caplog.text


@pytest.mark.parametrize('phase', ['challenge', 'home'])
@pytest.mark.parametrize('outcome', ['confirmed', 'unknown', 'user_stop', 'external_block'])
def test_arena_timeout_recovers_only_after_confirmed_receipt_and_home(tmp_path, phase, outcome):
    from package.daily_tasks.arena import ArenaTask
    scheduler, config, state, labels = scheduler_fixture(tmp_path)
    task = config['daily']['tasks']['arena']
    task['enabled'] = config['daily']['tasks']['offline_reward']['enabled'] = True
    task['timeout_seconds'] = .01
    task['schedule'].update(start='00:00', end='23:59')
    scheduler.running = True
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Game:
            tickets = 1
            homes = challenges = 0
            async def home(self):
                self.homes += 1
                if phase == 'home' and self.homes == 2:
                    entered.set()
                    await release.wait()
                    if outcome == 'unknown':
                        raise RetryableTaskError('返回大厅未确认')
            async def arena_state(self):
                return {'tickets': self.tickets, 'refresh_remaining': 0, 'targets': [{'id': 1, 'rank': 1}]}
            async def arena_challenge(self, target):
                self.challenges += 1
                if phase == 'challenge':
                    entered.set()
                    await release.wait()
                    if outcome == 'unknown':
                        return {'confirmed': False}
                self.tickets -= 1
                return {'confirmed': True, 'win': True}
        game = Game()
        scheduler._handlers['arena'] = ArenaTask(game, now=lambda: datetime(2026, 10, 29, 12, tzinfo=BEIJING))
        cleanup = []
        async def return_home():
            cleanup.append(True)
            return True
        scheduler._return_home_after_stop = return_home
        context = TaskContext(scheduler.daily_config().tasks['arena'], None, lambda: state.stop_operation)
        scheduler._active_task = 'arena'
        scheduler.operation = asyncio.create_task(scheduler._run(context, False))
        await asyncio.wait_for(entered.wait(), .5)
        # Wait for the scheduler's actual timeout signal before completing the in-flight action.
        for _ in range(100):
            if state.stop_operation:
                break
            await asyncio.sleep(.002)
        assert state.stop_operation and state.blocked and scheduler.busy
        if outcome == 'user_stop':
            scheduler.running = False
            scheduler.stopping = True
        elif outcome == 'external_block':
            state.blocked = '调试链路已断开'
        release.set()
        await asyncio.wait_for(scheduler.wait_operation(), 1)
        assert game.challenges == 1 and not scheduler.busy and scheduler.active is None
        if outcome in ('confirmed', 'user_stop'):
            assert not state.blocked and not scheduler._handlers['arena'].blocked_reason
            if outcome == 'confirmed':
                assert not state.stop_operation and not cleanup
                assert scheduler.pick(datetime(2026, 10, 29, 12, tzinfo=BEIJING)) == 'offline_reward'
            else:
                assert state.stop_operation and not scheduler.running and cleanup == [True]
        else:
            assert state.blocked and state.stop_operation
            if outcome == 'external_block':
                assert state.blocked == '调试链路已断开'
    asyncio.run(run())


def test_timeout_without_explicit_safe_receipt_still_blocks(tmp_path):
    scheduler, config, state, labels = scheduler_fixture(tmp_path)
    config['daily']['tasks']['energy']['timeout_seconds'] = .01
    async def run():
        class Handler:
            async def run(self, ctx, **kwargs):
                while not ctx.stop_requested():
                    await asyncio.sleep(.002)
                return TaskResult('success', '只返回成功但未确认收尾')
        scheduler._handlers['energy'] = Handler()
        async def return_home():return False
        scheduler._return_home_after_stop = return_home
        scheduler.begin('energy')
        await scheduler.wait_operation()
        assert state.blocked and state.stop_operation
    asyncio.run(run())


def test_changed_hatch_selection_wakes_only_its_own_timer(tmp_path):
    scheduler, config, state, labels = scheduler_fixture(tmp_path)
    tasks = config['daily']['tasks']
    tasks['pet_hatch']['enabled'] = tasks['offline_reward']['enabled'] = True
    tasks['pet_hatch']['params']['item_ids'] = [400004]
    scheduler.daily_config()
    scheduler._task_due.update(pet_hatch=10**12, offline_reward=10**12)
    tasks['pet_hatch']['params']['item_ids'] = [400003]
    assert scheduler.pick(datetime(2026, 10, 29, 12, tzinfo=BEIJING)) == 'pet_hatch'
    assert scheduler._task_due['offline_reward'] == 10**12


@pytest.mark.parametrize('interrupted', [True, False])
def test_old_run_cannot_restore_long_delay_after_stop_or_parameter_edit(tmp_path, interrupted):
    scheduler, config, state, labels = scheduler_fixture(tmp_path)
    task = config['daily']['tasks']['pet_hatch']
    task['enabled'] = True
    task['params']['item_ids'] = [400004]
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Handler:
            async def run(self, ctx, **kwargs):
                entered.set()
                await release.wait()
                return TaskResult('success', '已放入2个', 3600)
        scheduler._handlers['pet_hatch'] = Handler()
        async def return_home():return True
        scheduler._return_home_after_stop = return_home
        scheduler.begin('pet_hatch')
        await entered.wait()
        if interrupted:
            state.stop_operation = True
        else:
            task['params']['item_ids'] = [400003]
            scheduler.daily_config()
        release.set()
        await scheduler.wait_operation()
        assert scheduler._task_due['pet_hatch'] == 0
        assert scheduler.pick(datetime(2026, 10, 29, 12, tzinfo=BEIJING)) == 'pet_hatch'
    asyncio.run(run())


def test_saving_selection_does_not_stop_session_with_legacy_false_master(tmp_path):
    from PySide6.QtWidgets import QApplication
    from tools.test_plugin_runtime import make_controller, ready
    app = QApplication.instance() or QApplication([])
    async def run():
        c, service, transport, window = make_controller(tmp_path)
        try:
            window.store.set_task_enabled('pet_hatch', True)
            await ready(c, service)
            c.automation.set_automation(True)
            c.state.stop_operation = False
            assert window.store.snapshot()['daily']['enabled'] is False
            window.store.update_task('pet_hatch', {'params': {'item_ids': [400004, 400003]}})
            assert c.automation.running and not c.state.stop_operation
            window.store.set_task_enabled('pet_hatch', False)
            assert not c.automation.running and c.state.stop_operation
        finally:
            await c.shutdown()
            window.close()
            app.processEvents()
    asyncio.run(run())


def test_hatch_choices_render_and_save_checked_values(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from package.plugin_manager.panels import TaskPanel
    from package.plugin_manager.store import PluginConfigStore
    from package.ui.styles import APP_STYLESHEET
    app = QApplication.instance() or QApplication([])
    old_style = app.styleSheet()
    app.setStyleSheet(APP_STYLESHEET)
    store = PluginConfigStore(tmp_path/'panel-config.json')
    panel = TaskPanel(store, 'pet_hatch')
    choices = panel.fields['params.item_ids']
    selected = {400004, 400003, 400002}
    for i in range(choices.count()):
        item = choices.item(i)
        item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in selected else Qt.CheckState.Unchecked)
    panel.save()
    assert set(store.snapshot()['daily']['tasks']['pet_hatch']['params']['item_ids']) == selected
    panel.resize(850, 850)
    panel.show()
    choices.scrollToBottom()
    app.processEvents()
    assert panel.grab().save(str(tmp_path/'panel.png'))
    panel.close()
    app.setStyleSheet(old_style)
