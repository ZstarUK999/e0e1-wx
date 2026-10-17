"""构建期功能开关的测试：开关缺失/损坏时必须是全开，关掉的项要在三个入口都生效。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from package.plugin_manager import feature_flags as features  # noqa: E402
from package.plugin_manager import store  # noqa: E402


def _load_build_script():
    """按路径加载 tools/build_exe.py（文件名带连字符，不能直接 import）。"""
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "tools" / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def features_at(tmp_path, monkeypatch):
    """把开关文件指向临时目录；返回写入函数。"""

    def write(payload: str | dict) -> Path:
        path = tmp_path / "features.json"
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
        )
        return path

    monkeypatch.setattr(features, "features_path", lambda: tmp_path / "features.json")
    features.reset_cache()
    return write


def test_missing_file_means_all_enabled(features_at):
    assert features.task_enabled("arena")
    assert features.panel_enabled("debug")


def test_broken_file_means_all_enabled(features_at):
    features_at("{oops")
    assert features.task_enabled("arena")


def test_disabled_items(features_at):
    features_at({"tasks": {"arena": False}, "panels": {"debug": False}})
    assert not features.task_enabled("arena")
    assert features.task_enabled("energy")  # 没写到的仍然开启
    assert not features.panel_enabled("debug")
    assert features.panel_enabled("daily")


def test_default_config_drops_disabled_task(features_at):
    features_at({"tasks": {"arena": False}})
    config = store.default_config()
    assert "arena" not in config["daily"]["tasks"]
    assert "energy" in config["daily"]["tasks"]


def test_default_config_keeps_everything_when_no_file(features_at):
    assert set(store.default_config()["daily"]["tasks"]) >= {"arena", "energy", "sanshi_tombs"}


def _write_profile(directory: Path, payload: dict) -> Path:
    path = directory / "profile.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_profile_only_writes_disabled_entries(tmp_path, monkeypatch):
    build_exe = _load_build_script()
    monkeypatch.setattr(build_exe, "BUILD_DIR", tmp_path)
    target = build_exe.write_bundle_features({"tasks": {"arena": False, "energy": True}})
    assert target is not None
    assert json.loads(target.read_text(encoding="utf-8")) == {"tasks": {"arena": False}}


def test_profile_all_enabled_writes_nothing(tmp_path, monkeypatch):
    build_exe = _load_build_script()
    monkeypatch.setattr(build_exe, "BUILD_DIR", tmp_path)
    assert build_exe.write_bundle_features({"tasks": {"arena": True}}) is None


def test_profile_ignores_unknown_keys(tmp_path, monkeypatch):
    build_exe = _load_build_script()
    monkeypatch.setattr(build_exe, "BUILD_DIR", tmp_path)
    profile = build_exe.load_features_profile(
        _write_profile(tmp_path, {"tasks": {"不存在的任务": False, "arena": False}})
    )
    assert profile["tasks"] == {"arena": False}
