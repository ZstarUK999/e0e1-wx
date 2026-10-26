"""本阴司血月战绩与 CSV 导出。"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget)

COLUMNS = [('rank', '积分排名'), ('id', '玩家ID'), ('name', '名字'), ('sName', '服务器'),
           ('killRoleNum', '杀敌次数'), ('killGuardNum', '攻城次数'), ('score', '总积分'), ('dieNum', '死亡次数')]


def ranked_rows(rows):
    ordered = sorted(rows, key=lambda r: (r.get('score') is None, -(r.get('score') or 0), int(r['id'])))
    return [dict(row, rank=i+1 if row.get('score') is not None else None) for i, row in enumerate(ordered)]


def export_statistics(path, data):
    # BOM lets Excel open Chinese CSV without choosing an encoding.
    def safe(value):
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value
        return '' if value is None else value
    with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['战场ID', '战场名称', '阴司ID', '查询时间'] + [label for _, label in COLUMNS])
        for row in ranked_rows(data['rows']):
            writer.writerow([safe(data.get(k)) for k in ('warId', 'name', 'legionId', 'fetchedAt')]
                            + [safe(row.get(k)) for k, _ in COLUMNS])


class LegionBloodmoonPanel(QWidget):
    requested = Signal(str, dict)

    def __init__(self, cache_path=None):
        super().__init__()
        self.data = None
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache = {'accounts': {}, 'selected': None}
        self.account = None
        if self.cache_path:
            try:
                saved = json.loads(self.cache_path.read_text(encoding='utf-8'))
                if isinstance(saved, dict) and isinstance(saved.get('accounts'), dict):
                    self.cache = saved
            except (OSError, ValueError):
                pass
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.history = QPushButton('刷新血月战场列表')
        self.selector = QComboBox()
        self.selector.setMinimumWidth(280)
        self.fetch = QPushButton('查看统计')
        self.refresh = QPushButton('重新拉取本场')
        self.refresh.setEnabled(False)
        self.export = QPushButton('导出 CSV')
        self.export.setEnabled(False)
        self.fetch.setEnabled(False)
        top.addWidget(self.history)
        top.addWidget(self.selector, 1)
        top.addWidget(self.fetch)
        top.addWidget(self.refresh)
        top.addWidget(self.export)
        layout.addLayout(top)
        self.summary = QLabel('选择某次血月战场，查看该场本阴司成员战绩。')
        self.message = QLabel('按总积分降序排名；死亡次数使用游戏服务端统计。')
        for label in (self.summary, self.message):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([title for _, title in COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.history.clicked.connect(lambda: self.requested.emit('history', {}))
        self.fetch.clicked.connect(self.request_statistics)
        self.selector.currentIndexChanged.connect(self.select_war)
        self.refresh.clicked.connect(lambda: self.request_statistics(force=True))
        self.export.clicked.connect(self.export_csv)
        selected = self.cache.get('selected')
        if selected in self.cache['accounts']:
            try:
                self.account = selected
                self.populate()
            except (KeyError, TypeError, ValueError):
                self.account = None
                self.selector.clear()
                self.clear()

    def save_cache(self):
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.cache_path.parent, prefix=self.cache_path.name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(self.cache, stream, ensure_ascii=False, allow_nan=False)
            os.replace(temporary, self.cache_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def populate(self):
        previous = self.selector.currentData() or {}
        bucket = self.cache['accounts'][self.account]
        self.selector.blockSignals(True)
        self.selector.clear()
        for war in bucket['wars'].values():
            cached = str(war['warId']) in bucket['results']
            self.selector.addItem(f"S{war.get('seasonId', 0)} · {war['name']} · {war['warId']}" + ('（已缓存）' if cached else ''), war)
        index = next((i for i in range(self.selector.count())
                      if self.selector.itemData(i)['warId'] == previous.get('warId')), 0)
        self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)
        self.select_war()
        self.busy(False)

    def select_war(self, *_):
        self.clear()
        war = self.selector.currentData()
        bucket = self.cache['accounts'].get(self.account, {})
        cached = bucket.get('results', {}).get(str(war['warId'])) if war else None
        if cached:
            self.accept(cached, save=False)
        else:
            self.message.setText('本场尚无缓存，点击查看统计首次拉取。')

    def clear(self, *_):
        self.data = None
        self.table.setRowCount(0)
        self.export.setEnabled(False)
        self.summary.setText('选择的战场已变更，请拉取成员统计。')

    def busy(self, value):
        self.history.setEnabled(not value)
        self.selector.setEnabled(not value)
        self.fetch.setEnabled(not value and self.selector.count() > 0)
        self.refresh.setEnabled(not value and self.selector.count() > 0)

    def accept_history(self, data):
        self.account = data.get('account', 'unknown')
        bucket = self.cache['accounts'].setdefault(self.account, {'wars': {}, 'results': {}})
        for war in data['rows']:
            bucket['wars'][str(war['warId'])] = war
        self.cache['selected'] = self.account
        self.save_cache()
        self.populate()

    def request_statistics(self, _checked=False, *, force=False):
        war = self.selector.currentData()
        if war:
            cached = self.cache['accounts'].get(self.account, {}).get('results', {}).get(str(war['warId']))
            if cached and not force:
                self.accept(cached, save=False)
                return
            self.requested.emit('statistics', dict(war, cacheAccount=self.account))

    def accept(self, data, *, save=True):
        war = self.selector.currentData()
        if not war or war['warId'] != data['warId']:
            return
        if data.get('cacheAccount', self.account) != self.account:
            return
        from .legion import NumericItem
        self.data = data
        rows = ranked_rows(data['rows'])
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, (key, _) in enumerate(COLUMNS):
                value = row.get(key)
                item = NumericItem('—' if value is None else str(value))
                item.setData(Qt.ItemDataRole.UserRole, value)
                self.table.setItem(i, j, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.summary.setText(f"{data['name']} · 战场 {data['warId']} · 阴司 {data['legionId']} · 战绩成员 {len(rows)} 人\n查询时间：{data['fetchedAt']}")
        self.message.setText(('已显示本地缓存；需要更新请点击“重新拉取本场”。\n' if not save else '查询结果已缓存。\n') + data['note'])
        self.export.setEnabled(True)
        if save and self.account:
            self.cache['accounts'][self.account]['results'][str(data['warId'])] = data
            try:
                self.save_cache()
            except (OSError, ValueError) as exc:
                self.message.setText(f'统计已显示，但缓存保存失败：{exc}')

    def export_csv(self):
        if self.data is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出血月统计',
            f"血月统计_{datetime.now():%Y%m%d_%H%M%S}.csv", 'CSV 文件 (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            export_statistics(path, self.data)
            self.message.setText(f'已导出：{path}')
        except (OSError, ValueError) as exc:
            self.message.setText(f'导出失败：{exc}')
