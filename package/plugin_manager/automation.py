"""日常任务调度：任务处理器、到期时间、优先级选择与一次执行的收尾。

只回答"下一个该跑谁"，不关心游戏怎么连上。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from package.daily_tasks.config import parse_config
from package.daily_tasks.energy import EnergyTask
from package.daily_tasks.scheduler import BEIJING, ExecutionUncertain, RetryableTaskError, TaskContext
from package.daily_tasks.offline_reward import OfflineRewardTask
from package.daily_tasks.arena import ArenaTask
from package.daily_tasks.tombs import TombCycleTask, TombFillTask, TombRaidTask
from package.plugin_manager.resident import ResidentGame

from .feature_flags import task_enabled
from .transport import TARGET_APPID

LOG = logging.getLogger('plugin_manager')


class AutomationScheduler:
    def __init__(self, transport, state, view):
        self.transport = transport
        self.state = state
        self.view = view
        self.running = False
        self.operation = None
        self._handlers = {}
        self._task_due = {}
        self._active_task = None
        self._reset_handlers()

    # ── 任务处理器 ──

    def _reset_handlers(self) -> None:
        game = ResidentGame(self.transport)
        candidates = {
            'energy': lambda: EnergyTask(game, None),
            'offline_reward': lambda: OfflineRewardTask(game),
            'arena': lambda: ArenaTask(game),
        }
        for kind in ('sanshi', 'artifact'):
            candidates[kind + '_tombs'] = lambda kind=kind: TombCycleTask(game, kind)
            candidates[kind + '_raid'] = lambda kind=kind: TombRaidTask(game, kind)
            candidates[kind + '_fill'] = lambda kind=kind: TombFillTask(game, kind)
        # 构建期关掉的任务不注册处理器，pick() 自然也不会挑中它们。
        self._handlers = {key: factory() for key, factory in candidates.items() if task_enabled(key)}
        self._task_due = {key: 0.0 for key in self._handlers}

    def reset_handlers(self) -> None:
        """新会话：丢弃旧处理器，到期时间也一并重置。"""
        self._reset_handlers()

    @property
    def capabilities(self) -> set[str]:
        return set(self._handlers)

    @property
    def active(self) -> str | None:
        return self._active_task

    @property
    def busy(self) -> bool:
        return self.operation is not None and not self.operation.done()

    def handle(self, task_id):
        return self._handlers.get(task_id)

    # ── 启停 ──

    def set_automation(self, running: bool) -> None:
        """会话级启停；不持久化，插件重启后默认停止。"""
        if running == self.running:
            return
        if running:
            if self.state.closing or not self.state.installed:
                LOG.info('自动化未启动：%s', '插件正在关闭' if self.state.closing else '尚未注入目标游戏')
                self.view.set_automation_running(False)
                return
            if self.state.blocked:
                LOG.info('自动化未启动：当前会话已暂停，%s', self.state.blocked)
                self.view.set_automation_running(False)
                return
            self.running = True
            self.state.stop_operation = False
            LOG.info('日常自动化已启动')
        else:
            self.running = False
            self.state.stop_operation = True
            LOG.info('日常自动化已停止，等待当前操作安全收尾')
        self.view.set_automation_running(self.running)

    # ── 选择 ──

    def pick(self, now: datetime) -> str | None:
        """按优先级挑一个到期任务；时间窗任务还要落在窗口内。"""
        parsed = parse_config(self.view.store.snapshot()['daily'])
        candidates = []
        for key, task in parsed.tasks.items():
            if not task.enabled or key not in self._handlers or time.monotonic() < self._task_due.get(key, 0):
                continue
            if task.schedule.kind == 'daily_window' and not task.schedule.start <= now.time().replace(tzinfo=None) < task.schedule.end:
                continue
            candidates.append(task)
        if not candidates:
            return None
        selected = min(candidates, key=lambda task: (task.priority, self._task_due.get(task.task_id, 0), task.task_id))
        return selected.task_id

    # ── 执行 ──

    def begin(self, task_id: str, *, manual: bool = False) -> None:
        if self.state.closing or not self.state.installed or self.state.blocked or (self.operation and not self.operation.done()):
            return
        self.state.stop_operation = False
        ctx_task = parse_config(self.view.store.snapshot()['daily']).tasks[task_id]
        end = None
        if ctx_task.schedule.kind == 'daily_window':
            end = datetime.combine(datetime.now(BEIJING).date(), ctx_task.schedule.end, BEIJING)
        context = TaskContext(ctx_task, end, lambda: self.state.closing or self.state.stop_operation or not self.state.installed)
        self._active_task = task_id
        self.view.set_operation_running(True)
        self.operation = asyncio.create_task(self._run(context, manual))

    async def _run(self, context, manual: bool) -> None:
        task_id = context.task.task_id
        LOG.info('任务开始：%s%s', context.task.name, '（手动测试）' if manual else '')
        message = ''
        delay = context.task.schedule.interval_seconds
        try:
            job = asyncio.create_task(self._handlers[task_id].run(context, force_trigger=manual))
            done, _ = await asyncio.wait({job}, timeout=context.task.timeout_seconds)
            if not done:
                # 只请求在安全步骤停止，不取消已经发到游戏的请求/恢复。
                self.state.stop_operation = True
                self.state.blocked = '任务超时；等待当前请求收尾后需核对'
            result = await job
            message = result.message
            if result.next_delay_seconds is not None:
                delay = result.next_delay_seconds
            if manual or result.status == 'success':
                LOG.info('任务结束：%s，%s', context.task.name, message)
            if self.state.blocked:
                raise ExecutionUncertain(self.state.blocked)
        except RetryableTaskError as exc:
            message = str(exc)
        except Exception as exc:
            self.state.blocked = str(exc)
            self.state.blocked_session = self.state.installed or self.state.blocked_session
            message = '已暂停：' + str(exc)
            self.view.set_connection(connected=self.view.game_connected, target_appid=getattr(self.transport, 'TARGET_APPID', TARGET_APPID), runtime_ready=False)
            LOG.warning('插件任务暂停：%s', exc)
        finally:
            self._task_due[task_id] = time.monotonic() + delay
            self.view.task_panels[task_id].runtime_message.setText(message or '任务已收尾')
            self._active_task = None
            self.view.set_operation_running(False)
            if manual:
                self.view.finish_test(task_id, message or '测试已收尾')
            else:
                self.view.action_label.setText(message or '任务已收尾')

    async def wait_operation(self) -> None:
        if self.operation:
            await asyncio.shield(self.operation)
