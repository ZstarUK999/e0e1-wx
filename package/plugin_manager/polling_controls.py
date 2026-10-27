"""Explicit opt-in controls for optional background work."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox

DEFAULTS = dict(legion_poll=False, auction_poll=False, desire_poll=False,
                memory_poll=False, blank_recovery=True, automation_overlay=False, legion_scan_enabled=False)


def add_switch(panel, store, key, label):
    box = QCheckBox(label)
    box.setObjectName('ui.' + key)
    panel.layout().insertWidget(1, box)
    setattr(panel, key, box)
    def sync(state):
        blocker = QSignalBlocker(box)
        box.setChecked(state['ui'][key])
        del blocker
    def changed(value):
        try:
            store.set_ui_flag(key, value)
        except (OSError, ValueError) as exc:
            sync(store.snapshot())
            box.setToolTip('保存失败：' + str(exc))
    box.toggled.connect(changed)
    store.changed.connect(sync)
    sync(store.snapshot())


def install_switches(pages, store):
    for page, key, label in (
        ('legion', 'legion_poll', '自动读取当前阴司（关闭后仍可手动查询）'),
        ('auction', 'auction_poll', '启用拍卖助手与自动读取（关闭即停止购买）'),
        ('desire', 'desire_poll', '自动读取三尸库存（关闭后仍可手动操作）'),
        ('debug', 'memory_poll', '定期采集运行内存诊断（每5分钟）'),
        ('global', 'blank_recovery', '检测持续白屏／黑屏或无响应并自动重开（仅微信）'),
        ('daily', 'automation_overlay', '同步游戏内托管状态与浮层（关闭后停止同步及浮层定时器）'),
    ):
        if page in pages:
            add_switch(pages[page], store, key, label)
    if 'legion' in pages:
        add_switch(pages['legion'].scan, store, 'legion_scan_enabled', '启用区段扫描及成员自动更新（关闭即暂停，保留断点）')
