"""血月数据透视：本阴司历史、战场排名、完整分页战报和临时回放分析。"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from package.daily_tasks.scheduler import BEIJING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog)

from .legion import NumericItem
from .power_format import format_power
from .native_diagnostics import checkpoint

LOG=logging.getLogger('plugin_manager')
LEGIONS=[('rank','排名'),('name','阴司'),('sName','服务器'),('score','积分'),
         ('fightPower','战力'),('memberNum','人数'),('id','阴司ID')]
ROLES=[('rank','排名'),('name','玩家'),('legionName','阴司'),('sName','服务器'),
       ('score','积分'),('killRoleNum','杀敌'),('killGuardNum','攻城'),('dieNum','死亡'),
       ('statisticsSource','统计来源'),('membershipSource','成员来源'),('fightPower','战力'),('id','玩家ID'),('scoreSource','积分来源')]
REPORTS=[('time','时间'),('name','玩家'),('opponent','对手'),('result','输赢'),('side','攻守'),
         ('place','地点'),('energy','玩家耐力'),('other_energy','对手耐力'),
         ('power','玩家战力'),('other_power','对手战力'),('battleId','战斗ID')]


def format_time(value):
    try:
        return datetime.fromtimestamp(float(value)/1000, BEIJING).strftime('%Y-%m-%d %H:%M:%S') if value else '—'
    except (ValueError, TypeError, OverflowError, OSError):
        return '—'


def report_row(report, role_id):
    attack=report.get('rolePreview') or {}
    defense=report.get('tarRolePreview') or {}
    attack_info=report.get('roleInfo') or {}
    defense_info=report.get('tarRoleInfo') or {}
    is_defender=role_id == (defense_info.get('roleId') or defense.get('id'))
    mine,other=(defense,attack) if is_defender else (attack,defense)
    mine_info,other_info=(defense_info,attack_info) if is_defender else (attack_info,defense_info)
    win=report.get('winRoleId')
    return {'time':report.get('time'), 'name':mine.get('name') or '守卫',
        'opponent':other.get('name') or '守卫', 'result':'胜' if win==role_id else ('负' if win else '未结算'),
        'side':'防守' if is_defender else '进攻', 'place':report.get('place') or '—',
        'energy':mine_info.get('energy'), 'other_energy':other_info.get('energy'),
        'power':mine.get('fightPower'), 'other_power':other.get('fightPower'),
        'battleId':report.get('battleId')}


class SeasonInsightPanel(QWidget):
    requested=Signal(str,dict)

    def __init__(self,store):
        super().__init__()
        self.store=store;self.war=None;self.role=None;self.account=None;self.selected_legion=None
        self.cache_path=store.path.with_name('season_insight.json')
        try:self.cache=json.loads(self.cache_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.cache={}
        if not isinstance(self.cache,dict):self.cache={}
        from .season_report_store import SeasonReportStore
        self.report_store=SeasonReportStore(store.path.with_name('season_reports.sqlite3'))
        # Import legacy JSON without deleting it. The next metadata save strips
        # bulk reports only after every import transaction has committed.
        for account,bucket in self.cache.items():
            for key,snapshot in bucket.get('reports',{}).items():
                self.report_store.put(account,key,snapshot,only_missing=True)
        for account,reports in self.report_store.load().items():
            self.cache.setdefault(account,{'wars':{},'ranks':{},'reports':{}}).setdefault('reports',{}).update(reports)
        layout=QVBoxLayout(self)
        title=QLabel('血月数据透视');title.setObjectName('panelTitle');layout.addWidget(title)
        top=QHBoxLayout();layout.addLayout(top)
        top.addWidget(QLabel('本阴司历史战场'))
        self.selector=QComboBox();self.selector.setMinimumWidth(300);top.addWidget(self.selector,1)
        self.refresh=QPushButton('拉取 / 刷新');top.addWidget(self.refresh)
        self.stop_scan=QPushButton('停止扫描');top.addWidget(self.stop_scan)
        self.stop_scan.clicked.connect(lambda:self.requested.emit('stop_scan',{}))
        self.refresh_legion=QPushButton('重新拉取所选阴司');self.refresh_legion.setEnabled(False);top.addWidget(self.refresh_legion)
        self.all_roles=QPushButton('查看全场排名');top.addWidget(self.all_roles)
        self.export=QPushButton('导出当前页 CSV');top.addWidget(self.export)
        self.message=QLabel('连接游戏后拉取本阴司经历过的血月战场。双击玩家查看全部战报，双击战报播放并分析。')
        self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.message)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.legions=self._table(LEGIONS,'阴司列表')
        self.roles=self._table(ROLES,'个人排名')
        self.reports=self._table(REPORTS,'个人战报')
        self.refresh.clicked.connect(self.refresh_history)
        self.selector.activated.connect(self._select)
        self.legions.cellDoubleClicked.connect(self._open_legion)
        self.refresh_legion.clicked.connect(lambda:self._request_legion(force=True))
        self.all_roles.clicked.connect(self.show_all_roles)
        self.export.clicked.connect(self.export_csv)
        self.roles.cellDoubleClicked.connect(self._open_player)
        self.reports.cellDoubleClicked.connect(self._open_replay)
        self.set_ready(False)
        # Restore the latest saved account for offline browsing. A live history
        # refresh subsequently replaces the account and revalidates war IDs.
        saved_accounts=[key for key,value in self.cache.items() if isinstance(value,dict) and value.get('wars')]
        if saved_accounts:
            self.accept_history({'account':saved_accounts[-1],'rows':[], 'note':'本地缓存；连接后可手动刷新。'})

    def refresh_history(self):
        self._force_ranks=True
        self._scan_after_refresh=True
        self.requested.emit('history',{})

    def export_table_csv(self,path):
        table=self.tabs.currentWidget()
        if not self.war or not isinstance(table,QTableWidget) or not table.rowCount():
            raise ValueError('当前页没有可导出的数据')
        columns=LEGIONS if table is self.legions else ROLES if table is self.roles else REPORTS
        def safe(value):
            if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):return "'"+value
            return '' if value is None else value
        # Capture the displayed row order; numeric values retain their original
        # precision instead of exporting formatted units such as 万 or 亿.
        with open(path,'w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow(['战场ID','战场名称','筛选阴司ID']+[label for _,label in columns])
            for row in range(table.rowCount()):
                values=[]
                for col,(key,_) in enumerate(columns):
                    item=table.item(row,col)
                    value=item.data(Qt.ItemDataRole.UserRole) if item else None
                    if key=='time':value=format_time(value) if value else None
                    values.append(safe(value))
                writer.writerow([safe(self.war['warId']),safe(self.war.get('name')),
                                 safe((self.selected_legion or {}).get('id'))]+values)

    def export_csv(self):
        table=self.tabs.currentWidget()
        if not isinstance(table,QTableWidget) or not table.rowCount():
            self.message.setText('当前页没有可导出的数据');return
        path,_=QFileDialog.getSaveFileName(self,'导出当前页 CSV',
            f"血月数据_{datetime.now():%Y%m%d_%H%M%S}.csv",'CSV 文件 (*.csv)')
        if not path:return
        if not path.lower().endswith('.csv'):path+='.csv'
        try:
            self.export_table_csv(path)
            self.message.setText(f'已导出当前页：{path}')
        except (OSError,ValueError) as exc:self.message.setText(f'导出失败：{exc}')

    def _table(self,columns,title):
        table=QTableWidget(0,len(columns));table.setHorizontalHeaderLabels([name for _,name in columns])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True);table.setSortingEnabled(True);table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.sortItems(0,Qt.SortOrder.DescendingOrder if columns is REPORTS else Qt.SortOrder.AscendingOrder)
        self.tabs.addTab(table,title)
        return table

    def set_ready(self,ready):
        self.ready=bool(ready);self.refresh.setEnabled(self.ready)

    def save(self):
        checkpoint(f'season-cache-save begin account={self.account}')
        metadata={account:{k:v for k,v in bucket.items() if k!='reports'} for account,bucket in self.cache.items()}
        payload=json.dumps(metadata,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        self.cache_path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=self.cache_path.parent,prefix=self.cache_path.name,suffix='.tmp')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(payload)
            os.replace(tmp,self.cache_path)
            checkpoint('season-cache-save done')
        finally:
            if os.path.exists(tmp):os.unlink(tmp)

    def save_report(self,account,key,data):
        checkpoint(f'season-report-save begin account={account} key={key} rows={len(data.get("rows",[]))}')
        self.report_store.put(account,key,data)
        self.cache[account].setdefault('reports',{})[key]=data
        checkpoint(f'season-report-save committed key={key}')

    def accept_history(self,data):
        self.account=data['account'];self.role=None
        cache=self.cache.setdefault(self.account,{'wars':{},'ranks':{},'reports':{}})
        cache.setdefault('reports',{})
        for row in data['rows']:cache['wars'][row['warId']]=row
        self.selector.blockSignals(True);previous=self.war and self.war['warId'];self.selector.clear()
        live={r['warId'] for r in data['rows']}
        for row in sorted(cache['wars'].values(),key=lambda r:(r.get('seasonId',0),r['bTimeId']),reverse=True):
            row=dict(row,live=row['warId'] in live)
            self.selector.addItem(f"S{row.get('seasonId',0)} · {row['name']} · {row['warId']}" + ('' if row['live'] else '（本地）'),row)
        index=next((i for i in range(self.selector.count()) if self.selector.itemData(i)['warId']==previous),0)
        self.selector.setCurrentIndex(index);self.selector.blockSignals(False);self.save()
        self.message.setText(f"共 {self.selector.count()} 个战场。{data.get('note','')}")
        if self.selector.count():self._select(index)
        else:self.war=None;self._clear()

    def _clear(self):
        self.selected_legion=None;self.refresh_legion.setEnabled(False)
        self.tabs.setTabText(1,'个人排名')
        for table in (self.legions,self.roles,self.reports):table.setRowCount(0)
        self.tabs.setTabText(2,'个人战报')

    def _select(self,index):
        self.war=self.selector.itemData(index);self.role=None;self._clear()
        if not self.war:return
        cached=self.cache[self.account]['ranks'].get(self.war['warId'])
        if cached:self.show_ranks(cached,save=False)
        force=getattr(self,'_force_ranks',False);self._force_ranks=False
        scan=getattr(self,'_scan_after_refresh',False);self._scan_after_refresh=False
        if self.war.get('live') and (not cached or force):self.requested.emit('scan' if scan else 'ranks',dict(self.war))
        elif not cached:self.message.setText('该战场仅保留历史索引，尚无本地排名快照')

    def fill(self,table,columns,rows,raw=None):
        if table is self.roles:checkpoint(f'season-members-fill begin rows={len(rows)}')
        table.setSortingEnabled(False);table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,(key,_) in enumerate(columns):
                value=row.get(key)
                text=format_time(value) if key=='time' else format_power(value) if key in ('power','other_power','fightPower') else ('—' if value is None else str(value))
                # Bulk member refreshes use Qt's native comparator. Avoid virtual
                # Python __lt__ callbacks while Qt replaces and sorts these items.
                item=QTableWidgetItem() if table is self.roles else NumericItem(text)
                if table is self.roles and isinstance(value,(int,float)) and key not in ('fightPower',):
                    item.setData(Qt.ItemDataRole.DisplayRole,value)
                elif table is self.roles:item.setText(text)
                item.setData(Qt.ItemDataRole.UserRole,value)
                if c==0:item.setData(Qt.ItemDataRole.UserRole+1,(raw or rows)[r])
                item.setToolTip(str(value) if value is not None else '游戏未下发')
                table.setItem(r,c,item)
        if table is self.roles:checkpoint('season-members-fill items-done sort-begin')
        table.setSortingEnabled(True)
        if table is self.roles:checkpoint('season-members-fill sort-done resize-begin')
        table.resizeColumnsToContents()
        if table is self.roles:checkpoint('season-members-fill done')

    def show_ranks(self,data,save=True):
        if not self.war or self.war['warId']!=data['warId']:return
        for row in data['roles']:
            if row.get('score') is not None:row.setdefault('scoreSource','服务端排名')
        self.fill(self.legions,LEGIONS,data['legions']);self.fill(self.roles,ROLES,data['roles'])
        if save:self.cache[self.account]['ranks'][data['warId']]=data;self.save()

    def _open_legion(self,row,_column):
        if not self.war:return
        item=self.legions.item(row,0)
        if not item:return
        self.selected_legion=item.data(Qt.ItemDataRole.UserRole+1)
        self.role=None;self.reports.setRowCount(0)
        self.refresh_legion.setEnabled(True);self.tabs.setCurrentIndex(1)
        self.roles.setRowCount(0)
        self._request_legion()

    def _request_legion(self,*,force=False):
        if not self.war or not self.selected_legion:return
        key=self.war['warId']+':'+str(self.selected_legion['id'])
        cached=self.cache[self.account].get('legion_statistics',{}).get(key)
        if cached and not force:
            self.show_legion_statistics(cached)
            from .season_legion_statistics import complete_statistics
            if complete_statistics(cached):return
        self.requested.emit('legion_stats',dict(self.war,legionId=self.selected_legion['id'],
            legionName=self.selected_legion.get('name',''),memberNum=self.selected_legion.get('memberNum'),force=force))

    def show_legion_statistics(self,data):
        if not self.war or not self.selected_legion or data['warId']!=self.war['warId'] or str(data['legionId'])!=str(self.selected_legion['id']):return
        self.update_scores(data)
        rows=sorted(data['rows'],key=lambda r:(r.get('score') is None,-(r.get('score') or 0),int(r['id'])))
        rows=[dict(r,rank=i+1 if r.get('score') is not None else None,legionName=data.get('legionName','')) for i,r in enumerate(rows)]
        checkpoint(f"season-legion-render begin war={data['warId']} legion={data['legionId']} rows={len(rows)}")
        self.fill(self.roles,ROLES,rows);self.roles.sortItems(4,Qt.SortOrder.DescendingOrder)
        checkpoint('season-legion-render score-sort-done')
        self.tabs.setTabText(1,'个人排名 · '+data.get('legionName',str(data['legionId'])))
        finished=sum(bool(r.get('statisticsComplete')) for r in rows)
        self.message.setText(f"{data.get('legionName','')} · 已发现 {len(rows)}/{data.get('memberNum') or '未知'} 人 · 已完成统计 {finished} 人 · 缓存时间 {data.get('fetchedAt','—')}\n"
            '名单可能不完整；当前预览不等于历史参战名单。杀敌及对战死亡取玩家战报；攻城取结算、既有缓存或守卫战报首页总次数。无服务端积分时按游戏规则补算，统计不完整显示 —。'+data.get('note',''))
        checkpoint('season-legion-render done')

    def update_scores(self,data):
        from .season_legion_statistics import apply_score
        rule=self.cache[self.account]['ranks'].get(str(data['warId']),{}).get('scoreRule')
        changed=False
        for row in data.get('rows',[]):changed=apply_score(row,rule) or changed
        if changed:self.save()

    def show_all_roles(self):
        if not self.war:return
        self.selected_legion=None;self.refresh_legion.setEnabled(False);self.tabs.setTabText(1,'个人排名')
        self.tabs.setCurrentIndex(1)
        data=self.cache[self.account]['ranks'].get(self.war['warId'])
        scan=self.cache[self.account].get('battlefield_scans',{}).get(str(self.war['warId']))
        if scan:
            self.update_scores(scan)
            rows=sorted(scan['rows'],key=lambda r:(r.get('score') is None,-(r.get('score') or 0),int(r['id'])))
            rows=[dict(r,rank=i+1 if r.get('score') is not None else None) for i,r in enumerate(rows)]
            self.fill(self.roles,ROLES,rows);self.roles.sortItems(4,Qt.SortOrder.DescendingOrder)
        elif data:self.fill(self.roles,ROLES,data['roles'])

    def _open_player(self,row,_column):
        if not self.war:return
        item=self.roles.item(row,0)
        if not item:return
        role=item.data(Qt.ItemDataRole.UserRole+1);self.role=role
        self.tabs.setCurrentIndex(2);self.reports.setRowCount(0)
        cached=self.cache[self.account]['reports'].get(self.war['warId']+':'+str(role['id']))
        filtered=self.cache[self.account]['reports'].get(self.war['warId']+':'+str(role['id'])+':players')
        if not (cached and cached.get('complete')) and filtered:cached=filtered
        if cached:self.show_reports(cached,save=False)
        if self.war.get('live') and not (cached and cached.get('complete')):
            self.requested.emit('reports',dict(self.war,roleId=role['id'],reportFilter='players'))

    def show_reports(self,data,save=True):
        if not self.war or not self.role or data['warId']!=self.war['warId'] or data['roleId']!=self.role['id']:return
        def player_side(report,info,preview):
            value=(report.get(info) or {}).get('roleId') or (report.get(preview) or {}).get('id')
            return str(value).isdigit() and int(value)>=100000
        rows=[r for r in data['rows'] if player_side(r,'roleInfo','rolePreview') and player_side(r,'tarRoleInfo','tarRolePreview')]
        self.fill(self.reports,REPORTS,[report_row(r,data['roleId']) for r in rows],rows)
        self.tabs.setTabText(2,f"个人战报 · 仅玩家对战 · {self.role.get('name') or data['roleId']}（{len(rows)}）")
        if save:
            self.save_report(self.account,data['warId']+':'+str(data['roleId'])+(':players' if data.get('reportFilter')=='players' else ''),data)
            self.save()

    def _open_replay(self,row,_column):
        item=self.reports.item(row,0)
        if not item or not self.role or not self.war:return
        report=item.data(Qt.ItemDataRole.UserRole+1)
        self.requested.emit('replay',dict(self.war,roleId=self.role['id'],battleId=report['battleId'],report=report))


class SeasonInsightFeature:
    def __init__(self,transport,state,panel,damage,busy=lambda:False):
        self.transport=transport;self.state=state;self.panel=panel;self.damage=damage
        self.busy=busy
        self.job=None;self.replay_job=None;self.generation=0;self.pending=None
        panel.requested.connect(self.request)

    def request(self,op,args):
        if op=='stop_scan':
            self.generation+=1;self.pending=None
            self.panel.message.setText('已停止扫描；已保存进度，再次拉取可继续。');return
        if self.state.closing or not self.state.installed:
            self.panel.message.setText('请先连接游戏并完成挂载');return
        if op=='replay' and self.replay_job and not self.replay_job.done():
            self.panel.message.setText('当前战报正在回放和分析，请等待结束');return
        if op=='replay' and self.busy():
            self.panel.message.setText('当前自动操作尚未结束，请结束后再播放战报');return
        if self.job and not self.job.done():
            if op=='replay':
                self.panel.message.setText('正在读取血月数据，请读取完成后播放');return
            self.generation+=1;self.pending=(op,args)
            self.panel.message.setText('正在切换血月数据…');return
        self.generation+=1
        self.job=asyncio.create_task(self.handle(op,args,self.state.installed,self.generation))

    def current(self,session,generation):
        return not self.state.closing and session==self.state.installed and generation==self.generation

    async def handle(self,op,args,session,generation):
        try:
            self.panel.message.setText('正在读取血月数据…')
            if op=='replay':
                self.replay_job=asyncio.create_task(self.replay(args,session))
                await self.replay_job;return
            if op=='legion_stats':
                from .season_legion_statistics import load_legion_statistics
                await load_legion_statistics(self,args,session,generation)
                return
            if op=='scan':
                from .season_legion_statistics import scan_battlefield
                data=await self.transport.season_insight('ranks',args)
                if not self.current(session,generation):return
                self.panel.show_ranks(data)
                await scan_battlefield(self,args,session,generation)
                return
            if op=='reports':
                from .season_legion_statistics import load_reports
                data=await load_reports(self,args,session,generation,self.panel.account)
                if data is not None and self.current(session,generation):self.panel.show_reports(data)
                return
            data=await self.transport.season_insight(op,args)
            if not self.current(session,generation):return
            if op=='history':
                platform=getattr(self.transport,'platform_name','')
                if platform:data=dict(data,account=platform+':'+data['account'])
                self.panel.accept_history(data)
            elif op=='ranks':self.panel.show_ranks(data)
            self.panel.message.setText('血月数据已更新；时间为北京时间，缺失字段显示 —')
        except Exception as exc:
            LOG.exception('血月数据透视失败：%s',op)
            self.panel.message.setText(f'读取失败：{exc}')
        finally:
            # accept_history may select a battlefield while this task still owns
            # the read slot. Load its ranks after the current call completes.
            if self.pending and not self.state.closing:
                op_next,args_next=self.pending;self.pending=None
                asyncio.get_running_loop().call_soon(self.request,op_next,args_next)

    async def replay(self,args,session):
        lease=False
        try:
            if self.damage.forced_replay:raise RuntimeError('已有临时分析正在进行')
            status=await self.transport.damage_status()
            if isinstance(status,dict) and status.get('hooked',0)>0:raise RuntimeError('当前正在战斗，请结束后再播放战报')
            self.damage.forced_replay=True;lease=True
            # A game context may have been recreated since the last regular
            # poll. The runtime toggle injector is idempotent in a live context.
            self.damage._injected=False
            await self.damage._ensure_injected()
            await self.damage.take(force=True)
            await self.transport.damage_reset()
            self.damage._pending=None;self.damage._battle_key=None;self.damage._snapshot_signature=None
            self.damage._snapshot_ids=None;self.damage._next_snapshot=0;self.damage._written=False
            replay=await self.transport.season_insight('replay',args)
            self.panel.message.setText('战报已请求，正在强制进行 PVP 分析…')
            seen=False;started=time.monotonic()
            while not self.state.closing and session==self.state.installed:
                status=await self.transport.damage_status()
                hooked=isinstance(status,dict) and status.get('hooked',0)>0
                retained=isinstance(status,dict) and any(
                    isinstance(side,dict) and side.get('eventCount',0)>0 for side in (status.get('sides') or {}).values())
                seen=seen or hooked or retained
                native=await self.transport.season_insight('replay_status',{})
                if native and native.get('token')==replay['token'] and native.get('status')=='failed':
                    raise RuntimeError(native.get('error') or '游戏回放失败')
                if seen and not hooked:
                    await self.damage.take()
                    self.panel.message.setText('回放结束，PVP 分析报告已生成；已结束本次临时分析'
                        if self.damage._written else '回放结束，已关闭临时分析；未生成报告，请查看 PVP伤害分析 页的提示')
                    return
                if not seen and time.monotonic()-started>30:
                    raise RuntimeError('未观察到回放战斗，战报可能过期或版本不匹配')
                await self.damage.take()
                await asyncio.sleep(.25)
        except Exception as exc:
            self.panel.message.setText(f'回放分析失败：{exc}')
            LOG.exception('血月战报回放失败')
        finally:
            if lease:
                self.damage.forced_replay=False
                if session==self.state.installed and not self.damage.store.snapshot()['damage']['enabled']:
                    await self.transport.damage_stop();self.damage._injected=False

    async def close(self):
        self.generation+=1;self.pending=None
        for task in (self.job,self.replay_job):
            if task and not task.done():task.cancel()
        await asyncio.gather(*(t for t in (self.job,self.replay_job) if t),return_exceptions=True)
