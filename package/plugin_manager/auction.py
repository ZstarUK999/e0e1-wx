"""阴司拍卖助手：GUI只选择/控制，精确定时在游戏VM执行。"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView

LOG=logging.getLogger('plugin_manager')

class AuctionPanel(QWidget):
    requested = Signal(str, object)
    def __init__(self, store=None):
        super().__init__()
        self.rows=[];self.checked=set();self.stamp=0;self.server_now=0;self.running=False;self.ready=False
        layout=QVBoxLayout(self)
        title=QLabel('拍卖助手');title.setObjectName('panelTitle');layout.addWidget(title)
        note=QLabel('进入游戏「阴司 → 拍卖行」后读取拍品。勾选多件拍品，点击开始后，在开拍前500ms起每100ms刷新真实列表，拿到真实列表后停止刷新，固定ID并按50ms间隔每件最多发送3次一口价请求；成功或竞拍已结束即停止。离开拍卖行或断开连接会停止。')
        note.setWordWrap(True);layout.addWidget(note)
        self.message=QLabel('等待连接游戏并进入拍卖行');self.message.setWordWrap(True);layout.addWidget(self.message)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['选择','拍品','一口价','开拍倒计时','数据','拍品ID','状态'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide();layout.addWidget(self.table,1)
        buttons=QHBoxLayout();self.start=QPushButton('开始：一口价购买所选拍品');self.stop=QPushButton('停止');self.refresh=QPushButton('读取当前拍卖')
        for b in (self.start,self.stop,self.refresh):buttons.addWidget(b)
        layout.addLayout(buttons)
        self.start.clicked.connect(self._start);self.stop.clicked.connect(lambda:self.requested.emit('stop',{}));self.refresh.clicked.connect(lambda:self.requested.emit('status',{}))
        self.table.itemChanged.connect(self._check)
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self._countdown);self.timer.start()
        self.set_ready(False)
    def _check(self,item):
        if item.column()!=0:return
        key=item.data(Qt.UserRole)
        if item.checkState()==Qt.Checked:self.checked.add(key)
        else:self.checked.discard(key)
    def _start(self):
        keys=[r['key'] for r in self.rows if r['key'] in self.checked]
        if not keys:self.message.setText('请先勾选要一口价购买的拍品');return
        self.requested.emit('arm',{'keys':keys})
    def set_ready(self,ready):
        self.ready=bool(ready)
        self.start.setEnabled(self.ready and not self.running and bool(self.rows))
        self.stop.setEnabled(self.ready);self.refresh.setEnabled(self.ready)
        if not ready:self.message.setText('未连接游戏；拍卖请求已暂停')
    def show_status(self,data):
        self.running=bool(data.get('running'));self.rows=data.get('rows',[])
        self.server_now=float(data.get('now',0));self.stamp=time.monotonic()
        self.checked.intersection_update(r['key'] for r in self.rows)
        jobs={j['key']:j for j in data.get('jobs',[])}
        self.table.blockSignals(True);self.table.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            check=QTableWidgetItem();check.setData(Qt.UserRole,r['key']);check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Checked if r['key'] in self.checked else Qt.Unchecked)
            if self.running:check.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(i,0,check)
            job=jobs.get(r['key'],{})
            state=job.get('status') or ('已成交' if r.get('result',0)>0 else '待选择')
            if job:
                state += f" · 实发{job.get('sent',0)}次"
            values=[str(r.get('name','')),str(r.get('price','')), '', '预览（临时ID）' if r.get('preview') else '真实', '—' if r.get('preview') else str(r['id']),state]
            for col,text in enumerate(values,1):self.table.setItem(i,col,QTableWidgetItem(text))
        self.table.blockSignals(False);self._countdown();self.set_ready(self.ready)
        if data.get('visible'):
            self.message.setText('正在等待/查询真实拍品；每件最多3次购买请求' if self.running else '勾选拍品后点击开始。预览ID不会用于购买。')
        else:self.message.setText('请在游戏中进入「阴司 → 拍卖行」；离开后自动停止')
    def _countdown(self):
        now=self.server_now+(time.monotonic()-self.stamp)*1000
        for i,r in enumerate(self.rows):
            start=float(r.get('start',0));left=max(0,start-now)
            text=f'{left/1000:.1f}s' if start>0 and left>0 else ('已开拍' if start>0 else '未知')
            item=self.table.item(i,3)
            if item:item.setText(text)

class AuctionFeature:
    def __init__(self,transport,state,panel):
        self.transport,self.state,self.panel=transport,state,panel;self.job=None
        self._job_signature=None;self._audit_cursor={};self._last_poll_error=None
        panel.requested.connect(self.request)
    def request(self,op,args):
        if not self.state.installed or self.state.closing:
            self.panel.message.setText('请先连接游戏');return
        if self.job and not self.job.done():return
        LOG.info('拍卖助手操作：%s %s',op,json.dumps(args,ensure_ascii=False))
        self.job=asyncio.create_task(self.command(op,args))
    def _accept(self,result):
        # Persist VM audit events even on transports without console forwarding.
        for entry in result.get('audit',[]):
            trace=entry.get('traceId','legacy');seq=entry.get('seq',0)
            if seq>self._audit_cursor.get(trace,0):
                LOG.info('拍卖助手事件：%s',json.dumps(entry,ensure_ascii=False,sort_keys=True))
                self._audit_cursor[trace]=seq
        if len(self._audit_cursor)>20:
            self._audit_cursor={trace:self._audit_cursor[trace]}
        signature=json.dumps(result.get('jobs',[]),ensure_ascii=False,sort_keys=True)
        if signature!=self._job_signature:
            self._job_signature=signature
            if result.get('jobs'):LOG.info('拍卖助手状态：%s',signature)
        self.panel.show_status(result)
    async def command(self,op,args):
        self.panel.start.setEnabled(False)
        try:
            result=await self.transport.auction_call(op,args)
            if result is None:raise RuntimeError('游戏未连接')
            if not self.state.closing:self._accept(result)
        except Exception as exc:
            LOG.exception('拍卖助手操作失败：%s',op)
            self.panel.message.setText(f'拍卖助手：{exc}')
        finally:self.panel.set_ready(bool(self.state.installed) and not self.state.closing)
    async def poll(self):
        ready=bool(self.state.installed) and not self.state.closing;self.panel.set_ready(ready)
        if not ready or (self.job and not self.job.done()):return
        try:
            result=await self.transport.auction_call('status',{})
            if result is None:raise RuntimeError('游戏未连接')
            if not self.state.closing:self._accept(result)
            self._last_poll_error=None
        except Exception as exc:
            message=str(exc)
            if message!=self._last_poll_error:LOG.warning('读取拍卖行失败：%s',message)
            self._last_poll_error=message
            self.panel.message.setText(f'读取拍卖行失败：{exc}')
    async def close(self):
        try:
            if self.state.installed:
                result=await self.transport.auction_call('stop',{})
                if result:self._accept(result)
        except Exception as exc:LOG.warning('拍卖助手退出停止未确认：%s',exc)
