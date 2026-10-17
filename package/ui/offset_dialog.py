"""偏移自动检测期间的独占提示窗口（主工具与插件管理器共用）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget


class OffsetAdaptingDialog(QDialog):
    """自动重算调试偏移期间挡住界面，避免用户在适配过程中操作或关掉微信。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("正在适配")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)
        title = QLabel("检测到小程序有热更新，正在适配中")
        title.setWordWrap(True)
        layout.addWidget(title)
        note = QLabel("正在重新计算调试偏移，通常几十秒内完成。\n期间不要关闭微信或在界面上操作。")
        note.setWordWrap(True)
        layout.addWidget(note)


class OffsetDialogController:
    """按 offset_detect 状态开/关独占窗口，挂在任意 QWidget/QMainWindow 上。"""

    def __init__(self, parent: QWidget):
        self.parent = parent
        self.dialog: OffsetAdaptingDialog | None = None

    def set_active(self, active: bool) -> None:
        if active:
            if self.dialog is None:
                self.dialog = OffsetAdaptingDialog(self.parent)
            if not self.dialog.isVisible():
                self.dialog.open()  # 模态但不嵌套事件循环
            return
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
