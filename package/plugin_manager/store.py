"""独立插件配置存储：仅保存配置，不保存任务进度、玩家快照或连接状态。"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from package.daily_tasks.config import parse_config

from .feature_flags import task_enabled
from .battle_assist import default_battle_assist, validate_battle_assist
from .paths import default_config_path

SECONDS_MAX = 604800
PRIORITY_MAX = 1000000
BLOODMOON_POWER_MAX = 9007199254740991  # JavaScript safe integer; independent from task priorities.
RATIO_MIN = 0.01

# 九个已定义任务；构建期开关关掉的那些不进配置（见 default_config）。
TASK_IDS = ("energy", "offline_reward", "sanshi_tombs", "artifact_tombs",
            "sanshi_raid", "artifact_raid", "sanshi_fill", "artifact_fill", "arena")


def _check_seconds(value, label):
    if value > SECONDS_MAX or abs(value - round(value, 3)) > 1e-12:
        raise ValueError(f"{label} 只支持0.001至{SECONDS_MAX}秒，最多三位小数")


def default_config() -> dict:
    # 默认值属于独立GUI，不读取旧CLI的可变配置或运行记录。
    tasks = {}
    for kind, title in (("sanshi", "三尸"), ("artifact", "法器")):
        for action, name, priority, timeout, params in (
            ("tombs", "墓藏收取与重开", 20, 60, {"recruit": True}),
            # 三尸门槛16；法器普遍攒不满，10棺就可以盗。
            ("raid", "盗掠扫描", 50, 180, {"minimum_tombs": 16 if kind == "sanshi" else 10,
                                        "rescan_seconds": 60, "skip_failed_players": True}),
            ("fill", "填土扫描", 60, 60, {}),
        ):
            tasks[f"{kind}_{action}"] = {"name": title + name, "enabled": False, "priority": priority,
                                        "timeout_seconds": timeout, "retry_seconds": 60,
                                        "schedule": {"kind": "interval", "interval_seconds": 60}, "params": params}
    tasks["energy"] = {
        "name": "体力检查与扫荡", "enabled": False, "priority": 30, "timeout_seconds": 120, "retry_seconds": 60,
        "schedule": {"kind": "interval", "interval_seconds": 60},
        "params": {"trigger_ratio": 0.9, "spend_mode": "all_available", "sanshi_plan_scope": "existing",
                   "artifact_plan_scope": "existing", "formation_eye_name": "双子僵尸", "restore_original": True,
                   "energy_recover_seconds": 420},
    }
    tasks["offline_reward"] = {
        "name": "每小时领取挂机收益", "enabled": False, "priority": 40, "timeout_seconds": 60, "retry_seconds": 60,
        # 一小时内挂机时长不会变够，没必要每分钟跑一趟。
        "schedule": {"kind": "interval", "interval_seconds": 3600},
        "params": {"claim_interval_seconds": 3600, "restore_original": True},
    }
    tasks["arena"] = {
        "name": "最后两分钟斗法", "enabled": False, "priority": 10, "timeout_seconds": 30, "retry_seconds": 5,
        "schedule": {"kind": "daily_window", "start": "10:28", "end": "10:30", "interval_seconds": 1},
        "params": {"excluded_player_ids": [], "continuous": True, "skip_battle": True},
    }
    # 构建期关掉的任务不进默认配置，玩家也就无从打开。
    tasks = {key: value for key, value in tasks.items() if task_enabled(key)}
    daily = {"version": 1, "enabled": False, "timezone": "Asia/Shanghai", "poll_seconds": 1,
             "summary_interval_seconds": 3600, "tasks": tasks}
    return {"version": 1, "daily": daily, "player": {"enabled": False},
            "ui": {"delay_ms": 500, "game_overlays": True},
            "treasure": {"enabled": False, "auto_dump": False, "overlay": False, "refresh_seconds": 30},
            "damage": {"enabled": False, "auto_csv": True},
            # 三尸自动合成：kind 1贪 2嗔 3痴；expected_rate 是报告里理论曲线的默认成功率（百分数）。
            "desire": {"kind": 1, "start_quality": 1, "max_material_quality": 4,
                       "fail_limits": {"1": 4, "2": 4, "3": 4, "4": 4},
                       "max_attempts": 200, "expected_rate": 30.0},
            "battle_assist": default_battle_assist(),
            "bloodmoon": {"enabled": False,
                          "flag_probe": {"refresh_seconds": 5, "top_members": 3},
                          "speed_up": {"enabled": False, "max_times": 15,
                                       "safety_margin_seconds": 2, "poll_seconds": 2},
                          "attack": {"enabled": False, "power_ratio": 100, "power_limit": 0,
                                     "max_battles": 10, "wait_seconds": 0},
                          "stealth_mark": {"enabled": False}}}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON重复字段：{key}")
        result[key] = value
    return result


def _build_daily_tasks(raw_tasks) -> dict:
    """按本次构建的开关裁出任务表：没打包的丢掉，缺的用默认值补上。

    构建期关掉的任务不进默认配置（玩家也就无从打开），所以校验不能按「九个任务」
    硬卡——否则任何关掉过任务的产物，在没写过配置的机器上都会因为默认配置少了
    任务而加载失败。反过来，从完整版换到精简版时老配置里多出来的任务也不该把
    整份配置判死。认不到的任务 id 仍然拒绝。
    """
    tasks = raw_tasks if isinstance(raw_tasks, dict) else {}
    unknown = set(tasks) - set(TASK_IDS)
    if unknown:
        raise ValueError(f"插件GUI配置含未知任务：{'、'.join(sorted(unknown))}")
    defaults = default_config()["daily"]["tasks"]
    return {
        task_id: copy.deepcopy(tasks.get(task_id, defaults[task_id]))
        for task_id in TASK_IDS
        if task_enabled(task_id)
    }


def validate_config(raw: dict) -> dict:
    if not isinstance(raw, dict) or not {"version", "daily", "player"}.issubset(raw) or set(raw) - {"version", "daily", "player", "ui", "treasure", "damage", "desire", "bloodmoon", "battle_assist"}:
        raise ValueError("插件配置仅允许 version/daily/player/ui/treasure/damage/desire/bloodmoon/battle_assist，不接受运行状态")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("插件配置 version 必须是1")
    raw_daily = raw["daily"]
    if isinstance(raw_daily, dict):
        raw_daily = dict(raw_daily)
        raw_daily["tasks"] = _build_daily_tasks(raw_daily.get("tasks"))
    daily = parse_config(raw_daily)
    for task_id, task in daily.tasks.items():
        kind = "daily_window" if task_id == "arena" else "interval"
        if task.schedule.kind != kind:
            raise ValueError(f"{task_id} 必须使用{kind}调度")
        if task.priority > PRIORITY_MAX:
            raise ValueError(f"{task_id}.priority 不得超过{PRIORITY_MAX}")
        for label, value in (("interval_seconds", task.schedule.interval_seconds), ("timeout_seconds", task.timeout_seconds), ("retry_seconds", task.retry_seconds)):
            _check_seconds(value, task_id + "." + label)
        for label in ("rescan_seconds", "claim_interval_seconds"):
            if label in task.params:
                _check_seconds(task.params[label], task_id + "." + label)
        if "energy_recover_seconds" in task.params:
            value = task.params["energy_recover_seconds"]
            if type(value) not in (int, float) or isinstance(value, bool) or not 1 <= float(value) <= 3600:
                raise ValueError("体力恢复间隔必须是1至3600秒的数值")
        if "minimum_tombs" in task.params and task.params["minimum_tombs"] > PRIORITY_MAX:
            raise ValueError("minimum_tombs 超出界面支持范围")
        if "trigger_ratio" in task.params:
            ratio = task.params["trigger_ratio"]
            if ratio < RATIO_MIN or abs(ratio - round(ratio, 3)) > 1e-12:
                raise ValueError("体力触发阈值只支持1%至100%，百分数最多一位小数")
    player = raw["player"]
    if not isinstance(player, dict) or set(player) != {"enabled"} or type(player["enabled"]) is not bool:
        raise ValueError("player配置只接受enabled布尔开关")
    ui = raw.get("ui", {"delay_ms": 500})
    if not isinstance(ui, dict) or set(ui) - {"delay_ms", "auto_open_game", "game_overlays"}:
        # auto_open_game 已废弃（不再自动打开游戏），老配置里遇到就忽略。
        raise ValueError("ui配置只接受delay_ms/game_overlays")
    ui=dict(ui)
    ui.pop("auto_open_game", None)
    # Existing configurations enter the no-custom-overlay diagnostic mode on first upgrade.
    ui.setdefault("game_overlays", False)
    if type(ui["game_overlays"]) is not bool:
        raise ValueError("game_overlays须为布尔开关")
    if type(ui.get("delay_ms")) is not int or not 0 <= ui["delay_ms"] <= 5000:
        raise ValueError("ui配置只接受0至5000毫秒的整数delay_ms")
    treasure = raw.get("treasure", {"enabled": False, "auto_dump": False, "overlay": False, "refresh_seconds": 30})
    if not isinstance(treasure, dict) or set(treasure) != {"enabled", "auto_dump", "overlay", "refresh_seconds"}:
        raise ValueError("treasure配置只接受 enabled/auto_dump/overlay/refresh_seconds")
    for flag in ("enabled", "auto_dump", "overlay"):
        if type(treasure[flag]) is not bool:
            raise ValueError(f"treasure.{flag} 必须是布尔开关")
    seconds = treasure["refresh_seconds"]
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise ValueError("摸金刷新间隔必须是1至3600秒的整数")
    damage = raw.get("damage", {"enabled": False, "auto_csv": True})
    if not isinstance(damage, dict) or set(damage) != {"enabled", "auto_csv"}:
        raise ValueError("damage配置只接受 enabled/auto_csv")
    for flag in ("enabled", "auto_csv"):
        if type(damage[flag]) is not bool:
            raise ValueError(f"damage.{flag} 必须是布尔开关")
    desire = _validate_desire(raw.get("desire"))
    bloodmoon = _validate_bloodmoon(raw.get("bloodmoon"))
    return {"version": 1, "daily": daily.raw, "player": dict(player), "ui": dict(ui),
            "treasure": dict(treasure), "damage": dict(damage), "desire": desire,
            "bloodmoon": bloodmoon, "battle_assist": validate_battle_assist(raw.get("battle_assist"))}


def _validate_desire(raw) -> dict:
    """三尸自动合成参数：品质档位 1..8，失败上限按品质单独配。"""
    default = default_config()["desire"]
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or set(raw) - set(default):
        raise ValueError("desire配置只接受 kind/start_quality/max_material_quality/fail_limits/max_attempts/expected_rate")
    merged = copy.deepcopy(default)
    merged.update(copy.deepcopy(raw))
    if type(merged["kind"]) is not int or merged["kind"] not in (1, 2, 3):
        raise ValueError("desire.kind 必须是1贪／2嗔／3痴")
    for label in ("start_quality", "max_material_quality"):
        value = merged[label]
        if type(value) is not int or not 1 <= value <= 8:
            raise ValueError(f"desire.{label} 必须是1至8的品质档位")
    if merged["start_quality"] > merged["max_material_quality"]:
        raise ValueError("desire.start_quality 不得高于 max_material_quality")
    limits = merged["fail_limits"]
    if not isinstance(limits, dict):
        raise ValueError("desire.fail_limits 必须是「品质: 连续失败上限」的映射")
    cleaned = {}
    for key, value in limits.items():
        quality = int(key)
        if quality < 1 or quality > 8:
            raise ValueError("desire.fail_limits 的品质键必须在1至8之间")
        if type(value) is not int or not 1 <= value <= 99:
            raise ValueError(f"desire.fail_limits[{quality}] 必须是1至99的整数")
        cleaned[str(quality)] = value
    merged["fail_limits"] = cleaned
    if type(merged["max_attempts"]) is not int or not 1 <= merged["max_attempts"] <= 5000:
        raise ValueError("desire.max_attempts 必须是1至5000的整数（单批次保险丝）")
    rate = merged["expected_rate"]
    if type(rate) not in (int, float) or isinstance(rate, bool) or not 0.1 <= float(rate) <= 100:
        raise ValueError("desire.expected_rate 必须是0.1至100的百分数")
    merged["expected_rate"] = float(rate)
    return merged


def _validate_bloodmoon(raw) -> dict:
    """血月战场参数：只收四个功能各自的开关与阈值，不接受任何运行态字段。"""
    default = default_config()["bloodmoon"]
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or set(raw) - set(default):
        raise ValueError("bloodmoon配置只接受 enabled/flag_probe/speed_up/attack/stealth_mark")
    merged = copy.deepcopy(default)
    for key, value in copy.deepcopy(raw).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    if type(merged["enabled"]) is not bool:
        raise ValueError("bloodmoon.enabled 必须是布尔开关")
    probe = merged["flag_probe"]
    if not isinstance(probe, dict) or set(probe) - {"refresh_seconds", "top_members"}:
        raise ValueError("bloodmoon.flag_probe 只接受 refresh_seconds/top_members")
    if type(probe["refresh_seconds"]) is not int or not 1 <= probe["refresh_seconds"] <= 3600:
        raise ValueError("战旗探测刷新间隔必须是1至3600秒的整数")
    if type(probe["top_members"]) is not int or not 1 <= probe["top_members"] <= 50:
        raise ValueError("每个阴司默认显示人数必须是1至50的整数")
    speed = merged["speed_up"]
    if not isinstance(speed, dict) or set(speed) - {"enabled", "max_times", "safety_margin_seconds", "poll_seconds"}:
        raise ValueError("bloodmoon.speed_up 只接受 enabled/max_times/safety_margin_seconds/poll_seconds")
    if type(speed["enabled"]) is not bool:
        raise ValueError("bloodmoon.speed_up.enabled 必须是布尔开关")
    for label, low, high in (("max_times", 0, 99), ("safety_margin_seconds", 0, 60), ("poll_seconds", 1, 60)):
        value = speed[label]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"bloodmoon.speed_up.{label} 必须是{low}至{high}的整数")
    attack = merged["attack"]
    if not isinstance(attack, dict) or set(attack) - {"enabled", "power_ratio", "power_limit", "max_battles", "wait_seconds"}:
        raise ValueError("bloodmoon.attack 只接受 enabled/power_ratio/power_limit/max_battles/wait_seconds")
    if type(attack["enabled"]) is not bool:
        raise ValueError("bloodmoon.attack.enabled 必须是布尔开关")
    if type(attack["power_ratio"]) is not int or not 10 <= attack["power_ratio"] <= 200:
        raise ValueError("自动攻击战力比例必须是10至200的整数百分数")
    if type(attack["power_limit"]) is not int or not 0 <= attack["power_limit"] <= BLOODMOON_POWER_MAX:
        raise ValueError("自动攻击战力上限必须是非负整数（0表示不限制）")
    if type(attack["max_battles"]) is not int or not 0 <= attack["max_battles"] <= 999:
        raise ValueError("自动攻击单轮最多场次必须是0至999的整数（0表示不限制）")
    if type(attack["wait_seconds"]) is not int or not 0 <= attack["wait_seconds"] <= 60:
        raise ValueError("自动攻击两场之间的等待必须是0至60秒的整数")
    mark = merged["stealth_mark"]
    if not isinstance(mark, dict) or set(mark) - {"enabled"} or type(mark["enabled"]) is not bool:
        raise ValueError("bloodmoon.stealth_mark 只接受 enabled 布尔开关")
    return merged


class PluginConfigStore(QObject):
    changed = Signal(dict)

    def __init__(self, path: Path | None = None, parent=None):
        super().__init__(parent)
        self.path = Path(path) if path is not None else default_config_path()
        if self.path.exists():
            with self.path.open(encoding="utf-8-sig") as file:
                self._config = validate_config(json.load(file, object_pairs_hook=_unique))
        else:
            self._config = validate_config(default_config())

    def snapshot(self) -> dict:
        return copy.deepcopy(self._config)

    def _commit(self, raw: dict) -> None:
        validated = validate_config(raw)
        if validated == self._config:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(validated, file, ensure_ascii=False, indent=2, allow_nan=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._config = validated
        self.changed.emit(self.snapshot())

    def set_daily_enabled(self, enabled: bool) -> None:
        raw = self.snapshot()
        raw["daily"]["enabled"] = enabled
        self._commit(raw)

    def set_player_enabled(self, enabled: bool) -> None:
        raw = self.snapshot()
        raw["player"]["enabled"] = enabled
        self._commit(raw)

    def set_game_overlays(self, enabled: bool) -> None:
        raw=self.snapshot()
        raw['ui']['game_overlays']=enabled
        self._commit(raw)

    def set_ui_delay(self, delay_ms: int) -> None:
        raw = self.snapshot()
        raw["ui"]["delay_ms"] = delay_ms
        self._commit(raw)


    def set_treasure(self, patch: dict) -> None:
        raw = self.snapshot()
        raw["treasure"].update(copy.deepcopy(patch))
        self._commit(raw)

    def set_damage(self, patch: dict) -> None:
        raw = self.snapshot()
        raw["damage"].update(copy.deepcopy(patch))
        self._commit(raw)

    def set_desire(self, patch: dict) -> None:
        raw = self.snapshot()
        raw["desire"].update(copy.deepcopy(patch))
        self._commit(raw)

    def set_battle_assist(self, config: dict) -> None:
        raw = self.snapshot()
        raw["battle_assist"] = copy.deepcopy(config)
        self._commit(raw)

    def set_bloodmoon(self, patch: dict) -> None:
        raw = self.snapshot()
        section = raw["bloodmoon"]
        # 子段是合并而不是整体替换：只改一个阈值时不能把同段的其它字段冲掉。
        for key, value in copy.deepcopy(patch).items():
            if isinstance(value, dict) and isinstance(section.get(key), dict):
                section[key].update(value)
            else:
                section[key] = value
        self._commit(raw)

    def set_all_tasks_enabled(self, enabled: bool) -> None:
        """全选／反选：统一设置九个任务开关；daily.enabled 只表示“是否有启用任务”。"""
        raw = self.snapshot()
        for task in raw["daily"]["tasks"].values():
            task["enabled"] = enabled
        raw["daily"]["enabled"] = enabled
        self._commit(raw)

    def set_task_enabled(self, task_id: str, enabled: bool) -> None:
        self.update_task(task_id, {"enabled": enabled})

    def update_task(self, task_id: str, patch: dict) -> None:
        raw = self.snapshot()
        if task_id not in raw["daily"]["tasks"]:
            raise ValueError(f"未知子任务：{task_id}")
        task = raw["daily"]["tasks"][task_id]
        for key, value in patch.items():
            if key in {"params", "schedule"} and isinstance(value, dict):
                task[key].update(copy.deepcopy(value))
            else:
                task[key] = copy.deepcopy(value)
        self._commit(raw)
