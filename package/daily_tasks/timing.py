"""任务到期时间计算：只算"还要等多久"，不负责调度。

各任务提供到期时间（服务器时间戳，秒），这里统一换算成下一次检查的等待秒数。
拿不到可靠数据时返回 None，调用方退化为自己的轮询间隔，不改变既有安全语义。
"""
from __future__ import annotations

import math

# 一次"叫醒"的下限/上限：上限用来定期校准，避免长时间不重新读游戏数据。
MIN_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 3600.0
# 延后量：宁可晚一点，也不能来早了（墓还没到期就白跑一趟）。
DEFAULT_BUFFER_SECONDS = 5.0

DAY_SECONDS = 86400.0


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def clamp_delay(seconds, buffer: float = DEFAULT_BUFFER_SECONDS) -> float:
    """把秒数夹到合法区间并加上延后量；非法值一律按最小间隔处理。"""
    value = _finite(seconds)
    if value is None:
        return MIN_DELAY_SECONDS
    extra = _finite(buffer)
    value += DEFAULT_BUFFER_SECONDS if extra is None else max(extra, 0.0)
    if value < MIN_DELAY_SECONDS:
        return MIN_DELAY_SECONDS
    return min(value, MAX_DELAY_SECONDS)


def delay_until(deadline, now) -> float | None:
    """距离 deadline 还要等多久；deadline/now 不可用时返回 None。"""
    target = _finite(deadline)
    current = _finite(now)
    if target is None or current is None:
        return None
    return target - current


def seconds_until_energy(current, target, recover_seconds, last_recovery=None, now=None) -> float | None:
    """还要多久体力才能到 target。

    给了 last_recovery/now 时按"上次恢复时刻 + 间隔×缺几点"精算；
    否则退化为"缺几点 × 每点秒数"。
    """
    have = _finite(current)
    need = _finite(target)
    step = _finite(recover_seconds)
    if have is None or need is None or step is None or step <= 0:
        return None
    missing = need - have
    if missing <= 0:
        return 0.0
    last = _finite(last_recovery)
    current_time = _finite(now)
    if last is not None and current_time is not None:
        return (last + step * missing) - current_time
    return missing * step


def seconds_until_cross_day(cross_day_at, now) -> float | None:
    """距离下一次跨日还要多久；cross_day_at 是"上次跨日时刻"。"""
    last = _finite(cross_day_at)
    current = _finite(now)
    if last is None or current is None:
        return None
    next_cross = last + DAY_SECONDS
    while next_cross <= current:
        next_cross += DAY_SECONDS
    return next_cross - current


def describe(seconds) -> str:
    """把秒数写成易读的中文时长，用于日志。"""
    value = _finite(seconds)
    if value is None:
        return "未知"
    value = max(value, 0.0)
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    if hours:
        return f"{hours}小时{minutes}分"
    if minutes:
        return f"{minutes}分钟"
    return f"{int(value)}秒"
