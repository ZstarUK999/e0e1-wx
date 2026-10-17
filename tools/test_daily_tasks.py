"""统一日常配置/调度测试，全部使用本地假时钟，不接触游戏。"""

import asyncio
import copy
import importlib
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def modules():
    try:
        return (importlib.import_module("package.daily_tasks.config"), importlib.import_module("package.daily_tasks.scheduler"))
    except ModuleNotFoundError as exc:
        if exc.name.startswith("package.daily_tasks"):
            pytest.fail("尚未实现日常任务配置/调度框架")
        raise


def task(priority=20, interval=60, enabled=True, schedule=None, **extra):
    return {"name": "测试任务", "enabled": enabled, "priority": priority, "timeout_seconds": 1, "retry_seconds": 60,
            "schedule": schedule or {"kind": "interval", "interval_seconds": interval}, "params": {}, **extra}


def config(tasks, enabled=True, **extra):
    return {"version": 1, "enabled": enabled, "timezone": "Asia/Shanghai", "poll_seconds": 1,
            "summary_interval_seconds": 3600, "tasks": tasks, **extra}


class Clock:
    def __init__(self, wall=None):
        self.elapsed = 0.0
        self.wall = wall or datetime(2026, 10, 14, 2, 28, tzinfo=timezone.utc)

    def monotonic(self):
        return self.elapsed

    def now(self):
        return self.wall

    def advance(self, seconds):
        self.elapsed += seconds
        self.wall += timedelta(seconds=seconds)


def make_scheduler(raw, clock=None):
    c, s = modules()
    clock = clock or Clock()
    return s.Scheduler(c.parse_config(raw), monotonic=clock.monotonic, now=clock.now), clock


def test_default_config_contains_nine_independent_tasks():
    c, _ = modules()
    loaded = c.load_config(c.DEFAULT_CONFIG_PATH)
    # 这是用户可编辑的CLI配置，开关可以已经打开；测试不能修改或假设其当前状态。
    assert type(loaded.enabled) is bool
    assert len(loaded.tasks) == 9
    assert loaded.timezone == "Asia/Shanghai"
    assert loaded.tasks["energy"].params["trigger_ratio"] == 0.9
    assert loaded.tasks["energy"].params["spend_mode"] == "all_available"
    assert loaded.tasks["offline_reward"].params["claim_interval_seconds"] == 3600
    for task_id in ("energy", "sanshi_raid", "artifact_raid", "sanshi_fill", "artifact_fill"):
        assert loaded.tasks[task_id].schedule.interval_seconds == 60
    # 挂机收益一小时才可能攒够，按小时检查。
    assert loaded.tasks["offline_reward"].schedule.interval_seconds == 3600
    for task_id in ("sanshi_raid", "artifact_raid"):
        # 三尸门槛16，法器攒不满所以门槛10。
        assert loaded.tasks[task_id].params["minimum_tombs"] == (16 if task_id == "sanshi_raid" else 10)
        assert loaded.tasks[task_id].params["skip_failed_players"]
    assert loaded.tasks["arena"].schedule.start.isoformat() == "10:28:00"
    assert loaded.tasks["arena"].schedule.end.isoformat() == "10:30:00"


@pytest.mark.parametrize("patch", [
    {"enabled": "false"}, {"version": True}, {"timezone": "UTC"}, {"poll_seconds": 0},
    {"summary_interval_seconds": float("nan")}, {"typo": 1}, {"tasks": []},
])
def test_rejects_invalid_global_config(patch):
    c, _ = modules()
    raw = config({"sample": task()})
    raw.update(patch)
    with pytest.raises(ValueError):
        c.parse_config(raw)


@pytest.mark.parametrize("patch", [
    {"enabled": 1}, {"priority": True}, {"timeout_seconds": -1}, {"retry_seconds": float("inf")},
    {"schedule": {"kind": "interval", "interval_seconds": 0}},
    {"schedule": {"kind": "daily_window", "start": "10:30", "end": "10:28", "interval_seconds": 1}},
    {"schedule": {"kind": "daily_window", "start": "25:00", "end": "26:00", "interval_seconds": 1}},
    {"params": []}, {"unknown_field": 1},
])
def test_rejects_invalid_task_config(patch):
    c, _ = modules()
    with pytest.raises(ValueError):
        c.parse_config(config({"sample": task(**patch)}))


def test_normalizes_excluded_ids_without_evaluating_config():
    c, _ = modules()
    raw = config({"arena": task(params={"excluded_player_ids": ["安卓|天书通悟561服#12402987", 12402987, "456"]})})
    assert c.parse_config(raw).tasks["arena"].params["excluded_player_ids"] == [12402987, 456]
    for invalid in [True, "name", "abc#12oops", 0, -1, "#"]:
        with pytest.raises(ValueError):
            c.parse_config(config({"arena": task(params={"excluded_player_ids": [invalid]})}))


def test_config_file_rejects_duplicates_and_atomic_switch_preserves_params(tmp_path):
    c, _ = modules()
    path = tmp_path / "daily.json"
    raw = config({"one": task(params={"nested": {"value": 2}}), "two": task()})
    path.write_text(json.dumps(raw), encoding="utf-8")
    c.set_enabled(path, False, "one")
    result = c.load_config(path)
    assert result.enabled and not result.tasks["one"].enabled and result.tasks["two"].enabled
    assert result.tasks["one"].params == raw["tasks"]["one"]["params"]
    c.set_enabled(path, False)
    assert not c.load_config(path).enabled
    before = path.read_bytes()
    with pytest.raises(ValueError):
        c.set_enabled(path, True, "missing")
    assert path.read_bytes() == before
    path.write_text('{"version":1,"version":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        c.load_config(path)


def test_periodic_priority_coalescing_and_wall_clock_independence():
    async def scenario():
        _, s = modules()
        scheduler, clock = make_scheduler(config({"low": task(priority=30), "high": task(priority=10)}))
        called = []
        async def handler(ctx):
            called.append(ctx.task.task_id)
            return s.TaskResult()
        scheduler.register("low", handler)
        scheduler.register("high", handler)
        assert await scheduler.tick() == "high"
        assert await scheduler.tick() == "low"
        assert await scheduler.tick() is None
        clock.wall += timedelta(days=3)
        assert await scheduler.tick() is None
        clock.advance(300)
        assert await scheduler.tick() == "high"
        assert await scheduler.tick() == "low"
        assert await scheduler.tick() is None
        assert called == ["high", "low", "high", "low"]
    asyncio.run(scenario())


def test_periodic_cadence_includes_execution_time_and_coalesces_missed_ticks():
    async def scenario():
        _, s = modules()
        scheduler, clock = make_scheduler(config({"one": task(interval=60)}))
        advances = [40, 130, 0]
        async def handler(ctx):
            clock.advance(advances.pop(0))
            return s.TaskResult()
        scheduler.register("one", handler)
        assert await scheduler.tick() == "one"
        assert scheduler.snapshot()["tasks"]["one"]["next_due_in_seconds"] == 20
        clock.advance(20)
        assert await scheduler.tick() == "one"
        assert scheduler.snapshot()["tasks"]["one"]["next_due_in_seconds"] == 50
        assert await scheduler.tick() is None
        clock.advance(50)
        assert await scheduler.tick() == "one"
    asyncio.run(scenario())


def test_master_task_switches_and_unregistered_task_are_truthful():
    async def scenario():
        c, s = modules()
        scheduler, _ = make_scheduler(config({"disabled": task(enabled=False), "missing": task(), "ready": task()}, enabled=False))
        called = []
        async def handler(ctx):
            called.append(ctx.task.task_id)
            return s.TaskResult()
        scheduler.register("disabled", handler)
        scheduler.register("ready", handler)
        assert await scheduler.tick() is None
        assert scheduler.snapshot()["tasks"]["ready"]["state"] == "disabled"
        scheduler.apply_config(c.parse_config(config({"disabled": task(enabled=False), "missing": task(), "ready": task()})))
        assert scheduler.snapshot()["tasks"]["missing"]["state"] == "unregistered"
        assert await scheduler.tick() == "ready"
        assert called == ["ready"]
        assert scheduler.snapshot()["tasks"]["missing"]["attempts"] == 0
        with pytest.raises(ValueError):
            scheduler.register("ready", handler)
    asyncio.run(scenario())


def test_daily_window_uses_beijing_and_does_not_catch_up_after_close():
    async def scenario():
        _, s = modules()
        schedule = {"kind": "daily_window", "start": "10:28", "end": "10:30", "interval_seconds": 1}
        clock = Clock(datetime(2026, 10, 14, 2, 27, 59, tzinfo=timezone.utc))
        scheduler, _ = make_scheduler(config({"arena": task(schedule=schedule)}), clock)
        contexts = []
        async def handler(ctx):
            contexts.append(ctx)
            return s.TaskResult()
        scheduler.register("arena", handler)
        assert await scheduler.tick() is None
        clock.advance(1)
        assert await scheduler.tick() == "arena"
        assert contexts[0].window_end.hour == 10 and contexts[0].window_end.minute == 30
        clock.advance(119)
        assert await scheduler.tick() == "arena"
        clock.advance(1)
        assert await scheduler.tick() is None
        assert scheduler.snapshot()["tasks"]["arena"]["state"] == "outside_window"
        clock.advance(24 * 3600 - 120)
        assert await scheduler.tick() == "arena"
    asyncio.run(scenario())


def test_single_task_at_a_time_and_shutdown_waits_for_handler_cleanup():
    async def scenario():
        _, s = modules()
        scheduler, _ = make_scheduler(config({"one": task(), "two": task()}))
        entered = asyncio.Event()
        release = asyncio.Event()
        cleaned = []
        async def handler(ctx):
            entered.set()
            try:
                await release.wait()
                assert ctx.stop_requested()
                return s.TaskResult()
            finally:
                cleaned.append(ctx.task.task_id)
        scheduler.register("one", handler)
        scheduler.register("two", handler)
        first = asyncio.create_task(scheduler.tick())
        await entered.wait()
        assert await scheduler.tick() is None
        scheduler.stop()
        assert not first.done()
        release.set()
        assert await first == "one"
        assert cleaned == ["one"]
        assert await scheduler.tick() is None
        assert not scheduler.running_task
    asyncio.run(scenario())


def test_failures_back_off_and_wait_results_control_next_check():
    async def scenario():
        _, s = modules()
        scheduler, clock = make_scheduler(config({"bad": task(priority=10, retry_seconds=120), "good": task()}))
        async def bad(ctx):
            raise s.RetryableTaskError("已确认本轮未产生外部效果")
        async def good(ctx):
            return s.TaskResult(status="waiting", message="次数已耗尽", next_delay_seconds=300)
        scheduler.register("bad", bad)
        scheduler.register("good", good)
        assert await scheduler.tick() == "bad"
        assert scheduler.snapshot()["tasks"]["bad"]["state"] == "failed"
        assert await scheduler.tick() == "good"
        assert scheduler.snapshot()["tasks"]["good"]["state"] == "waiting"
        clock.advance(60)
        assert await scheduler.tick() is None
        clock.advance(60)
        assert await scheduler.tick() == "bad"
        assert scheduler.snapshot()["tasks"]["bad"]["failures"] == 2
    asyncio.run(scenario())


def test_timeout_pauses_all_dispatch_and_awaits_cleanup_before_resume():
    async def scenario():
        _, s = modules()
        scheduler, _ = make_scheduler(config({"hang": task(priority=10, timeout_seconds=0.02), "other": task()}))
        cleanup = []
        async def hang(ctx):
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.append(True)
        async def other(ctx):
            return s.TaskResult()
        scheduler.register("hang", hang)
        scheduler.register("other", other)
        assert await scheduler.tick() == "hang"
        assert cleanup == [True]
        assert scheduler.snapshot()["blocked_reason"]
        assert scheduler.snapshot()["tasks"]["hang"]["state"] == "uncertain"
        assert await scheduler.tick() is None
        scheduler.resume_after_verification()
        assert await scheduler.tick() == "other"
    asyncio.run(scenario())


def test_hourly_summary_logs_once_and_no_per_minute_success_spam(caplog):
    async def scenario():
        _, s = modules()
        scheduler, clock = make_scheduler(config({"one": task()}))
        async def handler(ctx):
            return s.TaskResult(message="正常")
        scheduler.register("one", handler)
        await scheduler.tick()
        assert not [r for r in caplog.records if r.levelno >= logging.INFO]
        clock.advance(3600)
        await scheduler.tick()
        summaries = [r for r in caplog.records if "日常任务摘要" in r.message]
        assert len(summaries) == 1
        await scheduler.tick()
        assert len([r for r in caplog.records if "日常任务摘要" in r.message]) == 1
    with caplog.at_level(logging.INFO):
        asyncio.run(scenario())


def test_cli_validate_list_switches_and_run_once_do_not_execute_game(tmp_path):
    modules()
    path = tmp_path / "daily.json"
    path.write_text(json.dumps(config({"custom": task()})), encoding="utf-8")
    script = ROOT / "tools" / "daily_tasks.py"
    def cli(*args):
        process = subprocess.run([sys.executable, str(script), *args, "--config", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=15)
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)
    assert cli("validate")["ok"]
    assert cli("list")["tasks"]["custom"]["state"] == "unregistered"
    assert cli("run", "--once")["tasks"]["custom"]["attempts"] == 0
    cli("disable", "--task", "custom")
    assert cli("list")["tasks"]["custom"]["state"] == "disabled"
    cli("disable")
    assert not cli("list")["enabled"]


def test_timeout_remains_uncertain_if_handler_swallows_cancellation():
    async def scenario():
        _, s = modules()
        scheduler, _ = make_scheduler(config({"one": task(timeout_seconds=0.01)}))
        async def handler(ctx):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return s.TaskResult(message="已收尾，但仍发生过超时")
        scheduler.register("one", handler)
        assert await scheduler.tick() == "one"
        state = scheduler.snapshot()
        assert state["blocked_reason"]
        assert state["tasks"]["one"]["state"] == "uncertain"
        assert state["tasks"]["one"]["successes"] == 0
        assert await scheduler.tick() is None
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["none", "exception", "explicit_unknown"])
def test_unconfirmed_result_blocks_all_automatic_retries(mode):
    async def scenario():
        _, s = modules()
        scheduler, clock = make_scheduler(config({"one": task()}))
        effects = []
        async def handler(ctx):
            effects.append("执行")
            if mode == "exception":
                raise ValueError("操作已发出，结果读取异常")
            if mode == "explicit_unknown":
                raise s.ExecutionUncertain("响应丢失")
            return None
        scheduler.register("one", handler)
        await scheduler.tick()
        assert scheduler.snapshot()["tasks"]["one"]["state"] == "uncertain"
        assert scheduler.blocked_reason
        clock.advance(3600)
        assert await scheduler.tick() is None
        assert effects == ["执行"]
    asyncio.run(scenario())


@pytest.mark.parametrize("once", [False, True])
def test_cli_cancellation_requests_stop_and_waits_for_normal_cleanup(tmp_path, once):
    async def scenario():
        _, s = modules()
        from tools.daily_tasks import run_scheduler
        path = tmp_path / "daily.json"
        raw = config({"one": task()})
        path.write_text(json.dumps(raw), encoding="utf-8")
        scheduler, _ = make_scheduler(raw)
        entered, saw_stop, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        cancelled = []
        async def handler(ctx):
            entered.set()
            try:
                while not ctx.stop_requested():
                    await asyncio.sleep(0)
                saw_stop.set()
                await release.wait()
                return s.TaskResult()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
        scheduler.register("one", handler)
        runner = asyncio.create_task(run_scheduler(scheduler, path, once))
        await entered.wait()
        runner.cancel()
        try:
            await asyncio.wait_for(saw_stop.wait(), 0.2)
            assert not runner.done()
            assert not cancelled
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await runner
        assert not cancelled
        assert scheduler.snapshot()["tasks"]["one"]["successes"] == 1
        assert not scheduler.running_task
    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["poll_seconds", "summary_interval_seconds"])
def test_huge_numbers_are_reported_as_config_errors(field):
    c, s = modules()
    with pytest.raises(ValueError):
        c.parse_config(config({}, **{field: 10**400}))
    with pytest.raises(ValueError):
        s.TaskResult(next_delay_seconds=10**400)


def test_rejects_submillisecond_timing_configuration():
    c, s = modules()
    for key in ("poll_seconds", "summary_interval_seconds"):
        with pytest.raises(ValueError):
            c.parse_config(config({}, **{key: 1e-320}))
    for patch in ({"schedule": {"kind": "interval", "interval_seconds": 1e-320}},
                  {"timeout_seconds": 1e-320}, {"retry_seconds": 1e-320}):
        with pytest.raises(ValueError):
            c.parse_config(config({"one": task(**patch)}))
    with pytest.raises(ValueError):
        s.TaskResult(next_delay_seconds=1e-320)


def test_hot_reload_pauses_invalid_config_then_resumes():
    async def scenario():
        c, s = modules()
        raw = config({"one": task()}, poll_seconds=0.001)
        scheduler, _ = make_scheduler(raw)
        loads = []
        effects = []
        async def handler(ctx):
            effects.append(True)
            assert not scheduler.config_error
            scheduler.stop()
            return s.TaskResult()
        def loader():
            loads.append(True)
            if len(loads) == 1:
                return c.parse_config(config({}, poll_seconds=10**400))
            assert scheduler.config_error
            assert not effects
            return c.parse_config(raw)
        scheduler.register("one", handler)
        await scheduler.run(config_loader=loader)
        assert len(loads) == 2
        assert effects == [True]
    asyncio.run(scenario())
