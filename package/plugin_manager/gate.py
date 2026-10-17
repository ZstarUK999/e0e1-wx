"""启动门禁占位面板：连接链路就绪前，主窗口只有一个居中的提示界面。

阶段由 PluginRuntime 按真实连接进度推进，不靠定时器猜：

    init       调试链路（frida hook／CDP）建立中 → "初始化中" + 转圈
    wait_game  链路已就绪，等目标游戏接入       → "请打开游戏"
    mounting   目标游戏已接入，挂载脚本中       → "游戏已打开，正在挂载脚本"
    denied     玩家ID读到了但授权对不上         → 明示原因与读到的ID

主 UI（左侧树 + 各功能面板）只在 `PluginWindow.show_main_ui()` 之后才可见。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

PHASE_INIT = "init"
PHASE_WAIT_GAME = "wait_game"
PHASE_MOUNTING = "mounting"
PHASE_DENIED = "denied"

PHASE_TITLES = {
    PHASE_INIT: "初始化中",
    PHASE_WAIT_GAME: "请打开游戏",
    PHASE_MOUNTING: "游戏已打开，正在挂载脚本",
    PHASE_DENIED: "此账号未授权",
}

# 只有"初始化中"才转圈；等游戏和挂载脚本都是在等一个明确动作，转圈等于假装还在加载。
SPINNER_PHASES = frozenset({PHASE_INIT})


class Spinner(QWidget):
    """自绘的转圈指示器：不依赖原生样式，浅色／深色都看得清。"""

    SEGMENTS = 12
    INTERVAL_MS = 80
    DOT_RATIO = 0.16  # 圆点直径 / 控件边长

    def __init__(self, parent=None, *, diameter: int = 36):
        super().__init__(parent)
        self._step = 0
        self.setFixedSize(diameter, diameter)
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def _tick(self) -> None:
        self._step = (self._step + 1) % self.SEGMENTS
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 回调命名
        side = min(self.width(), self.height())
        if side <= 0:
            return
        dot = max(2.0, side * self.DOT_RATIO)
        radius = side / 2.0 - dot / 2.0 - 1.0
        center_x, center_y = self.width() / 2.0, self.height() / 2.0
        base = self.palette().color(QPalette.ColorRole.Text)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(self.SEGMENTS):
            offset = (index - self._step) % self.SEGMENTS
            fade = 1.0 - offset / self.SEGMENTS  # 头部最亮，往后渐隐
            color = QColor(base)
            color.setAlphaF(0.12 + 0.88 * fade)
            painter.setBrush(color)
            angle = 2.0 * math.pi * index / self.SEGMENTS - math.pi / 2.0
            painter.drawEllipse(
                QPointF(center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)),
                dot / 2.0,
                dot / 2.0,
            )

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 回调命名
        self.stop()
        super().hideEvent(event)


class StartupGate(QWidget):
    """占位界面：一行标题 + 一行说明，居中在一个空白面板上。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = PHASE_INIT
        self.spinner = Spinner(self)
        self.title = QLabel(PHASE_TITLES[PHASE_INIT])
        self.title.setObjectName("panelTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.detail = QLabel("")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.detail.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addStretch()
        layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.detail, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.set_phase(PHASE_INIT)

    @property
    def phase(self) -> str:
        return self._phase

    def set_phase(self, phase: str, detail: str = "") -> None:
        """切换阶段；重复设置同一内容不触发重绘。"""
        phase = phase if phase in PHASE_TITLES else PHASE_INIT
        self._phase = phase
        title = PHASE_TITLES[phase]
        if self.title.text() != title:
            self.title.setText(title)
        text = detail or ""
        if self.detail.text() != text:
            self.detail.setText(text)
        spinning = phase in SPINNER_PHASES
        self.spinner.setVisible(spinning)
        if spinning:
            self.spinner.start()
        else:
            self.spinner.stop()
