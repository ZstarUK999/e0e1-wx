"""阴司区段扫描的页面和单请求调度器。"""
import asyncio
import time
import logging
from collections import deque
from datetime import datetime,timezone,timedelta

from PySide6.QtCore import Qt,QTimer,Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,
    QLabel,QTreeWidget,QTreeWidgetItem,QMenu,QDoubleSpinBox,QSpinBox)

from .legion_scan_store import LegionScanStore
from .power_format import format_power
LOG=logging.getLogger('plugin_manager')
BEIJING=timezone(timedelta(hours=8))


def relative_online(value,online=None,now_seconds=None):
    if not value:return '未更新'
    current=datetime.now(BEIJING).timestamp() if now_seconds is None else now_seconds
    elapsed=max(0,int(current-float(value)/1000))
    if online:return '刚刚'
    if elapsed<60:return '刚刚'
    if elapsed<3600:return f'{elapsed//60}分钟前'
    if elapsed<86400:return f'{elapsed//3600}小时前'
    return f'{elapsed//86400}天前'


class LegionScanPanel(QWidget):
    player_requested=Signal(str)
    def __init__(self, path):
        super().__init__()
        self.db=LegionScanStore(path)
        self.feature=None
        layout=QVBoxLayout(self)
        row=QHBoxLayout();layout.addLayout(row)
        self.search=QLineEdit();self.search.setPlaceholderText('输入阴司名称搜索，或输入阴司ID');row.addWidget(self.search,1)
        self.add=QPushButton('搜索并创建区段');row.addWidget(self.add)
        self.toggle=QPushButton('暂停 / 继续所选区段');row.addWidget(self.toggle)
        self.refresh_button=QPushButton('刷新数据');row.addWidget(self.refresh_button)
        options=QHBoxLayout();layout.addLayout(options)
        options.addWidget(QLabel('自动更新阴司最低战力'))
        self.min_power=QDoubleSpinBox();self.min_power.setRange(0,100000000);self.min_power.setDecimals(2)
        self.min_power.setSuffix(' 亿');self.min_power.setValue(self.db.min_power()/100000000)
        self.min_power.setToolTip('已标记或战力达到门槛，任一条件满足即自动更新阴司及当天未更新的成员；标记阴司不受门槛限制。')
        options.addWidget(self.min_power);options.addStretch()
        options.addWidget(QLabel('扫描间隔'))
        self.interval=QDoubleSpinBox();self.interval.setRange(.1,3600);self.interval.setDecimals(1)
        self.interval.setSuffix(' 秒');self.interval.setValue(self.db.interval());options.addWidget(self.interval)
        self.interval.setToolTip('每次自动查询完成后等待的时间，重试等待至少15秒；主循环繁忙时实际间隔可能更长。')
        self.interval.valueChanged.connect(self.interval_changed)
        options.addWidget(QLabel('查询并发数'))
        self.workers=QSpinBox();self.workers.setRange(1,10);self.workers.setValue(self.db.workers());options.addWidget(self.workers)
        self.workers.valueChanged.connect(self.db.set_workers)
        self.resume_errors=QPushButton('恢复异常停止');options.addWidget(self.resume_errors)
        self.resume_errors.clicked.connect(lambda:self.feature.resume_after_errors() if self.feature else None)
        self.min_power.valueChanged.connect(self.power_changed)
        self.status=QLabel('以种子阴司管理成员ID确定初始范围，按发现的玩家和成员ID校准扩展；两侧各100个交替补扫。')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True);layout.addWidget(self.status)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['区服段 / 阴司 / 玩家','ID / 扫描进度','战力','区服 / 扫描边界','更新时间','最后在线（北京时间）'])
        self.tree.setColumnWidth(0,300);self.tree.setColumnWidth(1,220);self.tree.setColumnWidth(3,240)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.tree,1)
        self.add.clicked.connect(self.create);self.search.returnPressed.connect(self.create)
        self.toggle.clicked.connect(self.pause);self.refresh_button.clicked.connect(self.refresh)
        self.tree.itemExpanded.connect(self.expand);self.tree.itemDoubleClicked.connect(self.more)
        self.tree.customContextMenuRequested.connect(self.menu)
        self.relative_timer=QTimer(self);self.relative_timer.setInterval(60000)
        self.relative_timer.timeout.connect(self.refresh_relative_times);self.relative_timer.start()
        self.refresh()

    def create(self):
        if self.feature:self.feature.create(self.search.text().strip())
        else:self.status.setText('请先连接游戏')

    def set_platform(self, platform):
        self.db.platform=platform
        self.min_power.blockSignals(True);self.min_power.setValue(self.db.min_power()/100000000);self.min_power.blockSignals(False)
        self.interval.blockSignals(True);self.interval.setValue(self.db.interval());self.interval.blockSignals(False)
        self.workers.blockSignals(True);self.workers.setValue(self.db.workers());self.workers.blockSignals(False)
        self.refresh()

    def interval_changed(self, value):
        self.db.set_interval(value)
        self.status.setText(f'扫描间隔已保存：{value:g} 秒，从下一次查询完成后生效')

    def power_changed(self, value):
        self.db.set_min_power(value*100000000)
        if self.feature:
            self.feature.refreshed_legions.clear()
            self.feature.next_request=0
        self.status.setText(f'自动更新门槛已保存：{value:g} 亿；区段扫描继续保存所有发现的玩家')

    def refresh(self):
        self.db.calibrate()
        self.tree.clear()
        self.update_roots()

    def update_roots(self):
        roots={self.tree.topLevelItem(i).data(0,Qt.ItemDataRole.UserRole)[1]:self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())}
        for task in self.db.tasks():
            groups=self.db.groups(task['id']);lo,hi=self.db.servers(task['id'])
            title=f'{lo}–{hi}服' if lo is not None else '区服段待扫描'
            top=next((g for g in groups if g['id']!='0'),None)
            title+=' · '+(top['name'] if top else task['name'])
            total=task['range_high']-task['range_low']+1
            complete=task['cursor']>=total
            state='完成' if complete else ('暂停' if task['paused'] else '待扫描')
            root=roots.get(task['id'])
            if root is None:root=QTreeWidgetItem(self.tree)
            for column,value in enumerate([title,f"{task['cursor']}/{total} · {state}",'',f"{task['range_low']}–{task['range_high']}",'']):root.setText(column,value)
            root.setData(0,Qt.ItemDataRole.UserRole,('task',task['id']))
            root.setToolTip(0,f"种子阴司：{task['name']} ({task['legion_id']})\n种子范围：{task['seed_low']}–{task['seed_high']}\n已扫边界：{task['scanned_low']}–{task['scanned_high']}\n{task['error']}")
            root.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

    def expand(self, item):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if not data:return
        if data[0]=='task':
            item.takeChildren()
            for group in self.db.groups(data[1]):
                name=('★ ' if group['marked'] else '')+(group['name'] or ('未加入阴司' if group['id']=='0' else '未知阴司'))
                child=QTreeWidgetItem(item,[f"{name} · 已发现{group['count']}人",group['id'],format_power(group['power']),'',group['updated_at'] or '待更新'])
                child.setToolTip(2,f"{group['power']:,.0f}")
                child.setData(0,Qt.ItemDataRole.UserRole,('legion',data[1],group['id'],bool(group['marked'])))
                child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        elif data[0]=='legion':
            item.takeChildren();self.load_members(item,data[1],data[2],0)

    def load_members(self, parent, task_id, lid, offset):
        rows=self.db.members(task_id,lid,offset,501)
        for row in rows[:500]:
            child=QTreeWidgetItem(parent,[row['name'],str(row['id']),format_power(row['power']),row['server_name'] or str(row['server_no'] or '—'),row['updated_at'] or '待查询'])
            child.setToolTip(2,f"{row['power']:,.0f}")
            child.setText(5,relative_online(row['last_online_ms'],row['online']))
            child.setData(5,Qt.ItemDataRole.UserRole,(row['last_online_ms'],row['online']))
            if row['last_online_ms']:
                child.setToolTip(5,datetime.fromtimestamp(row['last_online_ms']/1000,BEIJING).strftime('%Y-%m-%d %H:%M:%S 北京时间'))
            child.setData(0,Qt.ItemDataRole.UserRole,('player',row['id']))
        if len(rows)>500:
            child=QTreeWidgetItem(parent,['双击加载更多成员…'])
            child.setData(0,Qt.ItemDataRole.UserRole,('more',task_id,lid,offset+500))

    def refresh_relative_times(self):
        def visit(item):
            value=item.data(5,Qt.ItemDataRole.UserRole)
            if value:item.setText(5,relative_online(*value))
            for i in range(item.childCount()):visit(item.child(i))
        for i in range(self.tree.topLevelItemCount()):visit(self.tree.topLevelItem(i))

    def more(self, item, column=0):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if data and data[0]=='player':
            self.player_requested.emit(str(data[1]));return
        if data and data[0]=='more':
            parent=item.parent();parent.removeChild(item);self.load_members(parent,*data[1:])

    def pause(self):
        item=self.tree.currentItem()
        while item and item.parent():item=item.parent()
        if not item:return
        data=item.data(0,Qt.ItemDataRole.UserRole)
        task=next((t for t in self.db.tasks() if t['id']==data[1]),None)
        if task:self.db.pause(task['id'],not task['paused']);self.refresh()

    def menu(self, point):
        item=self.tree.itemAt(point)
        if not item:return
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if not data or data[0]!='legion' or data[2]=='0':return
        menu=QMenu(self)
        action=menu.addAction('取消每日成员更新' if data[3] else '标记：每日优先更新成员')
        update=menu.addAction('立即更新已发现成员信息')
        selected=menu.exec(self.tree.viewport().mapToGlobal(point))
        if selected==update:
            if self.feature:self.feature.insert_member_update(data[2])
        elif selected==action:
            self.db.mark(data[2],not data[3]);self.refresh()


class LegionScanner:
    def __init__(self, transport, state, panel):
        self.transport,self.state,self.panel=transport,state,panel
        self.db=panel.db;panel.feature=self
        panel.set_platform('douyin' if getattr(transport,'platform_name','微信')!='微信' else 'wechat')
        self.job=None;self.next_request=0;self.next_ui=0
        self.refreshed_legions=set()
        self.pending_create=None
        self.priority_requested=False
        self.seen_session=None
        self.error_window=deque(maxlen=20);self.failed_batches=0
        self.halted=self.db.halt_reason()
        if self.halted:self.panel.status.setText(self.halted)
        self.ready_session=None
        self.timer=QTimer(panel);self.timer.setInterval(100)
        self.timer.timeout.connect(self.schedule)
        self.timer.start()

    def set_ready(self,session):
        self.ready_session=session

    def schedule(self):
        # Public read queries continue even while daily automation owns the UI.
        if self.halted or self.state.closing or not self.state.installed or self.ready_session!=self.state.installed:return
        if self.job and not self.job.done():return
        if self.seen_session==self.state.installed and not self.pending_create and time.monotonic()<self.next_request:return
        try:loop=asyncio.get_running_loop()
        except RuntimeError:return
        loop.create_task(self.poll())

    def valid(self, session):
        return not self.state.closing and session==self.state.installed

    def create(self, text):
        if not text:self.panel.status.setText('请输入阴司名称或ID');return
        if not self.state.installed or self.state.closing:self.panel.status.setText('请先连接游戏并完成挂载');return
        if self.job and not self.job.done():
            self.pending_create=text
            self.panel.status.setText('当前查询结束后，将搜索阴司并创建区段')
            return
        self.job=asyncio.create_task(self.create_task(text))

    async def create_task(self, text):
        self.panel.add.setEnabled(False);session=self.state.installed
        try:
            info=await (self.transport.legion_read(text) if text.isascii() and text.isdigit() else self.transport.legion_scan_call('search',text))
            if not self.valid(session):return
            if not info:raise ValueError('未找到阴司')
            task=self.db.create_task(info)
            self.panel.status.setText(f"已保存区段：{task['name']} · 从 {task['seed_low']}–{task['seed_high']} 开始，已有任务继续原断点")
            self.panel.refresh()
        except Exception as exc:
            LOG.exception('阴司区段创建接口失败：搜索=%s；平台=%s',text,self.db.platform)
            self.panel.status.setText(f'创建失败：{exc}')
        finally:
            self.panel.add.setEnabled(True);self.next_request=time.monotonic()+self.db.interval()

    async def poll(self):
        if self.halted:
            self.panel.status.setText(self.halted);return
        if not self.state.installed or self.state.closing:return
        if self.job and not self.job.done():return
        if self.seen_session!=self.state.installed:
            self.seen_session=self.state.installed
            self.refreshed_legions.clear()
            self.next_request=0
            self.next_ui=0
        if self.pending_create:
            text,self.pending_create=self.pending_create,None
            self.create(text);return
        if time.monotonic()<self.next_request:return
        self.job=asyncio.create_task(self.step())

    async def step(self):
        if self.halted:return
        self.batch_outcomes=None
        session=self.state.installed;task=None;operation='读取任务';target='';failed=False
        try:
            queued=self.db.queued_members(self.db.workers())
            if queued:
                operation='插入任务：更新阴司成员';target=','.join(str(r['pid']) for r in queued)
                await self.update_inserted(queued,session)
                self.record_health(*(self.batch_outcomes or (0,len(queued))))
                return
            legion=self.db.stale_legion(self.refreshed_legions)
            if legion:
                operation='更新阴司';target=legion['id']
                self.panel.status.setText(f"优先更新阴司信息：{legion['name']} ({legion['id']})")
                info=await self.transport.legion_read(legion['id'])
                if not self.valid(session):return
                if not info:raise RuntimeError('阴司信息未返回，稍后重试')
                self.db.save_legion(info)
                self.refreshed_legions.add(legion['id'])
            else:
                player=self.db.stale_marked_player()
                if player:
                    operation='更新标记阴司玩家';target=str(player['id'])
                    pid=player['id'];self.panel.status.setText(f"更新标记阴司玩家：{player['name']} ({pid})")
                else:
                    task=next((t for t in self.db.tasks() if not t['paused'] and self.db.candidate(t) is not None),None)
                    if not task:
                        self.panel.status.setText('今日优先更新已完成；区段扫描已完成或暂停');return
                    pid=self.db.candidate(task)
                    operation='扫描玩家';target=str(pid)
                    self.panel.status.setText(f"扫描 {task['name']}：{task['cursor']}/{task['range_high']-task['range_low']+1} · 玩家 {pid}")
                if task:
                    await self.scan_batch(task,session)
                else:
                    row=await self.transport.legion_scan_call('player',str(pid))
                    if not self.valid(session):return
                    self.db.record(pid,row,task)
            if time.monotonic()>=self.next_ui:
                # Update root progress without rebuilding a browsed branch.
                self.panel.update_roots()
                self.next_ui=time.monotonic()+10
            self.record_health(*(self.batch_outcomes or (0,1)))
        except Exception as exc:
            failed=True
            LOG.exception('阴司扫描接口报错：平台=%s；操作=%s；目标ID=%s；任务=%s；进度=%s；详情=%s',
                self.db.platform,operation,target,task['id'] if task else None,task['cursor'] if task else None,exc)
            if task:self.db.task_error(task['id'],str(exc))
            self.panel.status.setText(f'查询暂停15秒后重试，已保留断点：{exc}')
            self.record_health(*(self.batch_outcomes or (1,0)),detail=str(exc))
            self.next_request=time.monotonic()+15
        finally:
            self.next_request=max(self.next_request,time.monotonic()+self.db.interval())
            if self.priority_requested and not failed and not self.halted:
                self.next_request=time.monotonic()
                self.priority_requested=False

    def insert_member_update(self,lid):
        count=self.db.enqueue_members(lid)
        self.priority_requested=bool(count)
        if count and not self.halted and (not self.error_window or not self.error_window[-1]):
            self.next_request=time.monotonic()
        if self.halted:
            self.panel.status.setText(f'已插入阴司 {lid} 的 {count} 名已发现成员更新；接口异常停止尚未解除，请先恢复')
        else:
            self.panel.status.setText(f'已插入阴司 {lid} 的 {count} 名成员更新；当前查询结束后优先执行，完成后续扫')

    async def update_inserted(self,queued,session):
        # Queue survives restarts; successful members are removed individually.
        ids=[str(r['pid']) for r in queued]
        self.panel.status.setText(f'优先更新阴司已发现成员：{", ".join(ids)}')
        if len(ids)==1:
            replies=[{'id':ids[0],'value':await self.transport.legion_scan_call('player',ids[0])}]
        else:replies=await self.transport.legion_scan_call('players',ids)
        if not self.valid(session):return
        if not isinstance(replies,list) or len(replies)!=len(ids):raise RuntimeError('成员更新回执数量不匹配')
        errors=[]
        for item,reply in zip(queued,replies):
            if not isinstance(reply,dict) or str(reply.get('id'))!=str(item['pid']) or reply.get('error') or 'value' not in reply:
                errors.append(f"玩家 {item['pid']}：{reply.get('error','回执无效') if isinstance(reply,dict) else '回执无效'}");continue
            self.db.record(item['pid'],reply['value'])
            self.db.finish_member(item['legion_id'],item['pid'])
        self.batch_outcomes=(len(errors),len(queued)-len(errors))
        if errors:raise RuntimeError('；'.join(errors))
        if not self.db.queued_members(1):
            self.db.calibrate();self.panel.refresh()
            self.panel.status.setText('阴司成员插入更新已完成，将继续原区段扫描')

    async def scan_batch(self,task,session):
        planned=[]
        for cursor in range(task['cursor'],min(task['range_high']-task['range_low']+1,task['cursor']+self.db.workers())):
            if not self.db.receipt(task,cursor)[0]:
                planned.append((cursor,self.db.candidate({**task,'cursor':cursor})))
        errors=[]
        if planned:
            ids=[str(pid) for _,pid in planned]
            self.panel.status.setText(f"并发查询 {len(ids)} 人：{', '.join(ids)}")
            if len(ids)==1:
                value=await self.transport.legion_scan_call('player',ids[0])
                replies=[{'id':ids[0],'value':value}]
            else:
                replies=await self.transport.legion_scan_call('players',ids)
            if not self.valid(session):return
            if not isinstance(replies,list) or len(replies)!=len(ids):raise RuntimeError('并发查询回执数量不匹配')
            for (cursor,pid),reply in zip(planned,replies):
                if not isinstance(reply,dict) or str(reply.get('id'))!=str(pid):
                    errors.append(f'玩家 {pid}：回执ID不匹配');continue
                if reply.get('error'):
                    errors.append(f"玩家 {pid}：{reply['error']}");continue
                if 'value' not in reply:
                    errors.append(f'玩家 {pid}：缺少查询回执');continue
                self.db.save_receipt(task,cursor,pid,reply['value'])
            self.batch_outcomes=(len(errors),len(planned)-len(errors))
        current=next(t for t in self.db.tasks() if t['id']==task['id'])
        while self.valid(session) and self.db.candidate(current) is not None:
            exists,value=self.db.receipt(current,current['cursor'])
            if not exists:break
            self.db.record(self.db.candidate(current),value,current)
            current={**current,'cursor':current['cursor']+1}
        if errors:raise RuntimeError('；'.join(errors))

    def record_health(self, failures, successes, detail=''):
        self.failed_batches=self.failed_batches+1 if failures else 0
        self.error_window.extend([False]*successes+[True]*failures)
        if self.failed_batches>=3 or sum(self.error_window)>=5:
            self.halted=f'接口异常过多，已停止扫描：连续{self.failed_batches}批报错，最近{len(self.error_window)}次查询有{sum(self.error_window)}次错误。{detail}；处理后点击“恢复异常停止”继续。'
            self.db.halt(self.halted);self.panel.status.setText(self.halted)
            LOG.error('阴司扫描自动停止：平台=%s；%s',self.db.platform,self.halted)

    def resume_after_errors(self):
        self.db.halt('');self.halted='';self.failed_batches=0;self.error_window.clear();self.next_request=0
        self.panel.status.setText('异常停止已解除，将从保存的断点继续查询')

    async def wait_operation(self):
        if self.job and not self.job.done():await asyncio.shield(self.job)
