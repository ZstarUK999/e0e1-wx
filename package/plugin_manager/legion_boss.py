"""跨服战场：以玩家 ID 对比跨服 Boss 排名和本阴司完整成员列表。"""
from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTabWidget,
    QVBoxLayout, QWidget,
)

from .power_format import format_power

CSV_COLUMNS = [('id','玩家ID'),('name','名字'),('sName','服务器'),
    ('tue_monsters','周二怪群进攻'),('tue_players','周二来犯玩家进攻'),('tue_attacks','周二折算次数'),
    ('thu_monsters','周四怪群进攻'),('thu_players','周四来犯玩家进攻'),('thu_attacks','周四折算次数'),
    ('status','Boss参与情况'),('score','Boss伤害'),('rank','Boss排名'),
    ('contribution_rank','贡献排名'),('contribution','已计贡献'),
    ('boss_bonus','Boss排名预估贡献'),('total_contribution','当前总贡献'),('contribution_source','贡献口径')]


def export_members_csv(path, data, rows):
    """Export the complete roster with exact numeric values, independent of UI filter."""
    def cell(value):
        if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
            return "'" + value
        return '' if value is None else value
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow([title for _, title in CSV_COLUMNS] + ['战场ID','日志完整','日志已读','日志总数','快照时间'])
        for row in rows:
            writer.writerow([cell(row.get(key)) for key, _ in CSV_COLUMNS] +
                [cell(data.get('bfId')), '是' if data.get('logComplete') else '否',
                 len(data.get('logs', [])), data.get('logTotal'), data.get('fetchedAt')])


def compare_members(data):
    ranks = {str(row['id']): row for row in data['ranks']}
    me = data.get('me')
    if me and (me.get('score', 0) > 0 or me.get('rank', 0) > 0):
        ranks.setdefault(str(data['roleId']), me)
    result = []
    contributions = {str(r['id']): r for r in data.get('contributions') or []}
    logs_by_member = {}
    for log in data.get('logs', []):
        logs_by_member.setdefault(str(log['roleId']), []).append(log)
    for member in data['members']:
        rank = ranks.get(str(member['id']))
        score = rank.get('score') if rank else None
        if str(member['id']) == str(data['roleId']) and data.get('selfDamage') is not None:
            score = max(score or 0, data['selfDamage'])
        boss_state = data.get('memberBoss', {}).get(str(member['id']))
        if boss_state is not None:
            score = max(score or 0, boss_state['damage'])
        member_logs = logs_by_member.get(str(member['id']), [])
        boss_logged = any(log['kind'] == 'boss' for log in member_logs)
        participated = bool(rank and rank.get('rank', 0) > 0 or score is not None and score > 0)
        participated = participated or boss_logged or bool(boss_state and boss_state.get('count', 0) > 0)
        # Only the current character has a direct damage record outside the top list.
        absent = not participated and (str(member['id']) == str(data['roleId']) and score == 0 or
            boss_state is not None and boss_state.get('count') == 0 and boss_state['damage'] == 0)
        stats = {}
        for prefix, round_id in (('tue', 1), ('thu', 3)):
            relevant = [log for log in member_logs if log['roundId'] == round_id]
            monsters = sum(log['kind'] == 'monster' for log in relevant)
            players = sum(log['kind'] == 'player' for log in relevant)
            stats.update({prefix+'_monsters': monsters, prefix+'_players': players,
                          prefix+'_attacks': monsters + 2 * players})
        contribution = contributions.get(str(member['id']))
        points = contribution['score'] if contribution else None
        bonus = 0 if not data.get('bossOngoing') else None
        if data.get('bossOngoing') and rank and rank['rank'] > 0:
            rule = next((r for r in data.get('bossRewardRules', []) if r['from'] <= rank['rank'] <= r['to']), None)
            if rule: bonus = rule['points']
        elif data.get('bossOngoing') and absent:
            bonus = 0
        total = points + bonus if points is not None and bonus is not None else None
        result.append({**member, 'rank': rank.get('rank') if rank else None,
                       **stats, 'contribution_rank': contribution.get('rank') if contribution else None,
                       'contribution': points, 'boss_bonus': bonus, 'total_contribution': total,
                       'contribution_source': '贡献榜＋当前Boss排名预估（未结算）' if data.get('bossOngoing') else '服务端贡献榜',
                       'score': score, 'participated': participated,
                       'status': '已参与' if participated else '未参与（本人伤害为 0）' if absent and str(member['id']) == str(data['roleId']) else '未参与（次数与伤害为0）' if absent else '未上榜（待确认）'})
    return sorted(result, key=lambda row: (row['participated'], row['rank'] or 10**9, str(row['id'])))


class LegionBossPanel(QWidget):
    requested = Signal()

    def __init__(self):
        super().__init__()
        self.data = None
        self.rows = []
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.refresh = QPushButton('拉取贡献排名、战场日志与Boss伤害')
        self.refresh.clicked.connect(self.requested.emit)
        top.addWidget(self.refresh)
        self.filter = QComboBox()
        self.filter.addItems(['未参与 / 未上榜', '全部成员', '已参与'])
        self.filter.setCurrentIndex(1)
        self.filter.currentIndexChanged.connect(self.render)
        top.addWidget(self.filter)
        self.copy = QPushButton('复制未参与 / 未上榜名单')
        self.copy.setEnabled(False)
        self.copy.clicked.connect(self.copy_missing)
        top.addWidget(self.copy)
        self.export = QPushButton('导出全部成员CSV')
        self.export.setEnabled(False)
        self.export.clicked.connect(self.export_csv)
        top.addWidget(self.export)
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
        self.table = self.make_table(['参与情况', '玩家ID', '名字', '服务器', '职位', '战力', 'Boss排名', 'Boss伤害',
            '周二怪群', '周二玩家', '周二折算次数', '周四怪群', '周四玩家', '周四折算次数',
            '贡献排名', '已计贡献', 'Boss预估贡献', '当前总贡献'])
        self.rank_table = self.make_table(['跨服排名', '玩家ID', '名字', '服务器', 'Boss 伤害'])
        self.contribution_table = self.make_table(['贡献排名','玩家ID','名字','贡献'])
        self.log_table = self.make_table(['星期','玩家ID','进攻类型','折算次数','目标玩家ID','目标阴司ID','胜负','魂魄','波数','时间戳'])
        for i, width in enumerate((190, 110, 150, 100, 80, 110, 90, 140)):
            self.table.setColumnWidth(i, width)
        for i, width in enumerate((100, 110, 180, 120, 160)):
            self.rank_table.setColumnWidth(i, width)
        tabs.addTab(self.table, '本阴司成员参与')
        tabs.addTab(self.rank_table, '跨服 Boss 排名')
        tabs.addTab(self.contribution_table, '贡献排名')
        tabs.addTab(self.log_table, '战场日志')

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
            f"日志{len(data.get('logs', []))}/{data.get('logTotal', '未知')}条 · {'完整' if data.get('logComplete') else '未确认完整，次数仅为已读记录下限'}\n"
            '来犯玩家进攻×2，怪群进攻×1（含胜负）；周二roundId=1，周四roundId=3。Boss攻略中总贡献为贡献榜＋当前Boss排名积分预估。\n' +
            '未上榜不能直接认定未参与；贡献缺失或排名奖励不明时，总贡献留空。\n' +
            '；'.join(data.get('notes', [])))
        self.copy.setEnabled(True)
        self.export.setEnabled(True)
        self.fill(self.rank_table, [[r['rank'], r['id'], r.get('name', ''), r.get('sName', ''), r['score']]
                                    for r in data['ranks']])
        self.fill(self.contribution_table, [[r['rank'],r['id'],r.get('name',''),r['score']]
            for r in data.get('contributions') or []])
        labels = {'monster':'怪群','player':'来犯玩家','boss':'Boss','unknown':'未知'}
        self.fill(self.log_table, [[f"周{r['roundId']+1}",r['roleId'],labels.get(r['kind'],'未知'),
            2 if r['kind']=='player' else 1 if r['kind']=='monster' else 0,
            r['targetRoleId'],r['targetLegionId'],'胜' if r['isWin'] else '负',r['point'],r['wave'],r['timeAt']]
            for r in data.get('logs', [])])
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
                              r['rank'] or None, r['score'],
                              *[r[k] for k in ('tue_monsters','tue_players','tue_attacks','thu_monsters','thu_players','thu_attacks',
                                  'contribution_rank','contribution','boss_bonus','total_contribution')]] for r in rows], power_columns=(5,))

    def export_csv(self):
        if not self.data: return
        path, _ = QFileDialog.getSaveFileName(self, '导出跨服战场成员统计', '跨服战场成员统计.csv', 'CSV (*.csv)')
        if path:
            try:
                export_members_csv(path, self.data, self.rows)
                self.message.setText(f'已导出全部{len(self.rows)}名成员：{path}')
            except OSError as exc:
                self.message.setText(f'导出失败：{exc}')

    def copy_missing(self):
        if self.data is None:
            return
        lines = [f"{self.data['legionName']} · 跨服 Boss 未参与 / 未上榜名单",
                 '未上榜仅表示本次排名未找到，不能据此确认未参与。']
        lines.extend(f"{r.get('name', '')}（{r['id']}）· {r['status']}" for r in self.rows if not r['participated'])
        QApplication.clipboard().setText('\n'.join(lines))
