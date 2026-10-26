"""战旗升级：读取当前角色并在本地编辑逐日预测。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import os
import tempfile
from datetime import date, timedelta

from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDateEdit, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget)

from .flag_upgrade_model import bj_date, defaults, forecast, amounts, WOOD, CLOTH, GOLD

LOG = logging.getLogger('plugin_manager')


class FlagUpgradePanel(QWidget):
    requested = Signal()

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.snapshot = None
        self.result = None
        self._loading = False
        self._ready = False
        self._busy = False
        self._saved_days = {}
        self.path = store.path.with_name('flag-upgrade-plans.json')
        self.saved = {}
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw, dict): self.saved = raw
        except (OSError, ValueError): pass
        layout = QVBoxLayout(self)
        heading = QLabel('战旗升级')
        heading.setObjectName('panelTitle')
        layout.addWidget(heading)
        top = QHBoxLayout()
        self.pull = QPushButton('拉取玩家进度并生成预测')
        self.pull.setEnabled(False)
        self.pull.clicked.connect(self.requested.emit)
        top.addWidget(self.pull)
        self.calculate = QPushButton('按当前计划重新计算')
        self.calculate.setEnabled(False)
        self.calculate.clicked.connect(self.recalculate)
        top.addWidget(self.calculate)
        self.reset = QPushButton('恢复自动计划')
        self.reset.setEnabled(False)
        self.reset.clicked.connect(self.reset_plan)
        top.addWidget(self.reset)
        top.addStretch()
        layout.addLayout(top)
        self.identity = QLabel('连接游戏后，点击拉取当前角色与赛季数据。')
        self.identity.setTextFormat(Qt.TextFormat.PlainText)
        self.identity.setWordWrap(True)
        layout.addWidget(self.identity)
        self.message = QLabel('只读取游戏数据；修改计划只影响预测。所有日期按北京时间计算。')
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        split = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(split, 1)
        settings = QGroupBox('完美完成计划 · 调整后点击重新计算')
        form = QGridLayout(settings)
        self.end = QDateEdit()
        self.end.setCalendarPopup(True)
        self.end.setDisplayFormat('yyyy-MM-dd')
        self.sweeps = self.spin(0, 6)
        self.star_rate = self.spin(0, 120)
        self.star_target = self.spin(0, 120)
        self.bp_level = self.spin(0, 80)
        self.bp_exp = self.spin(0, 100000)
        self.shop = self.spin(0, 100000)
        self.gifts = self.spin(0, 1000)
        self.cloth = self.spin(0, 100000000)
        self.gold = self.spin(0, 1000000000)
        pairs = [('截止日期', self.end), ('每日扫荡总次数', self.sweeps),
                 ('每日新增深渊星数', self.star_rate), ('深渊推进上限星数', self.star_target),
                 ('战令起始等级（可假设）', self.bp_level), ('战令当前级经验', self.bp_exp),
                 ('每周新增兑换木头', self.shop), ('从现在起购买礼包总数', self.gifts),
                 ('其他来源每日镇旗布', self.cloth), ('其他来源每日铜钱', self.gold)]
        for i, (label, control) in enumerate(pairs):
            form.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            form.addWidget(control, i // 2, (i % 2) * 2 + 1)
        self.today = QCheckBox('继续安排今天剩余扫荡和推星（已完成扫荡自动扣除）')
        self.mid = QCheckBox('解锁进阶战令')
        self.best = QCheckBox('解锁最高档战令')
        self.recharge = QCheckBox('每周完成充值30元任务（仅假设，不执行充值）')
        checks = QHBoxLayout()
        for control in (self.mid, self.best, self.recharge): checks.addWidget(control)
        form.addLayout(checks, 5, 0, 1, 4)
        form.addWidget(self.today, 6, 0, 1, 4)
        form.addWidget(QLabel('每日直接计算木头可达到的最高等级；镇旗布、铜钱视为充足。'), 7, 0, 1, 4)
        split.addWidget(settings)
        content = QWidget()
        lower = QVBoxLayout(content)
        lower.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel('')
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setStyleSheet('font-size: 15px; font-weight: 600;')
        lower.addWidget(self.summary)
        self.tabs = QTabWidget()
        lower.addWidget(self.tabs, 1)
        self.daily = self.table(['北京时间', '深渊星数', '扫荡', '首通木头', '扫荡木头', '战令木头',
            '商店木头', '礼包木头', '升级后剩余木头', '木头可达最高等级', '战令等级 / 经验', '当日经验', '事件'])
        self.milestones = self.table(['达到日期', '战旗等级', '突破木头', '解锁技能节点（仍需祭旗铃升阶）'])
        self.current = QPlainTextEdit()
        self.current.setReadOnly(True)
        self.task_table = self.table(['任务', '周期', '当前状态', '当前进度', '经验', '预计完成日（自动 / 不计 / yyyy-MM-dd）'], editable=True)
        self.schedule = self.table(['日期', '扫荡总次数', '新增星数', '战令达到等级（自动 / 数字）', '本周新增兑换木头', '当日礼包数'], editable=True)
        for widget, title in ((self.daily, '逐日预测'), (self.milestones, '战旗解锁'),
                              (self.current, '拉取快照与材料'), (self.task_table, '战令任务'),
                              (self.schedule, '逐日调整')):
            self.tabs.addTab(widget, title)
        self.notes = QLabel('')
        self.notes.setWordWrap(True)
        self.notes.setTextFormat(Qt.TextFormat.PlainText)
        lower.addWidget(self.notes)
        split.addWidget(content)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([265, 400])
        self.end.dateChanged.connect(self._resize_schedule)

    @staticmethod
    def spin(low, high):
        control = QSpinBox()
        control.setRange(low, high)
        return control

    @staticmethod
    def table(headers, editable=False):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        if not editable: table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def set_ready(self, ready):
        self._ready = bool(ready)
        self.pull.setEnabled(self._ready and not self._busy)

    def set_busy(self, busy):
        self._busy = bool(busy)
        self.pull.setEnabled(self._ready and not self._busy)

    def clear_session(self):
        self.set_ready(False)
        self.snapshot = self.result = None
        self.calculate.setEnabled(False)
        self.reset.setEnabled(False)
        self.identity.setText('会话已断开，请连接后重新拉取当前角色。')
        self.summary.clear()
        self.current.clear()
        for table in (self.daily, self.milestones, self.task_table, self.schedule): table.setRowCount(0)
        self.notes.clear()

    def accept(self, snapshot):
        self.snapshot = deepcopy(snapshot)
        self.key = str(snapshot.get('platform', '')) + ':' + snapshot['roleId'] + ':' + str(snapshot['season']['id'])
        plan = {**defaults(snapshot), **self.saved.get(self.key, {})}
        self.load_plan(plan)
        self.calculate.setEnabled(True)
        self.reset.setEnabled(True)
        self.recalculate()

    def load_plan(self, p):
        self._loading = True
        self.schedule.setRowCount(0)
        s = self.snapshot
        self.end.setMinimumDate(QDate.fromString(bj_date(s['asOf']).isoformat(), 'yyyy-MM-dd'))
        self.end.setMaximumDate(QDate.fromString(bj_date(s['season']['end']).isoformat(), 'yyyy-MM-dd'))
        self.end.setDate(QDate.fromString(p['end'], 'yyyy-MM-dd'))
        self.sweeps.setMaximum(s['freeSweeps'] + len(s['paidSweepCosts']))
        self.sweeps.setValue(p['sweeps'])
        self.star_rate.setValue(p['stars_per_day'])
        self.star_target.setMaximum(sum(len(r['rewards']) for r in s['stages']))
        self.star_target.setValue(p['target_stars'])
        self.bp_level.setMaximum(max(r['level'] for r in s['bp']['levels']))
        # Always refresh the opening balance. Saved plans must not replace a
        # new character snapshot with an earlier level/experience balance.
        self.bp_level.setValue(s['bp']['level'])
        self.bp_exp.setValue(s['bp']['exp'])
        self.shop.setValue(p['weekly_shop_wood'])
        self.gifts.setValue(p['gift_total'])
        self.cloth.setValue(p['extra_cloth'])
        self.gold.setValue(p['extra_gold'])
        self.today.setChecked(p['include_today'])
        self.mid.setChecked(p['active_tracks'][1] or s['bp']['active'][1])
        self.best.setChecked(p['active_tracks'][2] or s['bp']['active'][2])
        self.recharge.setChecked(p['weekly_recharge'])
        self._saved_days = deepcopy(p['days'])
        self.fill_tasks(p['tasks'])
        self._loading = False
        self._resize_schedule()

    def fill_tasks(self, edited):
        self.task_table.setRowCount(len(self.snapshot['tasks']))
        states = {0: '未完成', 1: '已完成待领经验', 2: '已领取经验'}
        for i, t in enumerate(self.snapshot['tasks']):
            self.put(self.task_table, i, [t['name'], {'daily': '每日', 'weekly': '每周', 'season': '赛季'}[t['kind']],
                states.get(t['state'], str(t['state'])), f"{t['progress']}/{t['target']}", t['score'],
                edited.get(str(t['id']), '自动').replace('skip', '不计')], editable=(5,))

    @staticmethod
    def put(table, row, values, editable=()):
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            if col not in editable: item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, col, item)

    def read_days(self):
        days = {}
        fields = ('sweeps', 'stars', 'bp', 'shop', 'gifts')
        for i in range(self.schedule.rowCount()):
            day = self.schedule.item(i, 0).text()
            row = {}
            for j, key in enumerate(fields, 1):
                text = self.schedule.item(i, j).text().strip()
                if text and text != '自动':
                    num = int(text)
                    if num < 0: raise ValueError('逐日调整不能填写负数')
                    row[key] = num
            if row: days[day] = row
        return days

    def _resize_schedule(self):
        if self._loading or not self.snapshot: return
        try: previous = self.read_days()
        except ValueError: previous = {}
        self._saved_days.update(previous)
        today = bj_date(self.snapshot['asOf'])
        end = date.fromisoformat(self.end.date().toString('yyyy-MM-dd'))
        days = max(0, (end - today).days + 1)
        self.schedule.setRowCount(days)
        for i in range(days):
            day = (today + timedelta(days=i)).isoformat()
            row = self._saved_days.get(day, {})
            self.put(self.schedule, i, [day, *[row.get(k, '自动') for k in ('sweeps', 'stars', 'bp', 'shop', 'gifts')]], editable=range(1, 6))

    def plan(self):
        edited = {}
        for i, t in enumerate(self.snapshot['tasks']):
            text = self.task_table.item(i, 5).text().strip()
            if text in ('', '自动'): continue
            if text == '不计': edited[str(t['id'])] = 'skip'
            else:
                date.fromisoformat(text)
                edited[str(t['id'])] = text
        return {'end': self.end.date().toString('yyyy-MM-dd'), 'sweeps': self.sweeps.value(),
            'stars_per_day': self.star_rate.value(), 'target_stars': self.star_target.value(),
            'include_today': self.today.isChecked(), 'wood_only': True,
            'weekly_shop_wood': self.shop.value(), 'gift_total': self.gifts.value(),
            'weekly_recharge': self.recharge.isChecked(), 'extra_cloth': self.cloth.value(),
            'extra_gold': self.gold.value(), 'active_tracks': [True, self.mid.isChecked(), self.best.isChecked()],
            'days': self.read_days(), 'tasks': edited}

    def recalculate(self):
        if not self.snapshot: return
        try:
            p = self.plan()
            s = deepcopy(self.snapshot)
            s['bp']['level'], s['bp']['exp'] = self.bp_level.value(), self.bp_exp.value()
            self.result = result = forecast(s, p)
            self.render(s, result)
            self.saved[self.key] = p
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.path.parent, suffix='.flag-plan.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(self.saved, f, ensure_ascii=False, allow_nan=False)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            self.message.setText('预测已更新，计划按平台、角色和赛季保存。扫荡按先推星再扫荡计算；购买、兑换只作计划。')
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.message.setText(f'无法生成预测：{exc}')

    def reset_plan(self):
        if self.snapshot:
            self._saved_days = {}
            self.schedule.setRowCount(0)
            self.load_plan(defaults(self.snapshot))
            self.recalculate()

    def render(self, s, result):
        today = bj_date(s['asOf']).isoformat()
        stock = amounts(s['resources'])
        stars = sum(r['star'] for r in s['stages'])
        self.identity.setText(f"{s.get('platform', '')} · 玩家 {s.get('name') or s['roleId']}（{s['roleId']}） · "
            f"{s['season']['name']} · 快照日期 {today}（北京时间）\n"
            f"战旗{s['flagLevel']}级 · 深渊{stars}星 · 木头{stock.get(WOOD, 0)} · "
            f"镇旗布{stock.get(CLOTH, 0)} · 铜钱{stock.get(GOLD, 0)} · 今日已扫荡{s['todaySweeps']}次")
        income = sum(v.get(WOOD, 0) for v in result['income'].values())
        tail = f"下一突破{result['next_break']}级还差{result['gap']}木头" if result['next_break'] else '已达配置最高级'
        self.summary.setText(f"截至{result['end']}：可达战旗{result['level']}级 · 总可用木头{stock.get(WOOD, 0) + income} · "
            f"升级后剩{result['resources'].get(WOOD, 0)}木头\n战令{result['bp']}级 · {tail}")
        self.daily.setRowCount(len(result['rows']))
        for i, r in enumerate(result['rows']):
            self.put(self.daily, i, [r['date'], r['stars'], f"{r['sweeps']}次×{r['wood_each']}",
                *[r['income'][k] for k in ('首通', '扫荡', '战令', '商店', '礼包')],
                r['wood'], r['level'], f"{r['bp']}级 {r['xp']}经验", r['earned_xp'], '；'.join(r['events'])])
        reached = {row['level']: row for row in result['milestones']}
        targets = {n for flag in s.get('flags', []) for n in flag['unlockLevel'] if n > 0}
        targets.update(r['level'] for r in s['levels'] if amounts(r['cost']).get(WOOD))
        self.milestones.setRowCount(len(targets))
        for i, target in enumerate(sorted(targets)):
            descriptions = []
            for flag in s.get('flags', []):
                for j, n in enumerate(flag['unlockLevel']):
                    if n == target:
                        import re
                        text = re.sub('<[^>]+>', '', flag['nodeTitle'][j])
                        state = '已升阶' if j <= flag['skillLevel'] else f'需{flag["costNum"][j]}祭旗铃升阶'
                        descriptions.append(f"{flag['name']} {text} {flag['nodeDesc'][j]}（{state}）")
            reached_day = '当前已满足等级' if target <= s['flagLevel'] else reached.get(target, {}).get('date', '截止日未达到')
            config = next(r for r in s['levels'] if r['level'] == target)
            self.put(self.milestones, i, [reached_day, target, amounts(config['cost']).get(WOOD, 0),
                '；'.join(descriptions) or '属性突破节点'])
        actual_bp = self.snapshot['bp']
        names = {WOOD: '展旗木', CLOTH: '镇旗布', GOLD: '铜钱', '10081': '祭旗铃',
                 '10055': '血月币', '10004': '元宝'}
        describe = lambda items: '，'.join(f'{names.get(k, k)}{v}' for k, v in amounts(items).items()) or '无'
        lines = ['读取的是游戏当前同步状态，重新拉取会更新余额和已领记录。',
                 f"战令实际等级{actual_bp['level']}，当前级经验{actual_bp['exp']}",
                 f"本次模拟起点：战令{s['bp']['level']}级，当前级经验{s['bp']['exp']}",
                 f"进阶战令：{'已开通' if actual_bp['active'][1] else '未开通'}；最高档战令：{'已开通' if actual_bp['active'][2] else '未开通'}",
                 '已领取至：' + '，'.join(f'{title}{n}级' for title, n in zip(('免费', '进阶', '最高档'), actual_bp['claimed'])),
                 f"当前探渊券：{s.get('tickets', '未提供')}", '']
        for goods in (s.get('exchange'), s.get('gift')):
            if goods: lines.append(f"{goods['name']}：本周已购{goods['bought']}/{goods['limit']}，单份奖励{describe(goods['rewards'])}")
        lines += ['', '深渊当前各关星级：']
        lines += [f"{r['area']} 第{r['sort']}关：{r['star']}/{len(r['rewards'])}星" for r in s['stages']]
        lines += ['', '预测新增来源：']
        lines += [f"{name}：木头{v.get(WOOD, 0)}，镇旗布{v.get(CLOTH, 0)}，铜钱{v.get(GOLD, 0)}" for name, v in result['income'].items()]
        lines += ['', f"升级累计消耗：{describe(result['spent'])}", f"其他材料缺口：{describe(result['deficits'])}",
                  f"计划扫荡消耗元宝{result['diamond_cost']}，兑换消耗血月币{result['exchange_cost']}，礼包支出¥{result['cash_cost']/100:g}",
                  '商店兑换假设血月币足够；付费扫荡假设元宝足够。',
                  '推星优先完成当前已解锁的高难度，每颗新增星消耗一张探渊券，计入每日补充与地图开放日。',
                  '每天按木头直接升到可达到的最高等级，不预留升级次数；卡住或满级时不虚计每日升级任务经验。',
                  '逐日调整里的战令等级是额外假设，升到该级的购买成本不自动计入。']
        self.current.setPlainText('\n'.join(lines))
        self.notes.setText('\n'.join(result['warnings']))
        for table in (self.daily, self.milestones, self.task_table, self.schedule):
            for col in range(table.columnCount() - 1): table.setColumnWidth(col, 110 if col else 135)
        self.task_table.setColumnWidth(0, 330)


class FlagUpgradeFeature:
    def __init__(self, transport, state, panel):
        self.transport, self.state, self.panel = transport, state, panel
        self.job = None
        self.generation = 0
        panel.requested.connect(self.request)

    def request(self):
        if self.state.closing or not self.state.installed:
            self.panel.message.setText('请先连接游戏并完成挂载')
            return
        if self.job and not self.job.done(): return
        self.generation += 1
        self.job = asyncio.create_task(self.read(self.state.installed, self.generation))

    async def read(self, session, generation):
        self.panel.set_busy(True)
        self.panel.message.setText('正在读取当前角色深渊、战令、任务、材料与配置…')
        try:
            data = await self.transport.flag_upgrade_read()
            if self.state.closing or self.state.installed != session or self.generation != generation: return
            data = dict(data, platform=getattr(self.transport, 'platform_name', '微信'))
            self.panel.accept(data)
        except Exception as exc:
            LOG.exception('读取战旗升级数据失败')
            if self.state.installed == session and self.generation == generation:
                self.panel.message.setText(f'读取失败：{exc}')
        finally:
            self.panel.set_busy(False)

    async def close(self):
        self.generation += 1
        if self.job and not self.job.done(): self.job.cancel()
        if self.job: await asyncio.gather(self.job, return_exceptions=True)
