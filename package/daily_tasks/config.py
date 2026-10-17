"""独立日常JSON配置。错误配置拒绝执行，不使用GUI状态文件。"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import time
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tools" / "config" / "daily_tasks.json"


@dataclass(frozen=True)
class Schedule:
    kind: str
    interval_seconds: float
    start: time | None = None
    end: time | None = None


@dataclass(frozen=True)
class TaskConfig:
    task_id: str
    name: str
    enabled: bool
    priority: int
    timeout_seconds: float
    retry_seconds: float
    schedule: Schedule
    params: dict


@dataclass(frozen=True)
class DailyConfig:
    enabled: bool
    timezone: str
    poll_seconds: float
    summary_interval_seconds: float
    tasks: dict[str, TaskConfig]
    raw: dict


def _fields(value, allowed: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是对象")
    unknown = value.keys() - allowed
    if unknown:
        raise ValueError(f"{label} 未知字段：{', '.join(sorted(unknown))}")
    return value


def _number(value, label: str, *, positive=True) -> float:
    message = f"{label} 必须是有限{'正' if positive else ''}数"
    if type(value) not in (int, float):
        raise ValueError(message)
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(message) from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(message)
    return number


def _seconds(value, label: str) -> float:
    seconds = _number(value, label)
    if seconds < 0.001:
        raise ValueError(f"{label} 不得小于0.001秒")
    return seconds


def _boolean(value, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} 必须是 true/false")
    return value


def _clock(value, label: str) -> time:
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError(f"{label} 必须是 HH:MM")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} 无效时间") from exc


def normalize_player_ids(values) -> list[int]:
    if not isinstance(values, list):
        raise ValueError("excluded_player_ids 必须是列表")
    ids = []
    for value in values:
        if isinstance(value, str):
            value = value.strip().rsplit("#", 1)[-1]
            if not re.fullmatch(r"[0-9]+", value):
                raise ValueError("玩家ID必须是正整数或以#数字结尾的标识")
            value = int(value)
        if type(value) is not int or value <= 0:
            raise ValueError("玩家ID必须是正整数")
        if value not in ids:
            ids.append(value)
    return ids


def _params(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("params 必须是对象")
    # 允许未来任务自己的JSON字段，但拒绝非JSON对象和NaN/Infinity。
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("params 必须是有限JSON数据") from exc
    result = copy.deepcopy(value)
    if "excluded_player_ids" in result:
        result["excluded_player_ids"] = normalize_player_ids(result["excluded_player_ids"])
    if "trigger_ratio" in result:
        ratio = _number(result["trigger_ratio"], "trigger_ratio")
        if ratio > 1:
            raise ValueError("trigger_ratio 必须大于0且不超过1")
    for key in ("rescan_seconds", "claim_interval_seconds"):
        if key in result:
            _seconds(result[key], key)
    if "minimum_tombs" in result and (type(result["minimum_tombs"]) is not int or result["minimum_tombs"] <= 0):
        raise ValueError("minimum_tombs 必须是正整数")
    for key in ("recruit", "skip_failed_players", "restore_original", "continuous", "skip_battle"):
        if key in result:
            _boolean(result[key], key)
    return result


def parse_config(raw: dict) -> DailyConfig:
    data = copy.deepcopy(_fields(raw, {"version", "enabled", "timezone", "poll_seconds", "summary_interval_seconds", "tasks"}, "日常配置"))
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("version 必须是1")
    enabled = _boolean(data.get("enabled"), "enabled")
    if data.get("timezone") != "Asia/Shanghai":
        raise ValueError("任务调度 timezone 必须为 Asia/Shanghai；日志使用系统本地时间")
    poll = _seconds(data.get("poll_seconds"), "poll_seconds")
    summary = _seconds(data.get("summary_interval_seconds"), "summary_interval_seconds")
    task_data = data.get("tasks")
    if not isinstance(task_data, dict):
        raise ValueError("tasks 必须是按task_id索引的对象")
    tasks = {}
    for task_id, item in task_data.items():
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", task_id):
            raise ValueError("task_id 只能使用小写字母、数字和下划线，字母开头")
        _fields(item, {"name", "enabled", "priority", "timeout_seconds", "retry_seconds", "schedule", "params"}, task_id)
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError(f"{task_id}.name 必须是非空字符串")
        if type(item.get("priority")) is not int or item["priority"] < 0:
            raise ValueError(f"{task_id}.priority 必须是非负整数，数值小的优先")
        spec = _fields(item.get("schedule"), {"kind", "interval_seconds", "start", "end"}, f"{task_id}.schedule")
        kind = spec.get("kind")
        interval = _seconds(spec.get("interval_seconds"), f"{task_id}.interval_seconds")
        if kind == "interval":
            if "start" in spec or "end" in spec:
                raise ValueError("interval 不接受 start/end")
            schedule = Schedule(kind, interval)
        elif kind == "daily_window":
            start, end = _clock(spec.get("start"), "start"), _clock(spec.get("end"), "end")
            if start >= end:
                raise ValueError("每日窗口必须start<end，暂不支持跨午夜窗口")
            schedule = Schedule(kind, interval, start, end)
        else:
            raise ValueError("schedule.kind 只能是 interval/daily_window")
        params = _params(item.get("params"))
        if task_id == "energy":
            _fields(params, {"trigger_ratio", "spend_mode", "sanshi_plan_scope", "artifact_plan_scope", "formation_eye_name", "restore_original",
                             "energy_recover_seconds"}, "energy.params")
            if "energy_recover_seconds" in params:
                _number(params["energy_recover_seconds"], "energy.params.energy_recover_seconds")
            for key, expected in (("spend_mode", "all_available"), ("sanshi_plan_scope", "existing"), ("artifact_plan_scope", "existing")):
                if params.get(key, expected) != expected:
                    raise ValueError(f"energy.{key} 仅支持 {expected}")
            if params.get("restore_original", True) is not True:
                raise ValueError("energy 必须恢复原配置")
            name = params.get("formation_eye_name", "双子僵尸")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("formation_eye_name 必须是非空名称")
        item["params"] = params
        tasks[task_id] = TaskConfig(task_id, item["name"], _boolean(item.get("enabled"), f"{task_id}.enabled"),
                                    item["priority"], _seconds(item.get("timeout_seconds"), f"{task_id}.timeout_seconds"),
                                    _seconds(item.get("retry_seconds"), f"{task_id}.retry_seconds"), schedule, params)
    return DailyConfig(enabled, "Asia/Shanghai", poll, summary, tasks, data)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON重复字段：{key}")
        result[key] = value
    return result


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> DailyConfig:
    with Path(path).open(encoding="utf-8-sig") as file:
        return parse_config(json.load(file, object_pairs_hook=_unique_object))


def set_enabled(path: Path, enabled: bool, task_id: str | None = None) -> None:
    path = Path(path)
    _boolean(enabled, "enabled")
    data = load_config(path).raw
    if task_id is None:
        data["enabled"] = enabled
    else:
        if task_id not in data["tasks"]:
            raise ValueError(f"未知任务：{task_id}")
        data["tasks"][task_id]["enabled"] = enabled
    parse_config(data)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
