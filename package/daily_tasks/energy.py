"""体力防溢出：只切已有方案，正常扫荡，确认后恢复原配置。"""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import os
from pathlib import Path

import logging

from . import timing
from .scheduler import ExecutionUncertain, RetryableTaskError, Scheduler, TaskContext, TaskResult

LOG = logging.getLogger("plugin_manager.energy")

# 每点体力的恢复秒数（实测 420 秒/点），可在任务参数里覆盖。
DEFAULT_ENERGY_RECOVER_SECONDS = 420.0


def _finite_number(value, label: str) -> float:
    if type(value) not in (int, float):
        raise RetryableTaskError(f"{label}不是有效数值")
    try:
        number = float(value)
    except OverflowError as exc:
        raise RetryableTaskError(f"{label}超出范围") from exc
    if not math.isfinite(number):
        raise RetryableTaskError(f"{label}不是有限数值")
    return number


class EnergyTask:
    def __init__(self, game, journal_path: Path | None) -> None:
        self.game = game
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self.pending_original = None

    def _save_original(self, original: dict) -> None:
        if self.journal_path is None:
            self.pending_original = original
            return
        try:
            fd = os.open(self.journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ExecutionUncertain("存在未恢复的扫荡记录，禁止覆盖或开始新一轮") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(original, file, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())

    async def __call__(self, ctx: TaskContext) -> TaskResult:
        return await self.run(ctx)

    async def run(self, ctx: TaskContext, *, force_trigger: bool = False) -> TaskResult:
        if self.pending_original is not None or (self.journal_path is not None and (self.journal_path.exists() or self.journal_path.is_symlink())):
            raise ExecutionUncertain("存在未确认的原配置，先核对当前会话，不自动重试")
        info = await self.game.inspect()
        current = _finite_number(info["energy"], "体力")
        maximum = _finite_number(info["maximum"], "体力上限")
        if maximum <= 0 or current < 0:
            raise RetryableTaskError("体力或上限无效")
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        if not force_trigger and current < maximum * ctx.task.params.get("trigger_ratio", 0.9):
            return self._wait_for_threshold(ctx, info, current, maximum)
        async with self.game.transaction(self.journal_path):
            # 每轮任务从主界面开始；普通功能页走正常关闭，战斗/未决状态不可强退。
            try:
                await self.game.home()
            except RetryableTaskError as exc:
                return TaskResult("waiting", str(exc))
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            info = await self.game.inspect()
            if not info.get("safe"):
                detail = ', '.join(info.get('blockers', []))
                return TaskResult("waiting", "主界面仍不可操作：" + (detail or '界面尚未就绪'))
            return await self._sweep(ctx)

    def _wait_for_threshold(self, ctx: TaskContext, info: dict, current: float, maximum: float) -> TaskResult:
        """按体力恢复速度算出还要多久，到点再扫荡；拿不到数据就退回任务间隔。"""
        threshold = maximum * ctx.task.params.get("trigger_ratio", 0.9)
        recover = ctx.task.params.get("energy_recover_seconds", DEFAULT_ENERGY_RECOVER_SECONDS)
        seconds = timing.seconds_until_energy(current, threshold, recover,
                                              info.get("last_recovery"), info.get("server_now"))
        if seconds is None:
            return TaskResult("waiting", f"体力{current:g}/{maximum:g}，未达触发阈值")
        delay = timing.clamp_delay(seconds)
        total = timing.describe(seconds)
        planned = timing.describe(delay)
        LOG.info("体力 %g/%g，还差 %g 点（每点 %g 秒），预计 %s 后达到阈值；本次等待 %s 后校准",
                 current, maximum, max(threshold - current, 0), recover, total, planned)
        previous = getattr(self, "_planned_energy_at", None)
        self._planned_energy_at = info.get("server_now")
        if previous is not None and abs((info.get("server_now") or 0) - previous) > 0:
            LOG.info("体力定时已按最新数据校准（上次读数 %s）", previous)
        return TaskResult("waiting", f"体力{current:g}/{maximum:g}，预计{total}后达到阈值", delay)

    async def _sweep(self, ctx: TaskContext) -> TaskResult:
        catalog = await self.game.catalog(ctx.task.params.get("formation_eye_name", "双子僵尸"))
        if not catalog.get("eye") or not catalog.get("sanshi") or not catalog.get("magic"):
            return TaskResult("waiting", "缺少指定阵眼或可用已有方案，未切换/未扫荡")
        original = await self.game.capture()
        selection = original.get("selection", {})
        if not selection.get("eye") or not selection.get("artifact") or not original.get("formation"):
            return TaskResult("waiting", "原阵眼/法器未装备或阵法未开启，无法保证恢复，未改变配置")
        if selection.get("sanshi") not in catalog["sanshi"] or not any(
            item["artifact"] == selection["artifact"] and item["plan"] == selection.get("plan") for item in catalog["magic"]
        ):
            return TaskResult("waiting", "原配置不在当前可用已有组合中，未改变配置")
        self._save_original(original)
        uncertain = False
        result = TaskResult("waiting", "尚未扫荡")
        try:
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            await self.game.set_eye(catalog["eye"])
            # 方案选择交给驻留脚本：三尸页内逐个实测、法器按词条数据直选，不再逐组合反复开关页面。
            optimized = await self.game.optimize()
            if not isinstance(optimized, dict) or not isinstance(optimized.get("choice"), dict):
                raise ExecutionUncertain("方案选择回执无效，未确认当前配置，禁止继续扫荡")
            best_score = _finite_number(optimized["gold"], "自身贪财")
            LOG.info("方案已选定：三尸%s（各方案实测贪财 %s）、法器%s、方案%s，贪财%g",
                     optimized["choice"]["sanshi"], optimized.get("measured") or "未返回",
                     optimized["choice"]["artifact"], optimized["choice"]["plan"], best_score)
            result = await self.perform(ctx, best_score)
        except ExecutionUncertain:
            uncertain = True
            raise
        except RetryableTaskError as exc:
            result = TaskResult("waiting", str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            uncertain = True
            raise ExecutionUncertain(f"扫荡流程异常，保留原配置记录：{exc}") from exc
        finally:
            if not uncertain:
                async def restore():
                    try:
                        restored = await self.game.restore(original)
                        if restored != original:
                            raise ExecutionUncertain("原方案、阵眼或阵脚恢复校验不一致")
                        await self.game.home()
                        if self.journal_path is not None:
                            self.journal_path.unlink()
                        self.pending_original = None
                    except Exception as exc:
                        raise ExecutionUncertain(f"恢复未确认，保留记录 {self.journal_path}：{exc}") from exc
                cleanup = asyncio.create_task(restore())
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await asyncio.shield(cleanup)
                    raise
        return result

    async def perform(self, ctx: TaskContext, best_score: float) -> TaskResult:
        count = 0
        while not ctx.stop_requested():
            before = await self.game.quote()
            cost = _finite_number(before["cost"], "扫荡体力消耗")
            energy = _finite_number(before["energy"], "当前体力")
            if not before.get("allowed") or energy < cost:
                break
            if cost <= 0:
                raise RetryableTaskError("扫荡消耗为0，停止以避免无限调用")
            after = await self.game.sweep()
            before_count = before.get("completed_count", before["sweep_num"])
            after_count = after.get("completed_count", after.get("sweep_num", -1))
            if after_count <= before_count or after.get("energy", energy) >= energy:
                raise ExecutionUncertain("扫荡返回成功但自身次数/体力未确认变化，不重复调用")
            count += 1
            LOG.info("扫荡第%d次已确认：%s倍消耗体力%g，体力 %g→%g，今日已完成%d次", count,
                     after.get("times", before.get("times", 1)), _finite_number(after.get("cost", cost), "本次消耗"),
                     energy, after.get("energy", energy), after_count)
        return TaskResult("success" if count else "waiting", f"完成{count}次正常扫荡；已有组合贪财{best_score:g}")


def register_energy(scheduler: Scheduler, game, journal_path: Path) -> None:
    if "energy" in scheduler.config.tasks:
        scheduler.register("energy", EnergyTask(game, journal_path))
