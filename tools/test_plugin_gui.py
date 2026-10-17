"""独立插件GUI测试；不运行微信、不连接CDP。"""
import copy
import importlib
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTime
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QCheckBox, QSpinBox


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def modules():
    try:
        return importlib.import_module("package.plugin_manager.store"), importlib.import_module("package.plugin_manager.window")
    except ModuleNotFoundError as exc:
        if exc.name.startswith("package.plugin_manager"):
            pytest.fail("独立插件GUI尚未实现")
        raise


@pytest.fixture
def window(app, tmp_path):
    s, w = modules()
    instance = w.PluginWindow(s.PluginConfigStore(tmp_path / "plugins.json"))
    yield instance
    instance.close()
    instance.deleteLater()
    app.processEvents()


def test_store_defaults_independent_and_only_configuration(app, tmp_path):
    s, _ = modules()
    store = s.PluginConfigStore(tmp_path / "plugins.json")
    state = store.snapshot()
    assert set(state) == {"version", "daily", "player", "ui", "treasure", "damage", "desire", "bloodmoon"}
    assert state["ui"]["delay_ms"] == 500
    assert state["treasure"] == {"enabled": False, "auto_dump": False, "overlay": False, "refresh_seconds": 30}
    assert state["damage"] == {"enabled": False, "auto_csv": True}
    assert not state["daily"]["enabled"]
    assert len(state["daily"]["tasks"]) == 9
    assert not any(t["enabled"] for t in state["daily"]["tasks"].values())
    assert not state["player"]["enabled"]
    assert not store.path.exists()
    store.set_task_enabled("energy", True)
    assert s.PluginConfigStore(store.path).snapshot() == store.snapshot()
    assert not store.snapshot()["daily"]["enabled"]


def test_new_gui_defaults_do_not_depend_on_editable_cli_configuration(app, tmp_path, monkeypatch):
    s, _ = modules()
    import package.daily_tasks.config as legacy
    missing = tmp_path / "missing-cli.json"
    monkeypatch.setattr(legacy, "DEFAULT_CONFIG_PATH", missing)
    if hasattr(s, "load_config"):
        def invalid_legacy(*args):
            raise ValueError("旧CLI配置损坏")
        monkeypatch.setattr(s, "load_config", invalid_legacy)
    store = s.PluginConfigStore(tmp_path / "plugins.json")
    assert len(store.snapshot()["daily"]["tasks"]) == 9
    assert store.snapshot()["daily"]["tasks"]["energy"]["params"]["trigger_ratio"] == 0.9
    assert not store.snapshot()["daily"]["enabled"]


def test_store_validation_precedes_save_and_emits_copies(app, tmp_path):
    s, _ = modules()
    store = s.PluginConfigStore(tmp_path / "plugins.json")
    changes = []
    store.changed.connect(changes.append)
    store.set_daily_enabled(True)
    changes[-1]["daily"]["enabled"] = False
    assert store.snapshot()["daily"]["enabled"]
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.update_task("energy", {"params": {"trigger_ratio": 1.2}})
    with pytest.raises(ValueError):
        store.set_task_enabled("missing", True)
    assert before == store.path.read_bytes()
    assert len(changes) == 1


def test_invalid_saved_config_is_not_overwritten(app, tmp_path):
    s, _ = modules()
    path = tmp_path / "plugins.json"
    path.write_text('{"version":1,"runtime_state":{}}', encoding="utf-8")
    with pytest.raises(ValueError):
        s.PluginConfigStore(path)
    assert "runtime_state" in path.read_text(encoding="utf-8")
    path.write_text('{"version":1,"version":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        s.PluginConfigStore(path)


def test_tree_navigation_and_truthful_unconnected_state(window):
    tree = window.tree
    assert [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())] == ["全局设置", "日常自动化", "血月战场", "玩家信息透视", "摸金地图", "PVP伤害分析", "三尸合成", "调试信息"]
    root = tree.topLevelItem(1)
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["体力扫荡", "阴墟墓葬", "定时斗法"]
    assert set(window.pages) == {"global", "daily", "energy", "mines", "arena", "bloodmoon", "player", "treasure", "damage", "desire", "debug"}
    assert "未接入" in window.connection_label.text()
    assert not window.game_connected
    # 血月页已接入：有开关，但游戏与插件未就绪时按钮一律不可用。
    bloodmoon = window.pages["bloodmoon"]
    assert bloodmoon.findChildren(QCheckBox)
    assert not bloodmoon.probe_start.isEnabled()
    assert not bloodmoon.diagnose_button.isEnabled()
    assert not hasattr(window, "bridge")
    tree.setCurrentItem(root.child(1))
    assert window.stack.currentWidget() is window.pages["mines"]


def test_root_only_switches_and_child_switch_sync(window):
    root = window.pages["daily"]
    assert len(root.findChildren(QCheckBox)) == 10
    assert not root.findChildren(QSpinBox)
    root.toggles["energy"].setChecked(True)
    child = window.task_panels["energy"]
    assert child.enabled.isChecked()
    assert window.store.snapshot()["daily"]["tasks"]["energy"]["enabled"]
    child.enabled.setChecked(False)
    assert not root.toggles["energy"].isChecked()
    # 总开关改语义：全选／反选全部任务，不再直接代表“自动运行”。
    assert root.run_button.text() == "开始日常自动化"
    root.master.setChecked(True)
    assert all(task["enabled"] for task in window.store.snapshot()["daily"]["tasks"].values())
    assert window.store.snapshot()["daily"]["enabled"]
    root.master.setChecked(False)
    assert not any(task["enabled"] for task in window.store.snapshot()["daily"]["tasks"].values())
    root.toggles["energy"].setChecked(True)
    assert not root.master.isChecked()


def test_automation_button_requests_start_and_stop(window):
    from PySide6.QtTest import QSignalSpy
    spy = QSignalSpy(window.automation_requested)
    daily = window.pages["daily"]
    window.set_connection(connected=True, target_appid=window.TARGET_APPID, runtime_ready=True)
    assert daily.run_button.isEnabled()
    daily.set_automation_running(True)
    assert daily.run_button.text() == "停止日常自动化"
    daily.run_button.click()
    assert spy.at(0) == [False]
    daily.set_automation_running(False)
    daily.run_button.click()
    assert spy.at(1) == [True]


def test_global_settings_edits_ui_delay(window):
    global_panel = window.pages["global"]
    assert global_panel.delay.value() == 500
    global_panel.delay.setValue(800)
    global_panel.save_button.click()
    assert window.store.snapshot()["ui"]["delay_ms"] == 800
    assert "已保存" in global_panel.message.text()


def test_ui_delay_rejects_out_of_range_and_non_integers(app, tmp_path):
    s, _ = modules()
    store = s.PluginConfigStore(tmp_path / "plugins.json")
    store.set_ui_delay(0)
    assert store.snapshot()["ui"]["delay_ms"] == 0
    for bad in (-1, 5001, 1.5, True, "500"):
        raw = store.snapshot()
        raw["ui"]["delay_ms"] = bad
        try:
            s.validate_config(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法延时未被拒绝：{bad}")
    assert store.snapshot()["ui"]["delay_ms"] == 0


def test_pending_parameter_edits_survive_live_switch_save(window):
    panel = window.task_panels["energy"]
    spy = QSignalSpy(window.configuration_changed)
    panel.fields["params.trigger_ratio"].setValue(85)
    panel.fields["schedule.interval_seconds"].setValue(45)
    assert spy.count() == 0
    assert window.store.snapshot()["daily"]["tasks"]["energy"]["params"]["trigger_ratio"] == 0.9
    panel.enabled.setChecked(True)
    assert spy.count() == 1
    assert panel.fields["params.trigger_ratio"].value() == 85
    panel.save_button.click()
    saved = window.store.snapshot()["daily"]["tasks"]["energy"]
    assert saved["params"]["trigger_ratio"] == 0.85
    assert saved["schedule"]["interval_seconds"] == 45
    assert saved["params"]["restore_original"]
    assert spy.count() == 2
    reward = window.task_panels["offline_reward"]
    reward.fields["params.claim_interval_seconds"].setValue(7200)
    reward.save_button.click()
    assert window.store.snapshot()["daily"]["tasks"]["offline_reward"]["params"]["claim_interval_seconds"] == 7200


def test_mine_groups_and_arena_validation(window):
    raid = window.task_panels["sanshi_raid"]
    raid.fields["params.minimum_tombs"].setValue(18)
    raid.save_button.click()
    saved = window.store.snapshot()["daily"]["tasks"]
    assert saved["sanshi_raid"]["params"]["minimum_tombs"] == 18
    # 改三尸不影响法器，法器默认是自己的门槛10。
    assert saved["artifact_raid"]["params"]["minimum_tombs"] == 10
    assert "params.minimum_tombs" not in window.task_panels["sanshi_fill"].fields
    assert "params.recruit" in window.task_panels["sanshi_tombs"].fields
    arena = window.task_panels["arena"]
    arena.fields["params.excluded_player_ids"].setPlainText("安卓|天书通悟561服#12402987\n456\n12402987")
    arena.save_button.click()
    assert window.store.snapshot()["daily"]["tasks"]["arena"]["params"]["excluded_player_ids"] == [12402987, 456]
    before = window.store.path.read_bytes()
    arena.fields["schedule.start"].setTime(QTime(11, 0))
    arena.save_button.click()
    assert before == window.store.path.read_bytes()
    assert "失败" in arena.message.text()


def test_manual_test_requires_real_connection_confirmation_and_not_busy(window):
    spy = QSignalSpy(window.test_requested)
    assert window.test_actions_for("energy")["energy"].text() == "测试执行"
    assert not window.test_actions_for("energy")["energy"].isEnabled()
    assert set(window.test_actions_for("mines")) == {"sanshi_tombs", "artifact_tombs", "sanshi_raid", "artifact_raid", "sanshi_fill", "artifact_fill"}
    window.request_test("energy", confirmed=True)
    assert spy.count() == 0
    window.set_connection(connected=True, target_appid="wrong", runtime_ready=True)
    assert not window.game_connected
    window.set_connection(connected=True, target_appid=window.TARGET_APPID, runtime_ready=False)
    assert not window.test_actions_for("energy")["energy"].isEnabled()
    window.set_connection(connected=True, target_appid=window.TARGET_APPID, runtime_ready=True)
    window.request_test("energy", confirmed=False)
    assert spy.count() == 0
    window.request_test("energy", confirmed=True)
    assert spy.count() == 1
    assert spy.at(0) == ["energy", {"force_trigger": True}]
    assert not window.test_actions_for("energy")["energy"].isEnabled()
    window.finish_test("energy", "测试回执：完成")
    assert window.test_actions_for("energy")["energy"].isEnabled()
    assert "完成" in window.action_label.text()


def test_debug_link_not_opened_until_click(window):
    calls = []
    window.chrome_opener = lambda link: calls.append(link) or True
    debug = window.pages["debug"]
    assert not debug.open_button.isEnabled()
    link = "devtools://devtools/bundled/inspector.html?ws=127.0.0.1:62000"
    window.set_debug_link(link)
    assert debug.link.text() == link
    assert not calls
    debug.open_button.click()
    assert calls == [link]
    for invalid in ("https://untrusted.example/", "file:///c:/secret", "devtools://devtools/bundled/inspector.html?ws=evil.example:62000"):
        window.set_debug_link(invalid)
        assert not debug.open_button.isEnabled()
    assert calls == [link]


def test_reset_current_session_not_configuration(window):
    window.store.set_task_enabled("energy", True)
    window.set_player_information("当前玩家公开信息", "玩家A")
    window.set_debug_link("devtools://devtools/bundled/inspector.html?ws=127.0.0.1:62000")
    saved = window.store.path.read_bytes()
    window.set_connection(connected=True, target_appid=window.TARGET_APPID, runtime_ready=True)
    window.reset_session()
    assert not window.game_connected
    assert window.pages["player"].text.toPlainText() == ""
    assert window.pages["debug"].link.text() == ""
    assert saved == window.store.path.read_bytes()
    assert window.store.snapshot()["daily"]["tasks"]["energy"]["enabled"]


def test_single_instance_lock_blocks_second_until_released(app, tmp_path):
    guard = importlib.import_module("package.runtime.instance_guard")
    first = guard.InstanceGuard(tmp_path / "plugin.lock")
    second = guard.InstanceGuard(tmp_path / "plugin.lock")
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_single_instance_is_exclusive_across_processes(app, tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    from package.runtime.instance_guard import InstanceGuard
    lock_path = tmp_path / "plugin.lock"
    guard = InstanceGuard(lock_path)
    assert guard.acquire()
    code = "import sys; from pathlib import Path; from package.runtime.instance_guard import InstanceGuard; guard=InstanceGuard(Path(sys.argv[1])); acquired=guard.acquire(); print(int(acquired)); guard.release()"
    try:
        process = subprocess.run([sys.executable, "-c", code, str(lock_path)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
        assert process.returncode == 0, process.stderr
        assert process.stdout.strip() == "0"
    finally:
        guard.release()


def test_close_emits_shutdown_without_saving_session(window):
    spy = QSignalSpy(window.shutdown_requested)
    window.set_player_information("临时展示", "自己")
    window.close()
    assert spy.count() == 1
    assert not window.store.path.exists()


@pytest.mark.parametrize("change", ["disconnect", "runtime", "busy", "close"])
def test_confirmation_rechecks_runtime_state_before_dispatch(window, monkeypatch, change):
    from PySide6.QtWidgets import QMessageBox
    spy = QSignalSpy(window.test_requested)
    window.set_connection(connected=True, target_appid=window.TARGET_APPID, runtime_ready=True)
    def answer(*args):
        if change == "disconnect":
            window.set_connection(connected=False)
        elif change == "runtime":
            window.set_connection(connected=True, target_appid=window.TARGET_APPID, runtime_ready=False)
        elif change == "busy":
            window._busy_task = "arena"
        else:
            window._closing = True
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", answer)
    window.request_test("energy")
    assert spy.count() == 0
    window._busy_task = None


def test_store_rejects_wrong_schedule_kinds_before_window_creation(app, tmp_path):
    s, _ = modules()
    for task_id in ("arena", "energy"):
        raw = s.default_config()
        task = raw["daily"]["tasks"][task_id]
        task["schedule"] = {"kind": "interval", "interval_seconds": 1} if task_id == "arena" else {"kind": "daily_window", "start": "10:28", "end": "10:30", "interval_seconds": 1}
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        before = path.read_bytes()
        with pytest.raises(ValueError):
            s.PluginConfigStore(path)
        assert path.read_bytes() == before


def test_store_rejects_values_that_gui_would_silently_clamp(app, tmp_path):
    s, _ = modules()
    patches = [
        {"params": {"trigger_ratio": 0.001}}, {"params": {"trigger_ratio": 0.85555}},
        {"schedule": {"interval_seconds": 700000}}, {"schedule": {"interval_seconds": 60.0001}}, {"priority": 1000001},
    ]
    store = s.PluginConfigStore(tmp_path / "plugins.json")
    for patch in patches:
        with pytest.raises(ValueError):
            store.update_task("energy", patch)
    assert not store.path.exists()


def test_supported_numeric_boundaries_roundtrip_without_parameter_changes(app, tmp_path):
    s, w = modules()
    store = s.PluginConfigStore(tmp_path / "plugins.json")
    store.update_task("energy", {"params": {"trigger_ratio": 0.01}, "priority": 1000000, "schedule": {"interval_seconds": 604800}})
    before = store.snapshot()
    window = w.PluginWindow(store)
    try:
        window.task_panels["energy"].save_button.click()
        assert store.snapshot() == before
    finally:
        window.close()


def test_busy_close_waits_for_completion_and_emits_once(window):
    window.set_connection(connected=True, target_appid=window.TARGET_APPID, runtime_ready=True)
    window.request_test("energy", confirmed=True)
    spy = QSignalSpy(window.shutdown_requested)
    assert not window.close()
    assert spy.count() == 1
    assert window._busy_task == "energy"
    window.finish_test("energy", "已完成收尾")
    assert window._busy_task is None
    assert not window.game_connected
    assert spy.count() == 1


def test_save_failure_reverts_live_checkbox_without_discarding_draft(window, monkeypatch):
    s, _ = modules()
    panel = window.task_panels["energy"]
    panel.fields["params.trigger_ratio"].setValue(85)
    def fail(*args):
        raise OSError("磁盘无法写入")
    monkeypatch.setattr(s.os, "replace", fail)
    panel.enabled.setChecked(True)
    assert not panel.enabled.isChecked()
    assert not window.pages["daily"].toggles["energy"].isChecked()
    assert panel.fields["params.trigger_ratio"].value() == 85
    assert not window.store.path.exists()
    assert "保存失败" in panel.message.text()


def test_real_qasync_entry_opens_and_closes_offscreen_without_backend(app, tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    code = '''
import json, sys
from pathlib import Path
from PySide6.QtCore import QTimer
import package.plugin_manager.store as store
import package.plugin_manager.window as ui
import package.plugin_manager.runtime as runtime
import plugin_main
from tools.test_plugin_runtime import FakeService, FakeTransport
OriginalRuntime=runtime.PluginRuntime
class FakeRuntime(OriginalRuntime):
    def __init__(self, window):
        super().__init__(window, service=FakeService(), transport=FakeTransport(), process_ready=lambda:False)
runtime.PluginRuntime=FakeRuntime
path = Path(sys.argv[1])
Original = ui.PluginWindow
class AutoCloseWindow(Original):
    def __init__(self, config):
        super().__init__(config)
        QTimer.singleShot(0, self.close)
ui.PluginWindow = AutoCloseWindow
result = plugin_main.main(path)
import logging
assert logging.getLogger('plugin_manager').isEnabledFor(logging.INFO), '每小时INFO日志未启用'
print(json.dumps({"exit":result,"config_written":path.exists(),"lock_left":path.with_name("plugin-manager.lock").exists()}))
'''
    process = subprocess.run([sys.executable, "-c", code, str(tmp_path / "plugins.json")], cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {"exit": 0, "config_written": False, "lock_left": False}


def test_entry_ctrl_c_uses_window_close_instead_of_forced_app_quit(app, tmp_path):
    import subprocess, sys
    from pathlib import Path
    code = '''
import sys, signal, json
from pathlib import Path
from PySide6.QtCore import QTimer
import package.plugin_manager.store as store
import package.plugin_manager.window as ui
import package.plugin_manager.runtime as runtime
import plugin_main
closed=[]
Original=ui.PluginWindow
class Window(Original):
    def __init__(self, config):
        super().__init__(config)
        QTimer.singleShot(0, lambda:signal.raise_signal(signal.SIGINT))
    def closeEvent(self,event):
        closed.append(True)
        super().closeEvent(event)
class FakeRuntime:
    def __init__(self,window):pass
    def start(self):pass
ui.PluginWindow=Window
runtime.PluginRuntime=FakeRuntime
result=plugin_main.main(Path(sys.argv[1]))
print(json.dumps({"exit":result,"closed":len(closed)}))
'''
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path/'plugins.json')],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'exit':0,'closed':1}


def test_task_buttons_replace_context_menus_and_advanced_fields_start_collapsed(window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    spy = QSignalSpy(window.test_requested)
    for panel in window.task_panels.values():
        assert panel.test_button.text() == '测试执行'
        assert not panel.test_button.isEnabled()
        assert panel.advanced.isHidden()
        assert not panel.advanced_toggle.isChecked()
        assert panel.advanced_toggle.arrowType() == Qt.ArrowType.RightArrow
        assert '#888' in panel.advanced_toggle.styleSheet()
        for name in ('schedule.interval_seconds', 'timeout_seconds', 'retry_seconds', 'priority'):
            assert panel.advanced.isAncestorOf(panel.fields[name])
        assert panel.contextMenuPolicy() != Qt.ContextMenuPolicy.CustomContextMenu
    assert window.tree.contextMenuPolicy() != Qt.ContextMenuPolicy.CustomContextMenu
    energy = window.task_panels['energy']
    assert not energy.advanced.isAncestorOf(energy.fields['params.trigger_ratio'])
    energy.advanced_toggle.click()
    assert not energy.advanced.isHidden()
    energy.advanced_toggle.click()
    assert energy.advanced.isHidden()
    window.attach_runtime({'energy'})
    window.set_connection(connected=True, target_appid=window.TARGET_APPID, runtime_ready=True)
    assert energy.test_button.isEnabled()
    assert not window.task_panels['arena'].test_button.isEnabled()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    energy.test_button.click()
    assert spy.count() == 1
    assert not energy.test_button.isEnabled()
    window.finish_test('energy', '完成')
    assert energy.test_button.isEnabled()


def test_launch_entry_does_not_import_old_main_window(app):
    modules()
    import inspect

    import package.plugin_manager.app as application
    entry = importlib.import_module("plugin_main")
    assert callable(entry.main)
    # 入口是薄壳：装配在 plugin_manager.app 里，且不拉起旧主窗口。
    assert "package.plugin_manager.app" in inspect.getsource(entry)
    assert "MainWindow" not in inspect.getsource(entry)
    assembly = inspect.getsource(application.PluginApplication._create_window)
    assert "window_module.PluginWindow" in assembly
    assert "MainWindow" not in assembly
