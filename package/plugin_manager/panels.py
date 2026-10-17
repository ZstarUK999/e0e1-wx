"""插件GUI配置表单。开关即时保存，其他参数点击保存后生效。"""

from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger('plugin_manager.configuration')

from PySide6.QtCore import QSignalBlocker, QTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTimeEdit, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .feature_flags import task_enabled
from .store import PRIORITY_MAX, RATIO_MIN, SECONDS_MAX, PluginConfigStore


def set_checked(box: QCheckBox, enabled: bool) -> None:
    blocker = QSignalBlocker(box)
    box.setChecked(enabled)
    del blocker


class DailyPanel(QWidget):
    automation_requested = Signal(bool)

    def __init__(self, store: PluginConfigStore):
        super().__init__()
        self.store = store
        layout = QVBoxLayout(self)
        heading = QLabel("日常自动化")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        layout.addWidget(QLabel("开关立即保存；具体参数在左侧子节点配置。"))
        self.master = QCheckBox("全选／反选全部任务")
        self.master.setObjectName("daily.enabled")
        self.toggles = {}
        layout.addWidget(self.master)
        self.run_button = QPushButton("开始日常自动化")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._toggle_automation)
        layout.addWidget(self.run_button)
        self.automation_state = QLabel("自动化未启动，勾选的任务不会自动执行")
        self.automation_state.setWordWrap(True)
        layout.addWidget(self.automation_state)
        self.automation_running = False
        labels = {"energy": "体力扫荡", "offline_reward": "每小时挂机收益", "sanshi_tombs": "三尸墓藏收取／重开", "artifact_tombs": "法器墓藏收取／重开", "sanshi_raid": "三尸盗掠", "artifact_raid": "法器盗掠", "sanshi_fill": "三尸填土", "artifact_fill": "法器填土", "arena": "定时斗法"}
        for task_id, label in labels.items():
            if not task_enabled(task_id):
                continue
            box = QCheckBox(label)
            box.setObjectName(task_id + ".enabled")
            layout.addWidget(box)
            self.toggles[task_id] = box
            box.toggled.connect(lambda enabled, key=task_id: self._change(key, enabled))
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch()
        self.master.toggled.connect(lambda enabled: self._change(None, enabled))
        store.changed.connect(self.sync)
        self.sync(store.snapshot())

    def _change(self, key, enabled):
        try:
            if key is None:
                self.store.set_all_tasks_enabled(enabled)
            else:
                self.store.set_task_enabled(key, enabled)
            self.message.setText("开关已保存")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync(self.store.snapshot())

    def _toggle_automation(self):
        self.automation_requested.emit(not self.automation_running)

    def set_automation_running(self, running):
        self.automation_running = bool(running)
        self.run_button.setText("停止日常自动化" if running else "开始日常自动化")
        enabled = sum(1 for task in self.store.snapshot()["daily"]["tasks"].values() if task["enabled"])
        self.automation_state.setText(f"自动化运行中：{enabled} 个任务已启用" if running
                                      else "自动化未启动，勾选的任务不会自动执行")

    def set_automation_ready(self, ready):
        self.run_button.setEnabled(bool(ready) or self.automation_running)

    def sync(self, state):
        set_checked(self.master, all(task["enabled"] for task in state["daily"]["tasks"].values()))
        for key, box in self.toggles.items():
            set_checked(box, state["daily"]["tasks"][key]["enabled"])


class TaskPanel(QGroupBox):
    """一个实际任务的开关和参数，不保存当前会话运行状态。"""

    def __init__(self, store: PluginConfigStore, task_id: str):
        task = store.snapshot()["daily"]["tasks"][task_id]
        super().__init__(task["name"])
        self.store, self.task_id = store, task_id
        self.fields = {}
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("启用此任务")
        self.enabled.setObjectName(task_id + ".enabled")
        layout.addWidget(self.enabled)
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(self.form)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("高级调度参数")
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setStyleSheet('QToolButton { color: #888; border: none; background: transparent; padding: 2px; text-align: left; }')
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(lambda opened: self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow))
        self.advanced = QWidget()
        basic_form = self.form
        self.form = QFormLayout(self.advanced)
        self._number("schedule.interval_seconds", "检查间隔（秒）", task["schedule"]["interval_seconds"])
        self._number("timeout_seconds", "单次任务超时（秒）", task["timeout_seconds"])
        self._number("retry_seconds", "失败后检查间隔（秒）", task["retry_seconds"])
        self._integer("priority", "优先级（数值小优先）", task["priority"], minimum=0)
        self.form = basic_form
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        params = task["params"]
        if task_id == "energy":
            ratio = QDoubleSpinBox()
            ratio.setRange(RATIO_MIN * 100, 100)
            ratio.setDecimals(1)
            ratio.setSuffix(" %")
            ratio.setValue(params.get("trigger_ratio", 0.9) * 100)
            self._field("params.trigger_ratio", "体力触发阈值", ratio)
            eye = QLineEdit(params.get("formation_eye_name", "双子僵尸"))
            self._field("params.formation_eye_name", "阵眼鬼仆名称", eye)
            recover = QSpinBox()
            recover.setRange(1, 3600)
            recover.setSuffix(" 秒/点")
            recover.setValue(int(params.get("energy_recover_seconds", 420)))
            self._field("params.energy_recover_seconds", "体力恢复间隔", recover)
            note = QLabel("仅比较已有三尸／法器方案；尽量使用现有体力；结束还原原方案和阵眼，不交换培养。")
            note.setWordWrap(True)
            layout.addWidget(note)
        elif task_id == "offline_reward":
            self._number("params.claim_interval_seconds", "领取间隔（秒）", params.get("claim_interval_seconds", 3600))
        elif task_id.endswith("_tombs"):
            self._bool("params.recruit", "重开后发布正常招募", params.get("recruit", True))
        elif task_id.endswith("_raid"):
            self._integer("params.minimum_tombs", "单个目标最少可盗墓数", params.get("minimum_tombs", 16))
            self._number("params.rescan_seconds", "未找到目标时重扫（秒）", params.get("rescan_seconds", 60))
            self._bool("params.skip_failed_players", "当前会话跳过战败目标", params.get("skip_failed_players", True))
        elif task_id.endswith("_fill"):
            note = QLabel("有剩余次数且目标可以填土就执行，不设置墓葬数量门槛。")
            note.setWordWrap(True)
            layout.addWidget(note)
        elif task_id == "arena":
            for key, title in (("start", "开始时间（北京时间）"), ("end", "截止时间（北京时间）")):
                editor = QTimeEdit(QTime.fromString(task["schedule"][key], "HH:mm"))
                editor.setDisplayFormat("HH:mm")
                self._field("schedule." + key, title, editor)
            excluded = QPlainTextEdit()
            excluded.setPlaceholderText("每行一个玩家ID，如：安卓|天书通悟561服#12402987")
            excluded.setPlainText("\n".join(str(v) for v in params.get("excluded_player_ids", [])))
            excluded.setMinimumHeight(90)
            self._field("params.excluded_player_ids", "不挑战的玩家ID", excluded)
            self._bool("params.continuous", "窗口内连续挑战", params.get("continuous", True))
            self._bool("params.skip_battle", "点击官方跳过战斗", params.get("skip_battle", True))
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced)
        self.save_button = QPushButton("保存参数")
        self.save_button.setObjectName(task_id + ".save")
        layout.addWidget(self.save_button)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.runtime_message = QLabel("运行服务尚未接入")
        self.runtime_message.setWordWrap(True)
        layout.addWidget(self.runtime_message)
        self.test_button = QPushButton("测试执行")
        self.test_button.setObjectName(task_id + ".test")
        self.test_button.setEnabled(False)
        layout.addWidget(self.test_button)
        self.enabled.toggled.connect(self._toggle)
        self.save_button.clicked.connect(self.save)
        store.changed.connect(self.sync_switch)
        self.sync_switch(store.snapshot())

    def _field(self, key, label, widget):
        widget.setObjectName(self.task_id + "." + key)
        self.fields[key] = widget
        self.form.addRow(label, widget)

    def _number(self, key, label, value):
        widget = QDoubleSpinBox()
        widget.setDecimals(3)
        widget.setRange(0.001, SECONDS_MAX)
        widget.setValue(value)
        self._field(key, label, widget)

    def _integer(self, key, label, value, minimum=1):
        widget = QSpinBox()
        widget.setRange(minimum, PRIORITY_MAX)
        widget.setValue(value)
        self._field(key, label, widget)

    def _bool(self, key, label, value):
        widget = QCheckBox()
        widget.setChecked(value)
        self._field(key, label, widget)

    def sync_switch(self, state):
        # 参数输入可能尚未保存，外部开关更新不能覆写它们。
        set_checked(self.enabled, state["daily"]["tasks"][self.task_id]["enabled"])

    def _toggle(self, enabled):
        try:
            self.store.set_task_enabled(self.task_id, enabled)
            self.message.setText("开关已立即保存")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync_switch(self.store.snapshot())

    def save(self):
        patch = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QTimeEdit):
                value = widget.time().toString("HH:mm")
            elif isinstance(widget, QPlainTextEdit):
                value = [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]
            elif isinstance(widget, QLineEdit):
                value = widget.text().strip()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            else:
                value = widget.value()
            if key == "params.trigger_ratio":
                value /= 100
            if "." in key:
                section, name = key.split(".", 1)
                patch.setdefault(section, {})[name] = value
            else:
                patch[key] = value
        try:
            self.store.update_task(self.task_id, patch)
            self.message.setText("参数已保存，下一个安全步骤生效")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")


class GlobalPanel(QWidget):
    """全局设置：只影响观察节奏，不改变任何安全检查。"""

    def __init__(self, store: PluginConfigStore):
        super().__init__()
        self.store = store
        layout = QVBoxLayout(self)
        heading = QLabel("全局设置")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(self.form)
        self.delay = QSpinBox()
        self.delay.setRange(0, 5000)
        self.delay.setSingleStep(100)
        self.delay.setSuffix(" 毫秒")
        self.delay.setValue(store.snapshot()["ui"]["delay_ms"])
        self.form.addRow("UI 操作间隔", self.delay)
        note = QLabel("每一步 UI 操作之间等待的时间，方便观察执行过程；只影响节奏，不改变任何安全检查。\n"
                      "目标游戏需要你自己在微信里打开：插件不会主动打开微信或小游戏。")
        note.setWordWrap(True)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.save_button = QPushButton("保存全局设置")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch()
        store.changed.connect(lambda state: self.sync(state))

    def sync(self, state):
        value = state["ui"]["delay_ms"]
        if self.delay.value() != value:
            self.delay.setValue(value)

    def save(self):
        try:
            self.store.set_ui_delay(self.delay.value())
            self.message.setText("全局设置已保存，下一次操作生效")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync(self.store.snapshot())


class TreasurePanel(QWidget):
    """摸金地图：工具栏脚本的地图导出与画面标注。"""

    dump_requested = Signal()
    overlay_requested = Signal(bool)
    status_requested = Signal()

    def __init__(self, store: PluginConfigStore):
        super().__init__()
        self.store = store
        layout = QVBoxLayout(self)
        heading = QLabel("摸金地图")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        note = QLabel("读取当前摸金地图缓存（含未探索格子的真实类型）并可在画面上标注；开关立即保存。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.enabled = QCheckBox("启用摸金地图透视")
        self.enabled.setObjectName("treasure.enabled")
        layout.addWidget(self.enabled)
        self.auto_dump = QCheckBox("自动导出地图（按刷新间隔）")
        self.auto_dump.setObjectName("treasure.auto_dump")
        layout.addWidget(self.auto_dump)
        self.overlay = QCheckBox("在画面上显示格子标注")
        self.overlay.setObjectName("treasure.overlay")
        layout.addWidget(self.overlay)
        form = QFormLayout()
        self.refresh = QSpinBox()
        self.refresh.setRange(1, 3600)
        self.refresh.setSuffix(" 秒")
        form.addRow("刷新间隔", self.refresh)
        layout.addLayout(form)
        self.save_button = QPushButton("保存摸金设置")
        layout.addWidget(self.save_button)
        buttons = QHBoxLayout()
        self.dump_button = QPushButton("立即导出地图")
        self.on_button = QPushButton("开启标注")
        self.off_button = QPushButton("关闭标注")
        self.status_button = QPushButton("查询状态")
        for button in (self.dump_button, self.on_button, self.off_button, self.status_button):
            button.setEnabled(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.subject = QLabel("等待摸金地图")
        layout.addWidget(self.subject)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.enabled.toggled.connect(lambda value: self._flag("enabled", value))
        self.auto_dump.toggled.connect(lambda value: self._flag("auto_dump", value))
        self.overlay.toggled.connect(lambda value: self._flag("overlay", value))
        self.save_button.clicked.connect(self.save)
        self.dump_button.clicked.connect(self.dump_requested.emit)
        self.on_button.clicked.connect(lambda: self.overlay_requested.emit(True))
        self.off_button.clicked.connect(lambda: self.overlay_requested.emit(False))
        self.status_button.clicked.connect(self.status_requested.emit)
        store.changed.connect(self.sync)
        self.sync(store.snapshot())
        self.set_enabled(False)

    def _flag(self, key, value):
        try:
            self.store.set_treasure({key: value})
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync(self.store.snapshot())

    def save(self):
        try:
            self.store.set_treasure({"refresh_seconds": self.refresh.value()})
            self.message.setText("摸金设置已保存")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync(self.store.snapshot())

    def sync(self, state):
        treasure = state["treasure"]
        set_checked(self.enabled, treasure["enabled"])
        set_checked(self.auto_dump, treasure["auto_dump"])
        set_checked(self.overlay, treasure["overlay"])
        if self.refresh.value() != treasure["refresh_seconds"]:
            self.refresh.setValue(treasure["refresh_seconds"])

    def set_enabled(self, ready: bool):
        for button in (self.dump_button, self.on_button, self.off_button, self.status_button):
            button.setEnabled(bool(ready))

    def set_map(self, text: str, subject: str):
        self.subject.setText(subject)
        self.text.setPlainText(text)

    def set_message(self, message: str):
        self.message.setText(message)


class PlayerPanel(QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("玩家信息透视"))
        # 绑定ID是后台签发 license 时要用到的账号ID（游戏 g.ROLE.id），玩家照这个报给管理员
        self.bound_id = QLabel("绑定ID：未读取")
        layout.addWidget(self.bound_id)
        self.enabled = QCheckBox("启用玩家信息展示")
        layout.addWidget(self.enabled)
        note = QLabel("进入玩家信息页后展示本人完整信息或对方公开信息，不绕过隐藏设置。仅保留当前会话最近一份。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.subject = QLabel("等待玩家信息")
        layout.addWidget(self.subject)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        self.copy_button, self.export_button = QPushButton("复制"), QPushButton("导出文本")
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)
        self.message = QLabel("")
        layout.addWidget(self.message)
        self.enabled.toggled.connect(self._toggle)
        store.changed.connect(lambda state: set_checked(self.enabled, state["player"]["enabled"]))
        set_checked(self.enabled, store.snapshot()["player"]["enabled"])
        self.copy_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def _toggle(self, enabled):
        try:
            self.store.set_player_enabled(enabled)
            self.message.setText("开关已保存")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            set_checked(self.enabled, self.store.snapshot()["player"]["enabled"])


class BloodmoonPanel(QWidget):
    """血月战场：战旗探测是只读展示，加速与攻击只走正常按钮并保留游戏全部限制。

    战旗探测由「开始/停止探测」按钮控制，运行状态不写配置；加速与攻击的开关即时保存，
    但只有游戏在血月地图里、插件就绪时才真正执行。
    """

    probe_requested = Signal(bool)
    mark_requested = Signal(bool)
    diagnose_requested = Signal()
    reset_requested = Signal()

    def __init__(self, store: PluginConfigStore):
        super().__init__()
        self.store = store
        # 这一页分组多，直接铺会被压扁：整页放进滚动区，各分组按内容取高度。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        outer.addWidget(scroll)
        heading = QLabel("血月战场")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        note = QLabel("战旗探测只读战场内已同步的旗帜数据；自动加速与自动攻击只点正常按钮，"
                      "保留冷却、剩余时间、道具与状态限制，被拒绝就停。\n"
                      "不读取、不展示被游戏隐藏的敌方隐匿行军，隐匿目标不作为自动攻击的选敌来源。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.enabled = QCheckBox("启用血月战场功能")
        self.enabled.setObjectName("bloodmoon.enabled")
        layout.addWidget(self.enabled)

        self.probe_box = QGroupBox("入场战旗探测（按阴司分组，战力降序）")
        probe_layout = QVBoxLayout(self.probe_box)
        buttons = QHBoxLayout()
        self.probe_start = QPushButton("开始探测")
        self.probe_stop = QPushButton("停止探测")
        self.probe_stop.setEnabled(False)
        buttons.addWidget(self.probe_start)
        buttons.addWidget(self.probe_stop)
        probe_layout.addLayout(buttons)
        probe_form = QFormLayout()
        self.probe_refresh = QSpinBox()
        self.probe_refresh.setRange(1, 3600)
        self.probe_refresh.setSuffix(" 秒")
        self.probe_refresh.setObjectName("bloodmoon.flag_probe.refresh_seconds")
        probe_form.addRow("刷新间隔", self.probe_refresh)
        self.probe_top = QSpinBox()
        self.probe_top.setRange(1, 50)
        self.probe_top.setSuffix(" 人")
        self.probe_top.setObjectName("bloodmoon.flag_probe.top_members")
        probe_form.addRow("每个阴司默认显示", self.probe_top)
        probe_layout.addLayout(probe_form)
        self.probe_save = QPushButton("保存探测设置")
        probe_layout.addWidget(self.probe_save)
        self.probe_subject = QLabel("未开始探测")
        self.probe_subject.setWordWrap(True)
        probe_layout.addWidget(self.probe_subject)
        self.probe_tree = QTreeWidget()
        self.probe_tree.setHeaderLabels(["阴司／成员", "战力", "战旗", "备注"])
        self.probe_tree.setRootIsDecorated(True)
        self.probe_tree.setAlternatingRowColors(True)
        self.probe_tree.setMinimumHeight(240)
        probe_layout.addWidget(self.probe_tree, 1)
        layout.addWidget(self.probe_box)

        self.speed_box = QGroupBox("自动加速（正常加速按钮）")
        speed_layout = QVBoxLayout(self.speed_box)
        self.speed_enabled = QCheckBox("行军中自动点击加速")
        self.speed_enabled.setObjectName("bloodmoon.speed_up.enabled")
        speed_layout.addWidget(self.speed_enabled)
        speed_form = QFormLayout()
        self.speed_times = QSpinBox()
        self.speed_times.setRange(0, 99)
        self.speed_times.setSuffix(" 次")
        self.speed_times.setObjectName("bloodmoon.speed_up.max_times")
        speed_form.addRow("单次行军最多加速", self.speed_times)
        self.speed_margin = QSpinBox()
        self.speed_margin.setRange(0, 60)
        self.speed_margin.setSuffix(" 秒")
        self.speed_margin.setObjectName("bloodmoon.speed_up.safety_margin_seconds")
        speed_form.addRow("最小剩余时间安全余量", self.speed_margin)
        speed_layout.addLayout(speed_form)
        self.speed_save = QPushButton("保存加速设置")
        speed_layout.addWidget(self.speed_save)
        self.speed_status = QLabel("未启用")
        self.speed_status.setWordWrap(True)
        speed_layout.addWidget(self.speed_status)
        layout.addWidget(self.speed_box)

        self.attack_box = QGroupBox("自动攻击（同节点、可见、战力更低）")
        attack_layout = QVBoxLayout(self.attack_box)
        self.attack_enabled = QCheckBox("自动挑战符合条件的玩家")
        self.attack_enabled.setObjectName("bloodmoon.attack.enabled")
        attack_layout.addWidget(self.attack_enabled)
        attack_form = QFormLayout()
        self.attack_ratio = QSpinBox()
        self.attack_ratio.setRange(10, 200)
        self.attack_ratio.setSuffix(" %")
        self.attack_ratio.setObjectName("bloodmoon.attack.power_ratio")
        attack_form.addRow("目标战力低于我方的比例", self.attack_ratio)
        self.attack_limit = QSpinBox()
        self.attack_limit.setRange(0, PRIORITY_MAX)
        self.attack_limit.setSpecialValueText("不限制")
        self.attack_limit.setObjectName("bloodmoon.attack.power_limit")
        attack_form.addRow("目标战力绝对上限", self.attack_limit)
        self.attack_max = QSpinBox()
        self.attack_max.setRange(0, 999)
        self.attack_max.setSpecialValueText("不限制")
        self.attack_max.setObjectName("bloodmoon.attack.max_battles")
        attack_form.addRow("单轮最多挑战", self.attack_max)
        self.attack_wait = QSpinBox()
        self.attack_wait.setRange(0, 60)
        self.attack_wait.setSuffix(" 秒")
        self.attack_wait.setObjectName("bloodmoon.attack.wait_seconds")
        attack_form.addRow("两场之间等待", self.attack_wait)
        attack_layout.addLayout(attack_form)
        self.attack_save = QPushButton("保存攻击设置")
        attack_layout.addWidget(self.attack_save)
        self.attack_status = QLabel("未启用")
        self.attack_status.setWordWrap(True)
        attack_layout.addWidget(self.attack_status)
        layout.addWidget(self.attack_box)

        self.mark_box = QGroupBox("水旗标注")
        mark_layout = QVBoxLayout(self.mark_box)
        self.mark_enabled = QCheckBox("给已可见的隐身单位画「隐身水旗」标识")
        self.mark_enabled.setObjectName("bloodmoon.stealth_mark.enabled")
        mark_layout.addWidget(self.mark_enabled)
        mark_note = QLabel("只标注当前本来就能看到的单位（已到达本节点、已在可见队列里）。"
                           "不揭示被游戏隐藏的敌方行军，也不把它们加进自动攻击的候选。")
        mark_note.setWordWrap(True)
        mark_layout.addWidget(mark_note)
        layout.addWidget(self.mark_box)

        bottom = QHBoxLayout()
        self.diagnose_button = QPushButton("诊断当前战场数据")
        self.reset_button = QPushButton("复位（清除结果未知状态）")
        bottom.addWidget(self.diagnose_button)
        bottom.addWidget(self.reset_button)
        layout.addLayout(bottom)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch()
        scroll.setWidget(content)
        self.set_ready(False)
        self.enabled.toggled.connect(lambda value: self._patch({"enabled": value}))
        self.speed_enabled.toggled.connect(lambda value: self._patch({"speed_up": {"enabled": value}}))
        self.attack_enabled.toggled.connect(lambda value: self._patch({"attack": {"enabled": value}}))
        self.mark_enabled.toggled.connect(lambda value: self._patch({"stealth_mark": {"enabled": value}}))
        self.probe_start.clicked.connect(lambda: self.probe_requested.emit(True))
        self.probe_stop.clicked.connect(lambda: self.probe_requested.emit(False))
        self.diagnose_button.clicked.connect(self.diagnose_requested.emit)
        self.reset_button.clicked.connect(self.reset_requested.emit)
        for button, patch in ((self.probe_save, self._probe_patch), (self.speed_save, self._speed_patch),
                              (self.attack_save, self._attack_patch)):
            button.clicked.connect(lambda _checked=False, fn=patch: self._save(fn))
        store.changed.connect(self.sync)
        self.sync(store.snapshot())

    def _patch(self, patch: dict) -> None:
        try:
            self.store.set_bloodmoon(patch)
            self.message.setText("开关已保存")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync(self.store.snapshot())

    def _save(self, patch) -> None:
        try:
            self.store.set_bloodmoon(patch())
            self.message.setText("参数已保存")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync(self.store.snapshot())

    def _probe_patch(self) -> dict:
        return {"flag_probe": {"refresh_seconds": self.probe_refresh.value(), "top_members": self.probe_top.value()}}

    def _speed_patch(self) -> dict:
        return {"speed_up": {"max_times": self.speed_times.value(),
                             "safety_margin_seconds": self.speed_margin.value()}}

    def _attack_patch(self) -> dict:
        return {"attack": {"power_ratio": self.attack_ratio.value(), "power_limit": self.attack_limit.value(),
                           "max_battles": self.attack_max.value(), "wait_seconds": self.attack_wait.value()}}

    def sync(self, state):
        bloodmoon = state.get("bloodmoon") or {}
        probe = bloodmoon.get("flag_probe") or {}
        speed = bloodmoon.get("speed_up") or {}
        attack = bloodmoon.get("attack") or {}
        mark = bloodmoon.get("stealth_mark") or {}
        set_checked(self.enabled, bool(bloodmoon.get("enabled")))
        set_checked(self.speed_enabled, bool(speed.get("enabled")))
        set_checked(self.attack_enabled, bool(attack.get("enabled")))
        set_checked(self.mark_enabled, bool(mark.get("enabled")))
        for widget, value in ((self.probe_refresh, probe.get("refresh_seconds", 5)),
                              (self.probe_top, probe.get("top_members", 3)),
                              (self.speed_times, speed.get("max_times", 3)),
                              (self.speed_margin, speed.get("safety_margin_seconds", 2)),
                              (self.attack_ratio, attack.get("power_ratio", 100)),
                              (self.attack_limit, attack.get("power_limit", 0)),
                              (self.attack_max, attack.get("max_battles", 10)),
                              (self.attack_wait, attack.get("wait_seconds", 3))):
            if widget.value() != value:
                widget.setValue(int(value))

    def set_ready(self, ready: bool) -> None:
        """游戏与插件未就绪时，除总开关外一律禁用。"""
        for widget in (self.probe_start, self.probe_save, self.diagnose_button, self.reset_button,
                       self.speed_enabled, self.speed_save, self.attack_enabled, self.attack_save,
                       self.mark_enabled):
            widget.setEnabled(bool(ready))
        if not ready:
            self.probe_stop.setEnabled(False)

    def set_probe_running(self, running: bool) -> None:
        self.probe_start.setEnabled(not running)
        self.probe_stop.setEnabled(bool(running))
        if not running:
            self.probe_subject.setText("已停止探测")

    def set_flags(self, rows: list, subject: str) -> None:
        """按阴司重建列表：阴司那一行带前三成员的战旗摘要，展开才是全部成员（战力降序）。"""
        self.probe_subject.setText(subject)
        scroll = self.probe_tree.verticalScrollBar().value()
        expanded = {item.text(0) for item in self._top_items() if item.isExpanded()}
        self.probe_tree.clear()
        for group in rows or []:
            members = list(group.get("members", []) or [])
            summary = " ".join(f"{m.get('name') or '?'}·{m.get('flag') or '?'}" for m in members[:3])
            top = QTreeWidgetItem([str(group.get("title") or "未命名阴司"),
                                   str(group.get("power") or ""), summary,
                                   "展开看全部" if members else str(group.get("note") or "")])
            for member in members:
                top.addChild(self._member_item(member))
            self.probe_tree.addTopLevelItem(top)
            if group.get("title") in expanded:
                top.setExpanded(True)
        self.probe_tree.resizeColumnToContents(0)
        self.probe_tree.verticalScrollBar().setValue(scroll)

    def _top_items(self):
        root = self.probe_tree.invisibleRootItem()
        return [root.child(index) for index in range(root.childCount())]

    @staticmethod
    def _member_item(member: dict) -> QTreeWidgetItem:
        return QTreeWidgetItem([str(member.get("name") or member.get("roleId") or "?"),
                                str(member.get("power") or ""), str(member.get("flag") or ""),
                                str(member.get("note") or "")])

    def set_speed_status(self, text: str) -> None:
        self.speed_status.setText(text)

    def set_attack_status(self, text: str) -> None:
        self.attack_status.setText(text)

    def set_message(self, text: str) -> None:
        self.message.setText(text)


class DebugPanel(QWidget):
    open_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("调试信息"))
        note = QLabel("内部CDP调试服务接入后显示实际页面链接；只有点击按钮才打开Chrome。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.link = QLineEdit()
        self.link.setReadOnly(True)
        self.link.setPlaceholderText("暂无调试页面链接")
        layout.addWidget(self.link)
        self.open_button = QPushButton("用 Chrome 打开调试页面")
        self.open_button.setEnabled(False)
        layout.addWidget(self.open_button)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch()
        self.open_button.clicked.connect(self.open_requested.emit)


class DamagePanel(QWidget):
    """PVP伤害分析：进战斗自动采集，面板显示基础信息与分数，按钮跳转浏览器看完整图表。"""

    refresh_requested = Signal()
    reset_requested = Signal()
    debug_requested = Signal()
    open_report_requested = Signal()

    def __init__(self, store: PluginConfigStore):
        super().__init__()
        self.store = store
        layout = QVBoxLayout(self)
        heading = QLabel("PVP伤害分析")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        note = QLabel("进入 PVP 对局自动采集我方与敌方两个 World 的伤害，战斗结束后在 logs/ 生成 HTML 报告。"
                      "当前完整支持的是好友切磋：它可以随便打，也可以直接点「跳过战斗」。"
                      "斗法／血月也能采，但它们的跳过走服务端结算，会丢数据——下面那行提示会说明当前模式。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.enabled = QCheckBox("启用自动采集")
        self.enabled.setObjectName("damage.enabled")
        layout.addWidget(self.enabled)
        self.auto_csv = QCheckBox("同时导出逐条事件 CSV")
        self.auto_csv.setObjectName("damage.auto_csv")
        layout.addWidget(self.auto_csv)

        self.status = QLabel("等待游戏与插件就绪")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("panelHint")
        layout.addWidget(self.hint)

        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText("打完一场 PVP 后这里显示分数与双方伤害拆解")
        layout.addWidget(self.summary, 1)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("立即取一次")
        self.reset_button = QPushButton("清空重采")
        self.debug_button = QPushButton("诊断")
        self.open_button = QPushButton("打开图表报告")
        for button in (self.refresh_button, self.reset_button, self.debug_button, self.open_button):
            buttons.addWidget(button)
        for button in (self.refresh_button, self.reset_button, self.debug_button):
            button.setEnabled(False)
        layout.addLayout(buttons)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self._report_path = None
        self.enabled.toggled.connect(lambda value: self._flag("enabled", value))
        self.auto_csv.toggled.connect(lambda value: self._flag("auto_csv", value))
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.reset_button.clicked.connect(self.reset_requested.emit)
        self.debug_button.clicked.connect(self.debug_requested.emit)
        self.open_button.clicked.connect(self.open_report_requested.emit)
        store.changed.connect(self.sync)
        self.sync(store.snapshot())

    def _flag(self, key, value):
        try:
            self.store.set_damage({key: value})
            self.message.setText("开关已保存")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync(self.store.snapshot())

    def sync(self, state):
        damage = state.get("damage") or {}
        set_checked(self.enabled, bool(damage.get("enabled")))
        set_checked(self.auto_csv, bool(damage.get("auto_csv")))

    def set_ready(self, ready: bool):
        for button in (self.refresh_button, self.reset_button, self.debug_button):
            button.setEnabled(bool(ready))

    def set_status(self, text: str):
        self.status.setText(text)

    def set_hint(self, text: str):
        self.hint.setText(text)

    def set_summary(self, text: str):
        self.summary.setPlainText(text)

    def set_report_path(self, path):
        self._report_path = Path(path) if path else None
        self.open_button.setEnabled(self._report_path is not None and self._report_path.exists())
        if self._report_path is not None:
            self.message.setText(f"报告：{self._report_path}")


class DesirePanel(QWidget):
    """三尸自动合成：手动点开始跑一批，随时停止；每次合成落一行日志，可生成离线 HTML 报告。

    策略是从最低品质档开始两两合成，某品质连续失败到上限就把材料品质升一档；
    材料品质超过「最高材料品质」就停止。品质名称以游戏内真名为准，连不上时显示兜底名。
    """

    start_requested = Signal()
    stop_requested = Signal()
    report_requested = Signal()
    probe_requested = Signal()
    open_report_requested = Signal()

    KIND_ITEMS = (("贪", 1), ("嗔", 2), ("痴", 3))
    QUALITY_FALLBACK = {1: "白", 2: "蓝", 3: "紫", 4: "橙", 5: "红", 6: "黑金", 7: "幻彩", 8: "轮回"}

    def __init__(self, store: PluginConfigStore):
        super().__init__()
        self.store = store
        self._report_path = None
        self._quality_names = dict(self.QUALITY_FALLBACK)
        layout = QVBoxLayout(self)
        heading = QLabel("三尸自动合成")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        note = QLabel("从最低的、凑得出一对的品质档开始两两合成，某品质连续失败到上限就把材料品质升一档；"
                      "同一档里先用「凡」当材料，本档最后一次机会时只要有「心」就改用「心」；"
                      "材料品质超过上限或停止时结束本批。合成会消耗三尸，拿不到明确回执会立刻停止。")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.kind = QComboBox()
        for text, value in self.KIND_ITEMS:
            self.kind.addItem(text, value)
        self.kind.setObjectName("desire.kind")
        form.addRow("三尸种类", self.kind)

        self.start_quality = QSpinBox()
        self.start_quality.setRange(1, 8)
        self.start_quality.setObjectName("desire.start_quality")
        form.addRow("起始材料品质", self.start_quality)

        self.max_quality = QSpinBox()
        self.max_quality.setRange(1, 8)
        self.max_quality.setObjectName("desire.max_material_quality")
        form.addRow("最高材料品质（含）", self.max_quality)
        layout.addLayout(form)

        self.limit_note = QLabel("4=橙：橙→红 是最后一步，红不再当材料；3=紫：紫→橙 后停止。")
        self.limit_note.setWordWrap(True)
        layout.addWidget(self.limit_note)

        self.limits_box = QGroupBox("各品质连续失败上限")
        limits_layout = QFormLayout(self.limits_box)
        self.limits = {}
        for quality in range(1, 9):
            box = QSpinBox()
            box.setRange(1, 99)
            box.setObjectName(f"desire.fail_limits.{quality}")
            self.limits[quality] = box
            limits_layout.addRow(self._quality_label(quality), box)
        layout.addWidget(self.limits_box)

        bottom = QFormLayout()
        self.max_attempts = QSpinBox()
        self.max_attempts.setRange(1, 5000)
        self.max_attempts.setObjectName("desire.max_attempts")
        bottom.addRow("单批次最多合成次数", self.max_attempts)
        self.expected_rate = QDoubleSpinBox()
        self.expected_rate.setRange(0.1, 100.0)
        self.expected_rate.setDecimals(1)
        self.expected_rate.setSuffix(" %")
        self.expected_rate.setObjectName("desire.expected_rate")
        bottom.addRow("报告理论成功率（默认官方宣称）", self.expected_rate)
        layout.addLayout(bottom)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("开始合成")
        self.stop_button = QPushButton("停止")
        self.report_button = QPushButton("生成并打开报告")
        self.probe_button = QPushButton("诊断现场")
        self.stop_button.setEnabled(False)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.report_button)
        buttons.addWidget(self.probe_button)
        layout.addLayout(buttons)

        self.status = QLabel("等待游戏与插件就绪")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.stats = QPlainTextEdit()
        self.stats.setReadOnly(True)
        self.stats.setPlaceholderText("就绪后这里显示可合成库存")
        layout.addWidget(self.stats, 1)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.kind.currentIndexChanged.connect(lambda _: self._save())
        for widget in (self.start_quality, self.max_quality, self.max_attempts):
            widget.valueChanged.connect(lambda _: self._save())
        self.expected_rate.valueChanged.connect(lambda _: self._save())
        for box in self.limits.values():
            box.valueChanged.connect(lambda _: self._save())
        self.start_button.clicked.connect(self.start_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.report_button.clicked.connect(self.report_requested.emit)
        self.probe_button.clicked.connect(self.probe_requested.emit)
        store.changed.connect(self.sync)
        self.sync(store.snapshot())

    def _quality_label(self, quality: int) -> str:
        return f"{quality} {self._quality_names.get(quality, '?')}"

    def set_quality_names(self, names: dict) -> None:
        """用游戏内的真名替换兜底名；连不上游戏时保持兜底。"""
        for key, value in (names or {}).items():
            try:
                self._quality_names[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
        for quality, box in self.limits.items():
            label = self.limits_box.layout().labelForField(box)
            if label is not None:
                label.setText(self._quality_label(quality))

    def _save(self):
        try:
            self.store.set_desire({
                "kind": self.kind.currentData() or 1,
                "start_quality": self.start_quality.value(),
                "max_material_quality": self.max_quality.value(),
                "fail_limits": {str(q): box.value() for q, box in self.limits.items()},
                "max_attempts": self.max_attempts.value(),
                "expected_rate": self.expected_rate.value(),
            })
            self.message.setText("参数已保存")
        except (OSError, ValueError) as exc:
            LOG.exception('插件配置保存失败')
            self.message.setText(f"保存失败：{exc}")
            self.sync(self.store.snapshot())

    def sync(self, state):
        config = state.get("desire") or {}
        index = self.kind.findData(int(config.get("kind") or 1))
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(index if index >= 0 else 0)
        self.kind.blockSignals(False)
        for widget, key, default in ((self.start_quality, "start_quality", 1),
                                     (self.max_quality, "max_material_quality", 4),
                                     (self.max_attempts, "max_attempts", 200)):
            widget.blockSignals(True)
            widget.setValue(int(config.get(key) or default))
            widget.blockSignals(False)
        self.expected_rate.blockSignals(True)
        self.expected_rate.setValue(float(config.get("expected_rate") or 30.0))
        self.expected_rate.blockSignals(False)
        limits = config.get("fail_limits") or {}
        for quality, box in self.limits.items():
            box.blockSignals(True)
            box.setValue(int(limits.get(str(quality)) or limits.get(quality) or 4))
            box.blockSignals(False)

    def set_ready(self, ready: bool):
        self.start_button.setEnabled(bool(ready))
        self.report_button.setEnabled(True)

    def set_running(self, running: bool):
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(bool(running))

    def set_status(self, text: str):
        self.status.setText(text)

    def set_stats(self, text: str):
        self.stats.setPlainText(text)

    def set_message(self, text: str):
        self.message.setText(text)

    def set_report_path(self, path):
        self._report_path = Path(path) if path else None
        if self._report_path is not None and self._report_path.exists():
            self.message.setText(f"报告：{self._report_path}")
            self.open_report_requested.emit()
        elif self._report_path is not None:
            self.message.setText(f"报告未生成：{self._report_path}")
