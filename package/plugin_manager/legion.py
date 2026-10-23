"""阴司透视：公开预览、已浏览快照和成员页签。"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,QLabel,QTabWidget,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView

LOG=logging.getLogger('plugin_manager')
from .power_format import format_power
COLUMNS=[('id','玩家ID'),('name','名字'),('fightPower','战力'),('maxFightPower','最高战力'),('level','等级'),('sName','服务器'),('job','职位'),('isOnline','在线状态'),('lastOnlineTime','最后在线'),('joinTime','加入时间'),('contribDay','今日贡献'),('contrib','总贡献'),('passStageId','通关关卡ID')]
JOBS={0:'无',1:'阎君',2:'判官',3:'拘魂使',9:'成员'}

class LegionHistory:
    def __init__(self,path):
        self.path=Path(path);self.rows={}
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(data,dict):self.rows={str(k):v for k,v in data.items() if str(k).isdigit() and isinstance(v,dict) and isinstance(v.get('members'),list)}
        except (OSError,ValueError):pass
    def save(self,data):
        row=dict(data);row['saved_at']=datetime.now().isoformat(timespec='seconds')
        rows={**self.rows,str(row['id']):row}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix=self.path.name,suffix='.tmp')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(rows,f,ensure_ascii=False,allow_nan=False)
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        self.rows=rows
        return row

class NumericItem(QTableWidgetItem):
    def __lt__(self,other):
        left=self.data(Qt.ItemDataRole.UserRole);right=other.data(Qt.ItemDataRole.UserRole)
        if isinstance(left,(int,float)) and isinstance(right,(int,float)):return left<right
        try:return float(self.text())<float(other.text())
        except ValueError:return self.text()<other.text()

class LegionPanel(QWidget):
    requested=Signal(str)
    def __init__(self,store):
        super().__init__();self.history=LegionHistory(store.path.with_name('legion_history.json'));self.selected=None
        layout=QVBoxLayout(self);top=QHBoxLayout();layout.addLayout(top)
        top.addWidget(QLabel('阴司'))
        self.selector=QComboBox();self.selector.setEditable(True);self.selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert);self.selector.lineEdit().setPlaceholderText('输入阴司ID，或选择已浏览阴司');self.selector.setMinimumWidth(260);top.addWidget(self.selector,1)
        self.query=QPushButton('查询 / 刷新');top.addWidget(self.query)
        self.summary=QLabel('在游戏中打开阴司详情，或输入阴司ID查询');self.summary.setWordWrap(True);self.summary.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.summary)
        self.message=QLabel('历史记录可离线查看，查询需要连接游戏');self.message.setWordWrap(True);layout.addWidget(self.message)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.table=QTableWidget(0,len(COLUMNS));self.table.setHorizontalHeaderLabels([t for _,t in COLUMNS]);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setAlternatingRowColors(True);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.table.verticalHeader().hide();self.tabs.addTab(self.table,'阴司成员')
        from .legion_scan import LegionScanPanel
        self.scan=LegionScanPanel(store.path.with_name('legion_scan.sqlite3'))
        self.tabs.addTab(self.scan,'区段扫描')
        self.query.clicked.connect(self._request);self.selector.lineEdit().returnPressed.connect(self._request);self.selector.activated.connect(self._choose)
        self._reload()
        if self.selector.count():self.show_data(self.history.rows[self.selector.itemData(0)])
    def _reload(self):
        self.selector.blockSignals(True);self.selector.clear()
        for row in sorted(self.history.rows.values(),key=lambda r:r.get('saved_at',''),reverse=True):self.selector.addItem(f"{row.get('name') or '未命名阴司'} · {row['id']}",str(row['id']))
        index=self.selector.findData(self.selected)
        if index>=0:self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)
    def _choose(self,index):
        key=self.selector.itemData(index)
        if key in self.history.rows:self.show_data(self.history.rows[key]);self.message.setText('已显示本地快照；点击查询 / 刷新获取最新数据')
    def _request(self):
        text=self.selector.currentText().strip();index=self.selector.currentIndex()
        key=self.selector.itemData(index) if index>=0 and text==self.selector.itemText(index) else text
        if not key or not str(key).isascii() or not str(key).isdigit() or not 0<int(key)<=9007199254740991:
            self.message.setText('请输入有效的正整数阴司ID');return
        self.requested.emit(str(int(key)))
    def accept(self,data,*,show=True):
        row=self.history.save(data);self._reload()
        if show:self.show_data(row)
    def show_data(self,data):
        self.selected=str(data['id']);index=self.selector.findData(self.selected)
        self.selector.blockSignals(True)
        if index>=0:self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)
        self.summary.setText(f"{data.get('name','未知阴司')} · ID {self.selected} · 等级 {data.get('level','—')} · {data.get('sName') or data.get('serverId','—')}\n阎君：{data.get('leaderName','—')} · 人数 {data.get('memberNum',len(data['members']))}/{data.get('memberNumMax','—')} · 总战力 {format_power(data.get('fightPower'))}\n公告：{data.get('notice') or '无'}")
        self.table.setSortingEnabled(False);self.table.setRowCount(len(data['members']))
        for i,row in enumerate(data['members']):
            for j,(key,_) in enumerate(COLUMNS):
                value=row.get(key,'—')
                if key=='sName':value=row.get('sName') or row.get('sId','—')
                elif key=='job':value=JOBS.get(value,str(value))
                elif key=='isOnline':value=('在线' if value else '离线') if isinstance(value,bool) else '—'
                elif key in ('lastOnlineTime','joinTime') and isinstance(value,(int,float)):
                    try:value=datetime.fromtimestamp(value/1000 if value>1e12 else value).strftime('%Y-%m-%d %H:%M:%S') if value>0 else '—'
                    except (ValueError,OSError,OverflowError):value=str(value)
                self.table.setItem(i,j,NumericItem(str(value)))
                if key in ('fightPower','maxFightPower'):
                    item=self.table.item(i,j);raw=row.get(key)
                    item.setText(format_power(raw));item.setData(Qt.ItemDataRole.UserRole,raw);item.setToolTip(str(raw) if raw is not None else '—')
        self.table.setSortingEnabled(True);self.table.sortItems(2,Qt.SortOrder.DescendingOrder)
        total=data.get("memberNum",len(data["members"]))
        scope=f"预览成员 {len(data['members'])}/{total}（接口仅返回部分成员）" if isinstance(total,(int,float)) and total>len(data["members"]) else f"成员 {len(data['members'])}/{total}"
        self.message.setText(f"本地快照：{data.get('saved_at','刚刚')} · {scope}；未返回字段显示 —")

class LegionFeature:
    def __init__(self,transport,state,panel):
        self.transport,self.state,self.panel=transport,state,panel;self.next_poll=0;self.signature=None;self.seen_session=None;self.observed_id=None;self.job=None
        panel.requested.connect(self.request)
        from .legion_scan import LegionScanner
        self.scanner=LegionScanner(transport,state,panel.scan)
    def request(self,key):
        if not self.state.installed or self.state.closing or not hasattr(self.transport,'legion_read'):
            self.panel.message.setText('请先连接游戏并完成挂载，历史快照仍可查看');return
        if self.job and not self.job.done():return
        self.job=asyncio.create_task(self.fetch(key))
    async def fetch(self,key):
        self.panel.query.setEnabled(False);self.panel.message.setText('正在查询阴司…');session=self.state.installed
        try:
            await self.scanner.wait_operation()
            data=await self.transport.legion_read(key)
            if self.state.closing or session!=self.state.installed:return
            if not data:raise RuntimeError('未返回阴司信息')
            self.panel.accept(data);LOG.info('阴司透视查询完成：ID=%s，成员=%s',key,len(data['members']))
        except Exception as exc:self.panel.message.setText(f'查询失败：{exc}；已保存快照仍可查看')
        finally:self.panel.query.setEnabled(True)
    async def wait_operation(self):
        if self.job and not self.job.done():await asyncio.shield(self.job)
        await self.scanner.wait_operation()
    async def poll(self):
        if not self.state.installed or self.state.closing or not hasattr(self.transport,'legion_read'):return
        if self.job and not self.job.done():return
        if self.scanner.job and not self.scanner.job.done():return
        if time.monotonic()<self.next_poll:
            await self.scanner.poll();return
        self.next_poll=time.monotonic()+2;session=self.state.installed
        if session!=self.seen_session:self.signature=None;self.seen_session=session
        try:
            data=await self.transport.legion_read()
            if session!=self.state.installed or self.state.closing:return
            if not data:self.signature=None;self.observed_id=None;return
            signature=json.dumps(data,ensure_ascii=False,sort_keys=True)
            if signature!=self.signature:
                self.panel.accept(data,show=self.observed_id!=str(data['id']) or self.panel.selected==str(data['id']));self.signature=signature;self.observed_id=str(data['id'])
        except Exception as exc:
            LOG.debug('阴司详情读取暂不可用：%s',exc)
        finally:
            await self.scanner.poll()
