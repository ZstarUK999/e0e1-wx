"""独立插件管理窗口。内部运行服务由入口接入，不主动打开微信或游戏。"""

from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
import time

from PySide6.QtCore import Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QGridLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QHBoxLayout, QScrollArea, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from package.ui.offset_dialog import OffsetDialogController
from .build_info import current as build_info
from .debug_link import open_chrome, valid_debug_link
from .gate import PHASE_INIT, StartupGate
from .feature_flags import panel_enabled, task_enabled
from .panels import BloodmoonPanel, DailyPanel, DamagePanel, DebugPanel, DesirePanel, GlobalPanel, PlayerPanel, TaskPanel, TreasurePanel
from .store import PluginConfigStore
from .battle_assist import create_battle_assist_panel, create_zhongkui_panel

PAGE_TASKS = {
    "energy": ("energy", "offline_reward"),
    "mines": ("sanshi_tombs", "artifact_tombs", "sanshi_raid", "artifact_raid", "sanshi_fill", "artifact_fill"),
    "arena": ("arena",),
}


def visible_tasks(page_key: str) -> tuple[str, ...]:
    """任务页里按构建期开关剩下的任务。"""
    return tuple(task_id for task_id in PAGE_TASKS.get(page_key, ()) if task_enabled(task_id))


class _ShutdownDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        self.setWindowTitle("正在退出")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("正在结束定时任务，请稍候…", self))
        self.countdown = QLabel(self)
        layout.addWidget(self.countdown)
        progress = QProgressBar(self)
        progress.setRange(0, 0)
        layout.addWidget(progress)

    def reject(self):
        # 关闭请求已经生效，Escape 不应把收尾提示藏起来。
        pass


class PluginWindow(QMainWindow):
    TARGET_APPID = "wx6d5e82c174635a48"
    configuration_changed = Signal(dict)
    test_requested = Signal(str, dict)
    automation_requested = Signal(bool)
    treasure_requested = Signal(str, dict)
    damage_requested = Signal(str, dict)
    desire_requested = Signal(str, dict)
    bloodmoon_requested = Signal(str, dict)
    shutdown_requested = Signal()

    def __init__(self, store: PluginConfigStore | None = None):
        super().__init__()
        self.store = store or PluginConfigStore(parent=self)
        self.game_connected = False
        self.runtime_ready = False
        self._busy_task = None
        self._closing = False
        self._shutdown_emitted = False
        self._runtime_attached = False
        self._shutdown_complete = False
        self._shutdown_dialog = None
        self._shutdown_started = None
        self._shutdown_estimate_seconds = 30.0
        self._shutdown_delay_timer = QTimer(self)
        self._shutdown_delay_timer.setSingleShot(True)
        self._shutdown_delay_timer.setInterval(200)
        self._shutdown_delay_timer.timeout.connect(self._show_shutdown_progress)
        self._shutdown_progress_timer = QTimer(self)
        self._shutdown_progress_timer.setInterval(200)
        self._shutdown_progress_timer.timeout.connect(self._update_shutdown_progress)
        self._operation_running = False
        self._capabilities = None
        self._offset_dialog = None
        self.chrome_opener = open_chrome
        info = build_info()
        self.version_text = f'v{info.version} · {"发行版" if info.is_release else "调试版"}'
        self.setWindowTitle(f'遗弃之地 · 插件管理器 · {self.version_text}')
        self.resize(1080, 780)
        self.setMinimumSize(820, 560)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(170)
        self.stack = QStackedWidget()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([210, 870])
        # 调试链路与账号校验就绪前只显示门禁占位面板，不把整套功能面板铺开。
        self.gate = StartupGate()
        self.gate.set_phase(PHASE_INIT, "正在建立调试链路")
        self._splitter = splitter
        self._root = QStackedWidget()
        self._root.addWidget(self.gate)
        self._root.addWidget(splitter)
        self.setCentralWidget(self._root)
        self._main_shown = False
        self.pages, self.task_panels, self.items = {}, {}, {}
        self._test_actions = {}
        self._add_page("global", GlobalPanel(self.store))
        self._add_page("daily", DailyPanel(self.store))
        for key, title in (("energy", "体力扫荡与挂机收益"), ("mines", "阴墟墓葬"), ("arena", "定时斗法")):
            if not panel_enabled(key) or not visible_tasks(key):
                continue
            self._add_page(key, self._task_page(key, title))
        self._add_page("battle_assist", create_battle_assist_panel(self.store))
        self._add_page("control_chain", create_battle_assist_panel(self.store))
        self._add_page("zhongkui", create_zhongkui_panel(self.store))
        self._add_page("bloodmoon", BloodmoonPanel(self.store))
        self._add_page("player", PlayerPanel(self.store))
        self._add_page("treasure", TreasurePanel(self.store))
        self._add_page("damage", DamagePanel(self.store))
        self._add_page("desire", DesirePanel(self.store))
        self._add_page("debug", DebugPanel())
        for key, title in (("global", "全局设置"), ("daily", "日常自动化"), ("battle_assist", "PVE辅助"), ("bloodmoon", "血月战场"), ("player", "玩家信息透视"), ("treasure", "摸金地图"), ("damage", "PVP伤害分析"), ("desire", "三尸合成"), ("debug", "调试信息")):
            if not panel_enabled(key):
                continue
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.tree.addTopLevelItem(item)
            self.items[key] = item
        assist_item = self.items.get("battle_assist")
        if assist_item is not None:
            item = QTreeWidgetItem(assist_item, ["控制链"])
            item.setData(0, Qt.ItemDataRole.UserRole, "control_chain")
            self.items["control_chain"] = item
            zhongkui_item = QTreeWidgetItem(assist_item, ["钟馗伏魔"])
            zhongkui_item.setData(0, Qt.ItemDataRole.UserRole, "zhongkui")
            self.items["zhongkui"] = zhongkui_item
            assist_item.setExpanded(True)
        daily_item = self.items.get("daily")
        for key, title in (("energy", "体力扫荡"), ("mines", "阴墟墓葬"), ("arena", "定时斗法")):
            if daily_item is None or not panel_enabled(key) or not visible_tasks(key):
                continue
            item = QTreeWidgetItem(daily_item, [title])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.items[key] = item
        if daily_item is not None:
            daily_item.setExpanded(True)
        self.tree.currentItemChanged.connect(self._select_page)
        if daily_item is not None:
            self.tree.setCurrentItem(daily_item)
        self.action_label = QLabel("配置面板就绪；运行服务尚未接入")
        self.connection_label = QLabel("未连接 · 运行服务未接入")
        self.bound_id_label = QLabel("绑定ID：未读取")
        self.statusBar().addWidget(self.action_label, 1)
        self.version_label = QLabel(self.version_text)
        self.statusBar().addPermanentWidget(self.version_label)
        self.statusBar().addPermanentWidget(self.bound_id_label)
        self.statusBar().addPermanentWidget(self.connection_label)
        # 门禁阶段状态栏也一起收起来，占位面板才是真的"空白"。
        self.statusBar().setVisible(False)
        self.store.changed.connect(self.configuration_changed.emit)
        self.pages["daily"].automation_requested.connect(self.automation_requested.emit)
        treasure = self.pages["treasure"]
        treasure.dump_requested.connect(lambda: self.treasure_requested.emit("dump", {}))
        treasure.overlay_requested.connect(lambda on: self.treasure_requested.emit("overlay", {"on": on}))
        treasure.status_requested.connect(lambda: self.treasure_requested.emit("status", {}))
        damage = self.pages["damage"]
        damage.refresh_requested.connect(lambda: self.damage_requested.emit("refresh", {}))
        damage.reset_requested.connect(lambda: self.damage_requested.emit("reset", {}))
        damage.debug_requested.connect(lambda: self.damage_requested.emit("debug", {}))
        damage.perf_requested.connect(lambda: self.damage_requested.emit("perf", {}))
        damage.open_report_requested.connect(self._open_damage_report)
        desire = self.pages["desire"]
        desire.start_requested.connect(lambda: self.desire_requested.emit("start", {}))
        desire.stop_requested.connect(lambda: self.desire_requested.emit("stop", {}))
        desire.report_requested.connect(lambda: self.desire_requested.emit("report", {}))
        desire.probe_requested.connect(lambda: self.desire_requested.emit("probe", {}))
        desire.open_report_requested.connect(self._open_desire_report)
        bloodmoon = self.pages["bloodmoon"]
        bloodmoon.probe_requested.connect(lambda on: self.bloodmoon_requested.emit("probe", {"on": on}))
        bloodmoon.diagnose_requested.connect(lambda: self.bloodmoon_requested.emit("diagnose", {}))
        bloodmoon.reset_requested.connect(lambda: self.bloodmoon_requested.emit("reset", {}))
        self._automation_ready = False
        debug = self.pages["debug"]
        debug.open_requested.connect(self._open_debug)
        player = self.pages["player"]
        player.copy_button.clicked.connect(self._copy_information)
        player.export_button.clicked.connect(self._export_information)

    def select_platform(self, callback):
        """Choose the host before constructing any debug service or patching files."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        title = QLabel('选择游戏平台')
        title.setObjectName('panelTitle')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        note = QLabel('请选择《遗弃之地》当前运行的平台')
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addStretch()
        buttons = []
        def choose(platform):
            for button in buttons:
                button.setEnabled(False)
            self._root.setCurrentWidget(self.gate)
            callback(platform)
        for platform, label in (('wechat', '微信小游戏'), ('douyin', '抖音 PC 小游戏')):
            button = QPushButton(label)
            button.setMinimumSize(180, 52)
            button.clicked.connect(lambda checked=False, key=platform: choose(key))
            row.addWidget(button)
            buttons.append(button)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        self.platform_buttons = dict(zip(('wechat', 'douyin'), buttons))
        self._root.addWidget(page)
        self._root.setCurrentWidget(page)

    def _add_page(self, key, widget):
        self.pages[key] = widget
        self.stack.addWidget(widget)

    def _task_page(self, key, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        note = QLabel("开关立即保存；数值参数点击保存。任务末尾可测试执行，需游戏与插件就绪并确认消耗。")
        note.setWordWrap(True)
        layout.addWidget(note)
        grid = QGridLayout()
        layout.addLayout(grid)
        for index, task_id in enumerate(visible_tasks(key)):
            panel = TaskPanel(self.store, task_id)
            self.task_panels[task_id] = panel
            if key == "mines":
                # 左列三尸，右列法器；每类收取重开、盗掠、填土各自独立。
                grid.addWidget(panel, index // 2, index % 2)
            else:
                grid.addWidget(panel, index, 0)
            action = QAction("测试执行", self)
            action.setEnabled(False)
            action.triggered.connect(lambda checked=False, task=task_id: self.request_test(task))
            self._test_actions[task_id] = action
            panel.test_button.clicked.connect(action.trigger)
        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _select_page(self, item, previous):
        if item is not None:
            self.stack.setCurrentWidget(self.pages[item.data(0, Qt.ItemDataRole.UserRole)])

    def set_gate(self, phase: str, detail: str = "") -> None:
        """退回门禁占位面板；已经进过主 UI 的先把主 UI 收回去。

        由 PluginRuntime 按真实连接进度调用：链路未就绪 → init，链路就绪等游戏 →
        wait_game，游戏已接入挂载脚本 → mounting，账号授权对不上 → denied
        （带读到的ID，不做任何伪装）。
        """
        # 调试版进入功能面板后，断连和重新挂载只更新状态，不收回面板。
        if not build_info().is_release and self._main_shown:
            return
        self.gate.set_phase(phase, detail)
        if self._main_shown:
            self._main_shown = False
            self.statusBar().setVisible(False)
        if self._root.currentWidget() is not self.gate:
            self._root.setCurrentWidget(self.gate)

    def show_main_ui(self) -> None:
        """连接与账号校验都通过后，切到真正的面板；重复调用无副作用。"""
        if self._main_shown:
            return
        self._main_shown = True
        self.gate.spinner.stop()
        self.statusBar().setVisible(True)
        self._root.setCurrentWidget(self._splitter)

    @property
    def main_ui_shown(self) -> bool:
        return self._main_shown

    def attach_runtime(self, capabilities):
        self._runtime_attached = True
        self._capabilities = set(capabilities)
        self._update_test_actions()

    def set_operation_running(self, running):
        self._operation_running = bool(running)
        self._update_test_actions()

    def complete_shutdown(self):
        self._shutdown_complete = True
        self._hide_shutdown_progress()
        self.close()

    def _hide_shutdown_progress(self):
        self._shutdown_delay_timer.stop()
        self._shutdown_progress_timer.stop()
        if self._shutdown_dialog is not None:
            self._shutdown_dialog.done(QDialog.DialogCode.Accepted)

    def set_shutdown_estimate(self, seconds):
        self._shutdown_estimate_seconds = max(1.0, float(seconds))

    def _show_shutdown_progress(self):
        if not self._closing or self._shutdown_complete:
            return
        if self._shutdown_dialog is None:
            self._shutdown_dialog = _ShutdownDialog(self)
        self._update_shutdown_progress()
        self._shutdown_dialog.show()
        self._shutdown_progress_timer.start()

    def _update_shutdown_progress(self):
        if self._shutdown_dialog is None or self._shutdown_started is None:
            return
        elapsed = max(0.0, time.monotonic() - self._shutdown_started)
        remaining = max(0, math.ceil(self._shutdown_estimate_seconds - elapsed))
        if remaining:
            text = f"预计 {remaining} 秒后退出；任务提前结束将立即退出。"
        else:
            text = f"仍在等待当前操作确认（已等待 {int(elapsed)} 秒），完成后自动退出。"
        self._shutdown_dialog.countdown.setText(text)

    def set_automation_running(self, running: bool):
        self.pages["daily"].set_automation_running(running)

    def _open_damage_report(self):
        """用系统默认浏览器打开本地 HTML 报告。"""
        panel = self.pages["damage"]
        path = panel._report_path
        if not path or not Path(path).exists():
            panel.message.setText("还没有生成报告，先打一场 PVP 或点「立即取一次」")
            return
        url = QUrl.fromLocalFile(str(Path(path).resolve()))
        if not QDesktopServices.openUrl(url):
            panel.message.setText(f"打开失败，请手动打开：{path}")

    def _open_desire_report(self):
        """用系统默认浏览器打开三尸合成报告。"""
        panel = self.pages["desire"]
        path = panel._report_path
        if not path or not Path(path).exists():
            panel.message.setText("还没有生成报告，先跑一批合成或点「生成并打开报告」")
            return
        url = QUrl.fromLocalFile(str(Path(path).resolve()))
        if not QDesktopServices.openUrl(url):
            panel.message.setText(f"打开失败，请手动打开：{path}")

    def set_automation_ready(self, ready: bool):
        self._automation_ready = bool(ready)
        self.pages["daily"].set_automation_ready(ready)

    def _update_test_actions(self):
        available = self.game_connected and self.runtime_ready and self._busy_task is None and not self._closing and not self._operation_running
        for task_id, action in self._test_actions.items():
            supported = self._capabilities is None or task_id in self._capabilities
            enabled = available and supported
            if action.isEnabled() != enabled:
                action.setEnabled(enabled)
            button = self.task_panels[task_id].test_button
            if button.isEnabled() != enabled:
                button.setEnabled(enabled)
            tooltip = ('此任务业务尚未接入' if not supported else
                       '正在退出插件' if self._closing else
                       '游戏或插件尚未就绪，请查看底部连接状态' if not (self.game_connected and self.runtime_ready) else
                       '当前已有操作执行中，请等待收尾' if not available else '')
            if action.toolTip() != tooltip:
                action.setToolTip(tooltip)
                button.setToolTip(tooltip)

    def test_actions_for(self, page_key):
        self._update_test_actions()
        return {task_id: self._test_actions[task_id] for task_id in visible_tasks(page_key)}

    def request_test(self, task_id: str, *, confirmed: bool | None = None):
        self._update_test_actions()
        action = self._test_actions.get(task_id)
        if action is None or not action.isEnabled():
            self.action_label.setText("无法测试：游戏或插件未就绪，或已有操作正在进行")
            return
        if confirmed is None:
            name = self.store.snapshot()["daily"]["tasks"][task_id]["name"]
            choice = QMessageBox.question(self, "确认测试执行", f"立即测试“{name}”？\n会跳过自动触发阈值或时间窗，可能消耗现有体力／次数或发送正常招募。\n仍保留游戏限制和安全检查，不购买额外资源。", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            confirmed = choice == QMessageBox.StandardButton.Yes
        if confirmed:
            # QMessageBox会运行嵌套事件循环，确认期间连接或关闭状态可能已经改变。
            self._update_test_actions()
            if not action.isEnabled():
                self.action_label.setText("测试已取消：确认期间游戏连接或运行状态发生变化")
                return
            self._busy_task = task_id
            self.action_label.setText(f"已请求测试：{self.store.snapshot()['daily']['tasks'][task_id]['name']}，等待运行服务回执")
            self._update_test_actions()
            self.test_requested.emit(task_id, {"force_trigger": True})

    def finish_test(self, task_id: str, message: str):
        if self._busy_task != task_id:
            return
        self._busy_task = None
        self.action_label.setText(message)
        self._update_test_actions()
        if self._closing:
            self.close()

    def set_connection(self, *, connected: bool, target_appid: str = "", runtime_ready: bool = False, message: str = ""):
        was_ready = self.runtime_ready
        self.game_connected = bool(connected and target_appid == self.TARGET_APPID)
        self.runtime_ready = self.game_connected and bool(runtime_ready)
        if self.game_connected:
            text = "游戏已连接 · 插件就绪" if self.runtime_ready else "通信已连接 · 功能尚未就绪"
        else:
            text = message or ("非目标游戏，不启用插件" if connected else "等待游戏连接")
        if self.connection_label.text() != text:
            self.connection_label.setText(text)
        if not self.runtime_ready or not was_ready:
            task_text = '游戏与插件已就绪，等待启动托管或手动测试' if self.runtime_ready else (message or '功能尚未就绪，等待连接游戏并完成挂载')
            for panel in self.task_panels.values():
                if panel.runtime_message.text() != task_text:
                    panel.runtime_message.setText(task_text)
        self.set_automation_ready(self.game_connected and self.runtime_ready and not self._closing)
        self._update_test_actions()

    def set_offset_detecting(self, active: bool):
        """自动检测偏移期间弹出/关闭独占窗口。"""
        if self._offset_dialog is None:
            self._offset_dialog = OffsetDialogController(self)
        self._offset_dialog.set_active(bool(active))

    def set_debug_link(self, link: str):
        debug = self.pages["debug"]
        valid = valid_debug_link(link)
        value = link if valid else ""
        if debug.link.text() != value:
            debug.link.setText(value)
        enabled = valid and not self._closing
        if debug.open_button.isEnabled() != enabled:
            debug.open_button.setEnabled(enabled)
        message = "" if valid or not link else "拒绝无效或非本机调试链接"
        if debug.message.text() != message:
            debug.message.setText(message)

    def _open_debug(self):
        debug = self.pages["debug"]
        link = debug.link.text()
        if not valid_debug_link(link) or self._closing:
            return
        try:
            opened = self.chrome_opener(link)
            debug.message.setText("Chrome已打开调试页面" if opened else "未找到Chrome或启动失败，请安装Chrome或检查路径")
        except OSError as exc:
            debug.message.setText(f"Chrome启动失败：{exc}")

    def set_bound_player_id(self, value: str) -> None:
        """显示用于绑定的主角ID；玩家把这个号报给管理员签发 license。

        状态栏也放一份，这样在任何页面都看得到，不用切到"玩家信息透视"。
        """
        text = f"绑定ID：{value}" if value else "绑定ID：未读取"
        self.pages["player"].bound_id.setText(text)
        self.bound_id_label.setText(text)

    def set_player_information(self, text: str, subject: str):
        player = self.pages["player"]
        player.subject.setText(f"{subject} · {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
        player.text.setPlainText(text)
        player.copy_button.setEnabled(bool(text))
        player.export_button.setEnabled(bool(text))

    def _copy_information(self):
        QApplication.clipboard().setText(self.pages["player"].text.toPlainText())

    def _export_information(self):
        text = self.pages["player"].text.toPlainText()
        if not text:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "导出当前玩家信息", "player_info.txt", "文本文件 (*.txt)")
        if filename:
            try:
                Path(filename).write_text(text, encoding="utf-8")
                self.pages["player"].message.setText("已导出所选文件")
            except OSError as exc:
                self.pages["player"].message.setText(f"导出失败：{exc}")

    def reset_session(self):
        self.game_connected = self.runtime_ready = False
        self._busy_task = None
        self.set_automation_ready(False)
        treasure = self.pages["treasure"]
        treasure.set_enabled(False)
        bloodmoon = self.pages["bloodmoon"]
        bloodmoon.set_ready(False)
        bloodmoon.set_probe_running(False)
        bloodmoon.set_flags([], "未开始探测")
        bloodmoon.set_speed_status("等待游戏与插件就绪")
        bloodmoon.set_attack_status("等待游戏与插件就绪")
        bloodmoon.set_message("")
        damage = self.pages["damage"]
        damage.set_ready(False)
        damage.set_status("等待游戏与插件就绪")
        damage.set_hint("就绪后发起一场「好友切磋」即可自动采集（当前完整支持的模式）。")
        damage.set_summary("")
        damage.message.setText("")
        desire = self.pages["desire"]
        desire.set_ready(False)
        desire.set_running(False)
        desire.set_status("等待游戏与插件就绪")
        desire.set_stats("")
        desire.message.setText("")
        player = self.pages["player"]
        player.text.clear()
        player.subject.setText("等待玩家信息")
        player.message.clear()
        player.copy_button.setEnabled(False)
        player.export_button.setEnabled(False)
        self.set_debug_link("")
        self.action_label.setText("会话状态已清空，仅保留配置")
        self.connection_label.setText("等待游戏连接")
        self._update_test_actions()

    def closeEvent(self, event):
        self._closing = True
        self._update_test_actions()
        if not self._shutdown_emitted:
            self._shutdown_emitted = True
            self.shutdown_requested.emit()
        if self._busy_task is not None or self._operation_running or (self._runtime_attached and not self._shutdown_complete):
            self.action_label.setText("等待当前操作确认并关闭内部运行服务后退出")
            if self._shutdown_started is None:
                self._shutdown_started = time.monotonic()
                self._shutdown_delay_timer.start()
            event.ignore()
            return
        self.reset_session()
        self._hide_shutdown_progress()
        event.accept()
