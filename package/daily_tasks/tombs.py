"""三尸/法器墓：正常UI收取重开、公开目标盗掠与填土。"""

from __future__ import annotations

import asyncio
import logging

from . import timing
from .scheduler import ExecutionUncertain, RetryableTaskError, TaskContext, TaskResult

LOG = logging.getLogger("plugin_manager.tombs")


def _confirmed(receipt, action: str) -> dict:
    if not isinstance(receipt, dict) or receipt.get("confirmed") is not True:
        raise ExecutionUncertain(f"{action}未获得明确回执，禁止重复调用")
    return receipt


def _label(target: dict | None) -> str:
    """候选展示名：有名字就带名字和服务器，没有只显示ID。"""
    if not target:
        return "无"
    name = str(target.get("name") or "").strip()
    server = str(target.get("server") or "").strip()
    return f"{server}·{name}({target['id']})" if name else f"玩家{target['id']}"


class _TombTask:
    def __init__(self, game, kind: str) -> None:
        if kind not in ("sanshi", "artifact"):
            raise ValueError("墓类型仅支持 sanshi/artifact")
        self.game = game
        self.kind = kind
        self.name = "三尸" if kind == "sanshi" else "法器"
        self.uncertain = ""

    async def __call__(self, ctx: TaskContext) -> TaskResult:
        return await self.run(ctx)

    async def run(self, ctx: TaskContext, *, force_trigger: bool = False) -> TaskResult:
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        if self.uncertain:
            raise ExecutionUncertain(self.uncertain)
        # 每轮任务都从大厅开始；战斗或阻挡界面不强退。
        try:
            await self.game.home()
        except RetryableTaskError as exc:
            LOG.warning("%s墓开始前返回主界面暂不可用：%s", self.name, exc)
            return TaskResult("waiting", str(exc), ctx.task.retry_seconds)
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        try:
            try:
                result = await self._perform(ctx)
            except RetryableTaskError as exc:
                LOG.warning("%s墓操作明确拒绝或暂不可用：%s", self.name, exc)
                result = TaskResult("waiting", str(exc), ctx.task.retry_seconds)
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            try:
                await self.game.home()
            except RetryableTaskError as exc:
                LOG.warning("%s墓正常返回主界面暂不可用：%s", self.name, exc)
                return TaskResult("waiting", str(exc), ctx.task.retry_seconds)
            return result
        except asyncio.CancelledError:
            self.uncertain = f"{self.name}墓任务被取消，需核对当前UI回执后再执行"
            LOG.error(self.uncertain)
            raise
        except Exception as exc:
            self.uncertain = str(exc) if isinstance(exc, ExecutionUncertain) else f"{self.name}墓流程结果未确认：{exc}"
            LOG.error(self.uncertain)
            if isinstance(exc, ExecutionUncertain):
                raise
            raise ExecutionUncertain(self.uncertain) from exc

    def _wait_until(self, ctx: TaskContext, when, now, reason: str) -> TaskResult:
        """按到期时间等待；算不出来就退回任务自带的重扫间隔。"""
        seconds = timing.delay_until(when, now)
        if seconds is None:
            return TaskResult("waiting", reason, ctx.task.params.get("rescan_seconds", 60))
        delay = timing.clamp_delay(seconds)
        LOG.info("%s墓%s，预计 %s 后到期；本次等待 %s 后校准", self.name, reason,
                 timing.describe(seconds), timing.describe(delay))
        return TaskResult("waiting", f"{self.name}墓{reason}，预计{timing.describe(seconds)}后到期", delay)

    def _wait_for_cross_day(self, ctx: TaskContext, state: dict, reason: str) -> TaskResult:
        """今日次数用完：等到跨日，不再按分钟轮询。"""
        seconds = timing.seconds_until_cross_day(state.get("cross_day_at"), state.get("server_now"))
        if seconds is None:
            return TaskResult("waiting", reason, ctx.task.params.get("rescan_seconds", 60))
        delay = timing.clamp_delay(seconds)
        LOG.info("%s墓%s，距跨日还有 %s；本次等待 %s 后校准", self.name, reason,
                 timing.describe(seconds), timing.describe(delay))
        return TaskResult("waiting", f"{self.name}墓{reason}，距跨日还有{timing.describe(seconds)}", delay)

    async def _state(self, *fields: str) -> dict:
        read = (getattr(self.game, "tomb_counts", self.game.tomb_state)
                if fields and all(field.endswith("_remaining") for field in fields) else self.game.tomb_state)
        state = await read(self.kind)
        if not isinstance(state, dict) or type(state.get("ready")) is not bool:
            raise RetryableTaskError(f"{self.name}墓状态缺少明确就绪标记")
        if state["ready"]:
            for field in fields:
                value = state.get(field)
                if field.endswith("_remaining"):
                    if type(value) is not int or value < 0:
                        raise RetryableTaskError(f"{self.name}墓{field}次数不是有效非负整数")
                elif type(value) is not bool:
                    raise RetryableTaskError(f"{self.name}墓{field}状态不是明确布尔值")
        return state

    async def _targets(self, mode: str, minimum: int = 0, exclude_ids=None, preferred_id=None) -> tuple[list[dict], dict]:
        payload = await self.game.tomb_targets(self.kind, mode, refresh=True, minimum=minimum,
                                               **({"exclude_ids": exclude_ids} if exclude_ids else {}),
                                               **({"preferred_id": preferred_id} if preferred_id else {}))
        scan = {}
        if isinstance(payload, dict):
            scan = {key: payload.get(key, 0) for key in ("refresh_count", "new_players")}
            payload = payload.get("targets")
        targets = payload
        if not isinstance(targets, list) or any(not isinstance(target, dict) for target in targets):
            raise RetryableTaskError(f"{self.name}墓公开候选列表无效")
        for target in targets:
            if type(target.get("id")) is not int or target["id"] <= 0:
                raise RetryableTaskError(f"{self.name}墓候选玩家ID无效")
            if mode == "raid":
                if type(target.get("site_num")) is not int or target["site_num"] < 0:
                    raise RetryableTaskError(f"{self.name}墓候选公开墓数无效")
            elif type(target.get("can_fill")) is not bool:
                raise RetryableTaskError(f"{self.name}墓候选填土状态不明确")
        return targets, scan


class TombCycleTask(_TombTask):
    async def _perform(self, ctx: TaskContext) -> TaskResult:
        state = await self._state("finished", "filling", "idle")
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        if not state["ready"]:
            return TaskResult("waiting", f"{self.name}墓界面尚未就绪")
        collected = False
        if state["finished"]:
            _confirmed(await self.game.tomb_collect(self.kind), f"{self.name}墓收取")
            LOG.info("%s墓到期收取已确认", self.name)
            collected = True
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            state = await self._state("finished", "filling", "idle")
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            if not state["ready"]:
                return TaskResult("waiting", f"{self.name}墓已收取，界面尚未就绪")
        if state["idle"]:
            _confirmed(await self.game.tomb_start(self.kind), f"{self.name}墓重开")
            LOG.info("%s墓重开已确认", self.name)
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            if ctx.task.params.get("recruit", True):
                _confirmed(await self.game.tomb_recruit(self.kind), f"{self.name}墓招募")
                LOG.info("%s墓重开后招募已确认", self.name)
            return TaskResult("success", f"{self.name}墓已正常重开")
        if collected:
            return TaskResult("success", f"{self.name}墓到期收益已收取")
        # 还没到期：按墓的到期时间等，不要每分钟都来看一次。
        return self._wait_until(ctx, state.get("next_ready_at"), state.get("server_now"),
                               "尚未到期，无需收取或招募")


class TombRaidTask(_TombTask):
    def __init__(self, game, kind: str, failed_ids: set[int] | None = None, history=None) -> None:
        super().__init__(game, kind)
        self.failed_ids = failed_ids if failed_ids is not None else set()
        self.loss_streaks = {}
        self.history = history
        self._owner = None

    async def _load_history(self):
        if self.history is None:
            return
        identity = await self.game.identity()
        owner = str(identity.get("player_id") or "") if isinstance(identity, dict) else ""
        if not owner:
            raise RetryableTaskError("当前角色ID尚未确认，不能读取墓藏战败名单")
        if owner != self._owner:
            self.loss_streaks = self.history.load(owner, self.kind)
            self.failed_ids.clear()
            self.failed_ids.update(key for key, count in self.loss_streaks.items() if count >= 3)
            self._owner = owner
            if self.failed_ids:
                LOG.info("%s墓已读取角色%s的打不过名单：%d名玩家，后续跳过", self.name, owner, len(self.failed_ids))

    async def _perform(self, ctx: TaskContext) -> TaskResult:
        await self._load_history()
        state = await self._state("raid_remaining")
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        if not state["ready"]:
            return TaskResult("waiting", f"{self.name}墓界面尚未就绪")
        if state["raid_remaining"] == 0:
            return self._wait_for_cross_day(ctx, state, "今日盗掠次数已用完")
        minimum = ctx.task.params.get("minimum_tombs", 16)
        wins, losses = 0, 0
        refused = set()
        retry_target = None
        # 只要还有次数就继续打：每轮重新读次数，打完立刻判断能不能再来一次。
        while state["raid_remaining"] > 0:
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            excluded = refused | self.failed_ids
            targets, scan = await self._targets("raid", minimum, excluded, retry_target)
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            best = max(targets, key=lambda item: item["site_num"], default=None)
            LOG.info("%s墓盗掠扫描：刷新%d次，新增%d名玩家，最多可盗 %s（%d棺），门槛%d，剩余%d次",
                     self.name, scan.get("refresh_count", 0), scan.get("new_players", 0),
                     _label(best) if best else "无", best["site_num"] if best else 0, minimum,
                     state["raid_remaining"])
            eligible = [item for item in targets if item["site_num"] >= minimum and item["id"] not in excluded]
            target = next((item for item in eligible if item["id"] == retry_target), None)
            target = target or next(iter(eligible), None)
            if target is None:
                break
            target_id = target["id"]
            before = state["raid_remaining"]
            try:
                receipt = _confirmed(await self.game.tomb_raid(self.kind, target_id), f"{self.name}墓盗掠")
            except RetryableTaskError as exc:
                refused.add(target_id)
                retry_target = None
                LOG.warning("%s墓盗掠目标%s未执行，重新扫描其他目标：%s", self.name, _label(target), exc)
                continue
            if type(receipt.get("win")) is not bool:
                raise ExecutionUncertain(f"{self.name}墓盗掠胜负未确认，禁止重复调用")
            if not receipt["win"]:
                losses += 1
                count = min(3, self.loss_streaks.get(target_id, 0) + 1)
                self.loss_streaks[target_id] = count
                if count >= 3:
                    self.failed_ids.add(target_id)
                    refused.add(target_id)
                    retry_target = None
                    LOG.warning("%s墓盗掠玩家%s连续战败3次，标记打不过，后续跳过该玩家", self.name, _label(target))
                else:
                    retry_target = target_id
                    LOG.warning("%s墓盗掠玩家%s第%d/3次战败，优先重新寻找该玩家，最多再试%d次",
                                self.name, _label(target), count, 3-count)
            else:
                wins += 1
                self.loss_streaks.pop(target_id, None)
                self.failed_ids.discard(target_id)
                retry_target = None
                LOG.info("%s墓盗掠玩家%s胜利已确认", self.name, _label(target))
            if self.history is not None:
                self.history.save(self._owner, self.kind, self.loss_streaks)
            # 打完重新确认还剩几次，不用本地推算。
            state = await self._state("raid_remaining")
            if not state["ready"]:
                return TaskResult("waiting", f"{self.name}墓界面尚未就绪")
            # 已确认战败可能不扣盗掠次数；三次战败上限负责阻止死循环。
            if state["raid_remaining"] > before or (receipt["win"] and state["raid_remaining"] >= before):
                raise ExecutionUncertain(f"{self.name}墓盗掠已结算但次数未减少，停止重复操作")
        if wins == 0 and losses == 0:
            LOG.info("%s墓本轮没有可盗掠目标（门槛%d），等待下次扫描", self.name, minimum)
            return TaskResult("waiting", f"{self.name}墓暂无单玩家墓数≥{minimum}的可盗掠目标，等待下次扫描",
                              ctx.task.retry_seconds if refused else ctx.task.params.get("rescan_seconds", 60))
        LOG.info("%s墓本轮盗掠完成：胜%d次、负%d次，剩余%d次", self.name, wins, losses, state["raid_remaining"])
        return TaskResult("success" if wins else "waiting",
                          f"{self.name}墓本轮盗掠完成：胜{wins}次、负{losses}次，剩余{state['raid_remaining']}次")


class TombFillTask(_TombTask):
    async def _perform(self, ctx: TaskContext) -> TaskResult:
        state = await self._state("fill_remaining")
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        if not state["ready"]:
            return TaskResult("waiting", f"{self.name}墓界面尚未就绪")
        if state["fill_remaining"] == 0:
            return self._wait_for_cross_day(ctx, state, "今日填土次数已用完")
        targets, scan = await self._targets("fill")
        if ctx.stop_requested():
            return TaskResult("waiting", "已请求停止")
        LOG.info("%s墓填土扫描：刷新%d次，当前列表可填%d个目标，剩余次数%d", self.name,
                 scan.get("refresh_count", 0), sum(1 for item in targets if item["can_fill"]),
                 state["fill_remaining"])
        filled, refused = [], set()
        # 一直填到次数用完；同一个玩家可以反复填，只有被明确拒绝才换下一个。
        attempts = 0
        limit = state["fill_remaining"] * 3 + len(targets) + 5
        while True:
            if ctx.stop_requested():
                return TaskResult("waiting", "已请求停止")
            state = await self._state("fill_remaining")
            if not state["ready"]:
                return TaskResult("waiting", f"{self.name}墓界面尚未就绪")
            if state["fill_remaining"] <= 0:
                break
            if attempts >= limit:
                LOG.warning("%s墓填土尝试%d次后停止，避免死循环", self.name, attempts)
                break
            candidate = next((item for item in targets if item["can_fill"] and item["id"] not in refused), None)
            if candidate is None:
                # 当前列表都填不动了，重新拉一次列表再试；仍没有就结束本轮。
                targets, scan = await self._targets("fill")
                if ctx.stop_requested():
                    return TaskResult("waiting", "已请求停止")
                candidate = next((item for item in targets if item["can_fill"] and item["id"] not in refused), None)
                if candidate is None:
                    break
            attempts += 1
            try:
                _confirmed(await self.game.tomb_fill(self.kind, candidate["id"]), f"{self.name}墓填土")
            except RetryableTaskError as exc:
                LOG.warning("%s墓为%s填土未执行：%s", self.name, _label(candidate), exc)
                refused.add(candidate["id"])
                continue
            filled.append(candidate["id"])
            before = state["fill_remaining"]
            state = await self._state("fill_remaining")
            if not state["ready"] or state["fill_remaining"] >= before:
                raise ExecutionUncertain(f"{self.name}墓填土已确认但次数未减少，停止重复操作")
            LOG.info("%s墓为%s填土已确认，本轮剩余填土次数%d", self.name, _label(candidate),
                     state["fill_remaining"])
        if not filled:
            detail = f"，被拒绝{len(refused)}个" if refused else ""
            return TaskResult("waiting", f"{self.name}墓本轮没有成功填土的目标{detail}",
                              ctx.task.params.get("rescan_seconds", 60))
        return TaskResult("success", f"{self.name}墓本轮填土{len(filled)}次（可重复填同一玩家），" +
                          f"剩余次数{state['fill_remaining']}")
