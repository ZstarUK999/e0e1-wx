"""单实例串行日常调度。仅执行显式注册的异步处理器，不包含游戏操作。"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import time as clock_time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import DailyConfig, TaskConfig, _seconds

BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")
LOG = logging.getLogger("daily_tasks")


@dataclass(frozen=True)
class TaskResult:
    status: str = "success"
    message: str = ""
    next_delay_seconds: float | None = None
    # Explicit receipt that the handler confirmed all effects and completed cleanup.
    safe_to_resume: bool = False

    def __post_init__(self):
        if self.status not in ("success", "skipped", "waiting"):
            raise ValueError("任务结果仅允许 success/skipped/waiting")
        if not isinstance(self.message, str):
            raise ValueError("任务结果message必须是字符串")
        if type(self.safe_to_resume) is not bool:
            raise ValueError("safe_to_resume必须是布尔值")
        if self.next_delay_seconds is not None:
            _seconds(self.next_delay_seconds, "next_delay_seconds")


class ExecutionUncertain(RuntimeError):
    """外部操作可能已执行但无法确认；停止调度，禁止自动重试。"""


class RetryableTaskError(RuntimeError):
    """处理器明确确认没有未决外部效果；允许按冷却时间重新检查。"""


@dataclass(frozen=True)
class TaskContext:
    task: TaskConfig
    window_end: datetime | None
    stop_requested: Callable[[], bool]


@dataclass
class TaskState:
    state: str = "idle"
    next_due: float = 0.0
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    last_message: str = ""
    last_started: str | None = None
    last_finished: str | None = None


Handler = Callable[[TaskContext], Awaitable[TaskResult]]


class Scheduler:
    def __init__(self, config: DailyConfig, *, monotonic: Callable[[], float] = clock_time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.config = copy.deepcopy(config)
        self.monotonic = monotonic
        self.now = now
        self.handlers: dict[str, Handler] = {}
        self.states: dict[str, TaskState] = {key: TaskState(next_due=monotonic()) for key in config.tasks}
        self.running_task: str | None = None
        self.blocked_reason = ""
        self.config_error = ""
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._next_summary = monotonic() + config.summary_interval_seconds

    def register(self, task_id: str, handler: Handler) -> None:
        if task_id not in self.config.tasks:
            raise ValueError(f"未配置任务：{task_id}")
        if task_id in self.handlers:
            raise ValueError(f"任务已注册：{task_id}")
        if not callable(handler):
            raise ValueError("handler必须是异步可调用对象")
        self.handlers[task_id] = handler

    def apply_config(self, config: DailyConfig) -> None:
        # 当前步骤使用自己的配置快照，开关在下一步骤边界生效。
        if config.summary_interval_seconds != self.config.summary_interval_seconds:
            self._next_summary = self.monotonic() + config.summary_interval_seconds
        self.config = copy.deepcopy(config)
        self.config_error = ""
        for task_id in config.tasks:
            self.states.setdefault(task_id, TaskState(next_due=self.monotonic()))

    def stop(self) -> None:
        """停止新任务，正在运行的处理器在自己的安全边界收尾。"""
        self._stop.set()

    def resume_after_verification(self) -> None:
        if self.running_task is not None:
            raise RuntimeError("等待正在运行的任务安全收尾后再恢复")
        self.blocked_reason = ""

    def _window(self, task: TaskConfig) -> tuple[bool, datetime | None]:
        if task.schedule.kind == "interval":
            return True, None
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("每日调度时钟必须包含时区")
        now = now.astimezone(BEIJING)
        start = datetime.combine(now.date(), task.schedule.start, BEIJING)
        end = datetime.combine(now.date(), task.schedule.end, BEIJING)
        return start <= now < end, end

    def _state_name(self, task: TaskConfig, state: TaskState) -> str:
        if self.running_task == task.task_id:
            return "running"
        if not self.config.enabled or not task.enabled:
            return "disabled"
        if task.task_id not in self.handlers:
            return "unregistered"
        if self.config_error:
            return "config_error"
        if self.blocked_reason:
            return state.state if state.state == "uncertain" else "blocked"
        if self._stop.is_set():
            return "stopped"
        if not self._window(task)[0]:
            return "outside_window"
        return state.state

    def snapshot(self) -> dict:
        elapsed = self.monotonic()
        tasks = {}
        for task_id, task in self.config.tasks.items():
            state = self.states[task_id]
            tasks[task_id] = {"name": task.name, "enabled": task.enabled, "registered": task_id in self.handlers,
                              "state": self._state_name(task, state), "priority": task.priority,
                              "attempts": state.attempts, "successes": state.successes, "failures": state.failures,
                              "next_due_in_seconds": max(0.0, state.next_due - elapsed), "last_message": state.last_message,
                              "last_started": state.last_started, "last_finished": state.last_finished}
        return {"enabled": self.config.enabled, "timezone": self.config.timezone, "log_timezone": "local",
                "running_task": self.running_task, "blocked_reason": self.blocked_reason, "config_error": self.config_error,
                "stopping": self._stop.is_set(), "tasks": tasks}

    def _summary(self) -> None:
        elapsed = self.monotonic()
        if elapsed >= self._next_summary:
            # 周期合并，不因长时间暂停补发多条摘要。
            LOG.info("日常任务摘要：%s", self.snapshot())
            self._next_summary = elapsed + self.config.summary_interval_seconds

    async def _execute(self, context: TaskContext) -> TaskResult:
        job = asyncio.ensure_future(self.handlers[context.task.task_id](context))
        try:
            done, _ = await asyncio.wait({job}, timeout=context.task.timeout_seconds)
            if not done:
                # 先记下超时再等清理；处理器吞掉取消返回成功也不能抹掉超时。
                self.blocked_reason = f"{context.task.task_id}: 任务超时，等待收尾并核对外部状态"
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
                raise ExecutionUncertain("任务超时，执行结果未知")
            return await job
        finally:
            if not job.done():
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)

    async def tick(self) -> str | None:
        """执行一个到期步骤。并发tick不排队、不重复执行。"""
        if self._lock.locked():
            return None
        async with self._lock:
            self._summary()
            if self._stop.is_set() or not self.config.enabled or self.blocked_reason or self.config_error:
                return None
            elapsed = self.monotonic()
            ready = [task for task in self.config.tasks.values()
                     if task.enabled and task.task_id in self.handlers and self.states[task.task_id].next_due <= elapsed
                     and self._window(task)[0]]
            if not ready:
                return None
            task = min(ready, key=lambda item: (item.priority, self.states[item.task_id].next_due, item.task_id))
            # 每次发起前重新判断窗口；截止后不补执行。
            in_window, window_end = self._window(task)
            if not in_window:
                return None
            state = self.states[task.task_id]
            state.attempts += 1
            state.state = "running"
            state.last_started = datetime.now().astimezone().isoformat(timespec="seconds")
            self.running_task = task.task_id
            delay = task.schedule.interval_seconds
            fixed_cadence = True
            context = TaskContext(copy.deepcopy(task), window_end, self._stop.is_set)
            try:
                result = await self._execute(context)
                if not isinstance(result, TaskResult):
                    raise TypeError("任务处理器必须返回TaskResult")
                state.state = result.status
                state.last_message = result.message
                if result.status == "success":
                    state.successes += 1
                if result.next_delay_seconds is not None:
                    delay = result.next_delay_seconds
                    fixed_cadence = False
            except (asyncio.TimeoutError, ExecutionUncertain) as exc:
                state.state = "uncertain"
                state.failures += 1
                state.last_message = str(exc) or "任务超时，执行结果未知"
                self.blocked_reason = f"{task.task_id}: {state.last_message}；核对外部状态后才能恢复"
                delay = task.retry_seconds
                fixed_cadence = False
                LOG.error(self.blocked_reason)
            except asyncio.CancelledError:
                state.state = "uncertain"
                state.last_message = "调度被取消，执行结果需核对"
                self.blocked_reason = f"{task.task_id}: {state.last_message}"
                self.stop()
                raise
            except RetryableTaskError as exc:
                state.state = "failed"
                state.failures += 1
                state.last_message = str(exc)
                delay = task.retry_seconds
                fixed_cadence = False
                LOG.warning("日常任务 %s 失败，冷却%s秒：%s", task.task_id, delay, exc)
            except Exception as exc:
                state.state = "uncertain"
                state.failures += 1
                state.last_message = str(exc)
                self.blocked_reason = f"{task.task_id}: {exc}；执行结果未经确认，暂停调度"
                delay = task.retry_seconds
                fixed_cadence = False
                LOG.error(self.blocked_reason)
            finally:
                finished = self.monotonic()
                if fixed_cadence:
                    missed = max(1, math.floor((finished - state.next_due) / delay) + 1)
                    state.next_due += missed * delay
                else:
                    state.next_due = finished + delay
                state.last_finished = datetime.now().astimezone().isoformat(timespec="seconds")
                self.running_task = None
                self._summary()
            return task.task_id

    async def run(self, *, config_loader: Callable[[], DailyConfig] | None = None) -> None:
        """可交给现有TaskSupervisor托管的单一调度协程。"""
        while not self._stop.is_set():
            if config_loader is not None:
                try:
                    updated = config_loader()
                    if updated != self.config or self.config_error:
                        self.apply_config(updated)
                except (OSError, ValueError) as exc:
                    error = str(exc)
                    if error != self.config_error:
                        LOG.error("日常配置无效，暂停新任务：%s", error)
                    self.config_error = error
            completed = await self.tick()
            if completed is not None:
                # 让同一轮其他到期任务执行，已完成的不会重复排队。
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.config.poll_seconds)
            except asyncio.TimeoutError:
                pass
