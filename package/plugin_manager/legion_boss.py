"""跨服战场：以玩家 ID 对比跨服 Boss 排名和本阴司完整成员列表。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

from .power_format import format_power


def compare_members(data):
    ranks = {str(row['id']): row for row in data['ranks']}
    me = data.get('me')
    if me and (me.get('score', 0) > 0 or me.get('rank', 0) > 0):
        ranks.setdefault(str(data['roleId']), me)
    result = []
    for member in data['members']:
        rank = ranks.get(str(member['id']))
        score = rank.get('score') if rank else None
        if str(member['id']) == str(data['roleId']) and data.get('selfDamage') is not None:
            score = max(score or 0, data['selfDamage'])
        participated = bool(rank and rank.get('rank', 0) > 0 or score is not None and score > 0)
        # Only the current character has a direct damage record outside the top list.
        absent = not participated and str(member['id']) == str(data['roleId']) and score == 0
        result.append({**member, 'rank': rank.get('rank') if rank else None,
                       'score': score, 'participated': participated,
                       'status': '已参与' if participated else '未参与（本人伤害为 0）' if absent else '未上榜（待确认）'})
    return sorted(result, key=lambda row: (row['participated'], row['rank'] or 10**9, str(row['id'])))


class LegionBossPanel(QWidget):
    requested = Signal()

    def __init__(self):
        super().__init__()
        self.data = None
        self.rows = []
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.refresh = QPushButton('拉取跨服 Boss 排名并对比本阴司')
        self.refresh.clicked.connect(self.requested.emit)
        top.addWidget(self.refresh)
        self.filter = QComboBox()
        self.filter.addItems(['未参与 / 未上榜', '全部成员', '已参与'])
        self.filter.currentIndexChanged.connect(self.render)
        top.addWidget(self.filter)
        self.copy = QPushButton('复制未参与 / 未上榜名单')
        self.copy.setEnabled(False)
        self.copy.clicked.connect(self.copy_missing)
        top.addWidget(self.copy)
        top.addStretch()
        layout.addLayout(top)
        self.summary = QLabel('点击拉取，自动使用当前角色所属阴司的完整成员名单。')
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.message = QLabel('按玩家 ID 对比。榜单可能只保留前列，未上榜成员需要进一步确认是否参与。')
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.message)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        self.table = self.make_table(['参与情况', '玩家ID', '名字', '服务器', '职位', '战力', '跨服排名', 'Boss 伤害'])
        self.rank_table = self.make_table(['跨服排名', '玩家ID', '名字', '服务器', 'Boss 伤害'])
        for i, width in enumerate((190, 110, 150, 100, 80, 110, 90, 140)):
            self.table.setColumnWidth(i, width)
        for i, width in enumerate((100, 110, 180, 120, 160)):
            self.rank_table.setColumnWidth(i, width)
        tabs.addTab(self.table, '本阴司成员参与')
        tabs.addTab(self.rank_table, '跨服 Boss 排名')

    @staticmethod
    def make_table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().hide()
        return table

    def accept(self, data):
        rows = compare_members(data)
        self.data, self.rows = data, rows
        count = sum(row['participated'] for row in rows)
        self.summary.setText(
            f"{data['legionName']} · 阴司 ID {data['legionId']} · 当前角色 {data['roleId']}\n"
            f"{data['bossName']} · 战场 {data.get('bfId', '—')} · 成员 {len(rows)} 人 · "
            f"已确认参与 {count} 人 · 未参与 / 未上榜 {len(rows)-count} 人")
        self.message.setText(
            f"本次读取 {len(data['ranks'])} 条跨服排名（最多 {data['rankLimit']} 条）· 更新时间 {data['fetchedAt']}\n"
            '未上榜不代表未打 Boss：服务端可能只保留前列。仅本人可通过伤害记录确认未参与；其他成员标为待确认。')
        self.copy.setEnabled(True)
        self.fill(self.rank_table, [[r['rank'], r['id'], r.get('name', ''), r.get('sName', ''), r['score']]
                                    for r in data['ranks']])
        self.render()

    @staticmethod
    def fill(table, values, power_columns=()):
        from .legion import NumericItem
        table.setSortingEnabled(False)
        table.setRowCount(len(values))
        for i, row in enumerate(values):
            for j, value in enumerate(row):
                item = NumericItem(format_power(value) if j in power_columns else '—' if value is None else str(value))
                item.setToolTip('—' if value is None else str(value))
                if isinstance(value, (int, float)):
                    item.setData(Qt.ItemDataRole.UserRole, value)
                table.setItem(i, j, item)
        table.setSortingEnabled(True)

    def render(self):
        from .legion import JOBS
        mode = self.filter.currentIndex()
        rows = [r for r in self.rows if mode == 1 or r['participated'] == (mode == 2)]
        self.fill(self.table, [[r['status'], r['id'], r.get('name', ''), r.get('sName', ''),
                              JOBS.get(r.get('job'), '—'), r.get('fightPower'),
                              r['rank'] or None, r['score']] for r in rows], power_columns=(5,))

    def copy_missing(self):
        if self.data is None:
            return
        lines = [f"{self.data['legionName']} · 跨服 Boss 未参与 / 未上榜名单",
                 '未上榜仅表示本次排名未找到，不能据此确认未参与。']
        lines.extend(f"{r.get('name', '')}（{r['id']}）· {r['status']}" for r in self.rows if not r['participated'])
        QApplication.clipboard().setText('\n'.join(lines))
