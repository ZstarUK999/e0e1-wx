"""到期时间计算机制的单元测试。"""
import importlib
import math

import pytest


def timing():
    try:
        return importlib.import_module("package.daily_tasks.timing")
    except ModuleNotFoundError:
        pytest.fail("定时计算机制尚未实现")


def test_clamp_delay_adds_buffer_and_bounds():
    m = timing()
    assert m.clamp_delay(0) == m.DEFAULT_BUFFER_SECONDS  # 已到期也延后一点
    assert m.clamp_delay(60) == 65.0
    assert m.clamp_delay(10 * 3600) == m.MAX_DELAY_SECONDS
    assert m.clamp_delay(-100) == m.MIN_DELAY_SECONDS


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "x", []])
def test_clamp_delay_rejects_non_finite(bad):
    m = timing()
    assert m.clamp_delay(bad) == m.MIN_DELAY_SECONDS


def test_delay_until_and_missing_values():
    m = timing()
    assert m.delay_until(1000, 400) == 600
    assert m.delay_until(400, 1000) == -600  # 已过期交给调用方判断
    assert m.delay_until(None, 400) is None
    assert m.delay_until(1000, None) is None


def test_seconds_until_energy_by_step():
    m = timing()
    assert m.seconds_until_energy(30, 90, 420) == 60 * 420
    assert m.seconds_until_energy(90, 90, 420) == 0.0
    assert m.seconds_until_energy(100, 90, 420) == 0.0
    assert m.seconds_until_energy(30, 90, 0) is None
    assert m.seconds_until_energy(None, 90, 420) is None


def test_seconds_until_energy_uses_last_recovery_when_available():
    m = timing()
    # 上次恢复在 100 秒前，还差 2 点，每点 420 秒 → 还要 740 秒。
    assert m.seconds_until_energy(30, 32, 420, last_recovery=1000, now=1100) == 740
    assert m.seconds_until_energy(30, 32, 420, last_recovery=None, now=1100) == 840


def test_seconds_until_cross_day_rolls_forward():
    m = timing()
    assert m.seconds_until_cross_day(0, 100) == m.DAY_SECONDS - 100
    # 已经过了"上次跨日"很久：应顺延到下一个跨日，而不是返回负数。
    assert m.seconds_until_cross_day(0, m.DAY_SECONDS * 3 + 10) == m.DAY_SECONDS - 10
    assert m.seconds_until_cross_day(None, 100) is None


def test_describe_readable():
    m = timing()
    assert m.describe(45) == "45秒"
    assert m.describe(90) == "1分钟"
    assert m.describe(3725) == "1小时2分"
    assert m.describe(None) == "未知"
    assert m.describe(float("nan")) == "未知"


def test_module_constants_are_sane():
    m = timing()
    assert 0 < m.MIN_DELAY_SECONDS <= m.MAX_DELAY_SECONDS <= m.SECONDS_MAX if hasattr(m, "SECONDS_MAX") else True
    assert math.isfinite(m.MAX_DELAY_SECONDS)
