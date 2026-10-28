"""跨服战场：以玩家 ID 对比跨服 Boss 排名和本阴司完整成员列表。"""
from __future__ import annotations

import csv
import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from .power_format import format_power

DAY_COLUMNS = [
    ('wed_failures','周三失败次数'),('wed_monsters','周三击败怪群次数'),
    ('wed_players','周三击败玩家次数'),('wed_contribution','周三获取贡献'),
    ('fri_failures','周五失败次数'),('fri_monsters','周五击败怪群次数'),
    ('fri_players','周五击败玩家次数'),('fri_contribution','周五获取贡献')]
MEMBER_COLUMNS = [('status','Boss参与情况'),('id','玩家ID'),('name','名字'),('sName','服务器'),
    ('job','职位'),('fightPower','战力'),*DAY_COLUMNS,
    ('score','周日Boss伤害'),('rank','周日Boss排名'),('boss_bonus','周日预估贡献'),
    ('total_contribution','当前总贡献')]
CSV_COLUMNS = [('id','玩家ID'),('name','名字'),*DAY_COLUMNS,
    ('score','周日Boss伤害'),('rank','周日Boss排名'),('boss_bonus','周日预估贡献'),
    ('total_contribution','当前总贡献'),('contribution','已计贡献'),('contribution_source','贡献口径'),
    ('wed_complete','周三次数完整'),('wed_contribution_complete','周三贡献完整'),
    ('fri_complete','周五次数完整'),('fri_contribution_complete','周五贡献完整')]


def valid_points(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0


class BattlefieldItem(QTableWidgetItem):
    """Order by original numbers even when display text uses 万/亿 or ≥."""
    def __lt__(self,other):
        left=self.data(Qt.ItemDataRole.UserRole)
        right=other.data(Qt.ItemDataRole.UserRole)
        if left is None or right is None:
            if left is None and right is None:return False
            table=self.tableWidget()
            descending=table is not None and table.horizontalHeader().sortIndicatorOrder()==Qt.SortOrder.DescendingOrder
            # Qt reverses this comparison for descending order; keep unknowns last in both directions.
            return left is None if descending else right is None
        def key(item):
            value=item.data(Qt.ItemDataRole.UserRole)
            if value is None:return (2,'')
            if isinstance(value,(int,float)) and not isinstance(value,bool):return (0,value)
            return (1,str(value))
        return key(self)<key(other)


def export_members_csv(path, data, rows):
    """Export the complete roster with exact numeric values, independent of UI filter."""
    def cell(value):
        if isinstance(value,bool):return '是' if value else '否'
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
        for prefix, round_id in (('wed', 2), ('fri', 4)):
            relevant = [log for log in member_logs if log['roundId'] == round_id]
            stats.update({
                prefix+'_failures':sum(log['kind']=='monster' and log.get('isWin') is False for log in relevant),
                prefix+'_monsters':sum(log['kind']=='monster' and log.get('isWin') is True for log in relevant),
                prefix+'_players':sum(log['kind']=='player' and log.get('isWin') is True for log in relevant),
                prefix+'_contribution':sum(log['point'] for log in relevant if valid_points(log.get('point'))),
                prefix+'_complete':bool(data.get('logComplete')) and data.get('logResultsComplete',True)
                    and all(log['kind'] in ('monster','player','boss') and
                        (log['kind']=='boss' or isinstance(log.get('isWin'),bool)) for log in relevant),
                prefix+'_contribution_complete':bool(data.get('logComplete')) and
                    all(valid_points(log.get('point')) for log in relevant)})
        contribution = contributions.get(str(member['id']))
        points = contribution['score'] if contribution else None
        bonus = None
        if rank and rank['rank'] > 0:
            rule = next((r for r in data.get('bossRewardRules', []) if r['from'] <= rank['rank'] <= r['to']), None)
            if rule:bonus=rule['points']
        elif absent:
            bonus=0
        total = (points+bonus if points is not None and bonus is not None else None) if data.get('bossOngoing') else points
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
        self.refresh = QPushButton('拉取成员战报、贡献排名与Boss伤害')
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
        self.table = self.make_table([title for _,title in MEMBER_COLUMNS])
        for column,(key,_) in enumerate(MEMBER_COLUMNS):
            if key in ('status','id','sName','job'):self.table.setColumnHidden(column,True)
        self.table.horizontalHeader().setSortIndicator(
            next(i for i,(key,_) in enumerate(MEMBER_COLUMNS) if key=='total_contribution'),
            Qt.SortOrder.DescendingOrder)
        self.rank_table = self.make_table(['跨服排名', '玩家ID', '名字', '服务器', 'Boss 伤害'])
        self.contribution_table = self.make_table(['贡献排名','玩家ID','名字','贡献'])
        self.log_table = self.make_table(['星期','玩家ID','进攻类型','计入失败次数','目标玩家ID','目标阴司ID','胜负','魂魄','波数','时间戳','成员名字'])
        for i, width in enumerate((190, 110, 150, 100, 80, 110)):
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
            '周三、周五：仅怪群攻击失败计失败；击败怪群／玩家仅统计胜利。每日贡献累加当日战报的魂魄积分。\n' +
            '周日显示Boss最高伤害、排名及排名预估贡献；当前总贡献使用服务端贡献，攻略期另加Boss预估，已结算不重复加。≥表示数据未完整。\n' +
            '未上榜不能直接认定未参与；攻略期贡献缺失或排名奖励不明时，总贡献留空。\n' +
            '；'.join(data.get('notes', [])))
        self.copy.setEnabled(True)
        self.export.setEnabled(True)
        self.fill(self.rank_table, [[r['rank'], r['id'], r.get('name', ''), r.get('sName', ''), r['score']]
                                    for r in data['ranks']],power_columns=(4,))
        self.fill(self.contribution_table, [[r['rank'],r['id'],r.get('name',''),r['score']]
            for r in data.get('contributions') or []])
        labels = {'monster':'怪群','player':'其他阴司玩家','boss':'Boss','unknown':'未知'}
        member_names={str(m['id']):m.get('name','') for m in data['members']}
        weekdays=dict(enumerate(('周一','周二','周三','周四','周五','周六','周日')))
        self.fill(self.log_table, [[weekdays.get(r['roundId'],str(r['roundId'])),r['roleId'],labels.get(r['kind'],'未知'),
            1 if r['kind']=='monster' and r.get('isWin') is False else 0,
            r['targetRoleId'],r['targetLegionId'],'胜' if r.get('isWin') is True else '负' if r.get('isWin') is False else '未知',
            r.get('point'),r.get('wave'),r.get('timeAt'),member_names.get(str(r['roleId']), '非当前成员')]
            for r in data.get('logs', [])])
        self.render()

    @staticmethod
    def fill(table, values, power_columns=(), lower_bound_cells=()):
        table.setSortingEnabled(False)
        table.setRowCount(len(values))
        for i, row in enumerate(values):
            for j, value in enumerate(row):
                item = BattlefieldItem(format_power(value) if j in power_columns else '—' if value is None else str(value))
                item.setToolTip('—' if value is None else str(value))
                if (i,j) in lower_bound_cells:
                    item.setText('≥'+str(value))
                    item.setToolTip('已读取战报中的数值；数据未完整，此数值仅为下限')
                raw=int(value) if isinstance(value,str) and value.isascii() and value.isdigit() else value
                item.setData(Qt.ItemDataRole.UserRole, raw)
                table.setItem(i, j, item)
        table.setSortingEnabled(True)

    def render(self):
        from .legion import JOBS
        mode = self.filter.currentIndex()
        rows = [r for r in self.rows if mode == 1 or r['participated'] == (mode == 2)]
        values=[];lower=set()
        for i,row in enumerate(rows):
            values.append([JOBS.get(row.get(key),'—') if key=='job' else
                (row.get(key) or None) if key=='rank' else row.get(key) for key,_ in MEMBER_COLUMNS])
            for j,(key,_) in enumerate(MEMBER_COLUMNS):
                for prefix in ('wed','fri'):
                    if key.startswith(prefix+'_'):
                        complete=prefix+'_contribution_complete' if key==prefix+'_contribution' else prefix+'_complete'
                        if not row[complete]:lower.add((i,j))
        self.fill(self.table,values,power_columns=(5,14),lower_bound_cells=lower)


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
