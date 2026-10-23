"""Persistent public-player census and resumable ID ranges (platform isolated)."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import re
import sqlite3
import math
import json

MIN_ID, MAX_ID, SCAN_SIZE = 10000000, 99999999, 100000


def now():
    return datetime.now().isoformat(timespec='seconds')


def server_number(row):
    matches = re.findall(r'(\d+)\s*服', str(row.get('sName', '')))
    if matches:
        return int(matches[-1])
    # Some versions return the displayed server ordinal directly in sId.
    value = row.get('sId')
    return int(value) if str(value).isdigit() and int(value) > 0 else None


class LegionScanStore:
    def __init__(self, path, platform='wechat'):
        self.path, self.platform = Path(path), platform
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS scan_tasks(
              id INTEGER PRIMARY KEY, platform TEXT NOT NULL, legion_id TEXT NOT NULL,
              name TEXT NOT NULL, seed_low INTEGER NOT NULL, seed_high INTEGER NOT NULL,
              range_low INTEGER NOT NULL, range_high INTEGER NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
              scanned_low INTEGER, scanned_high INTEGER, paused INTEGER NOT NULL DEFAULT 0,
              error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
              UNIQUE(platform,legion_id));
            CREATE TABLE IF NOT EXISTS scan_legions(
              platform TEXT NOT NULL,id TEXT NOT NULL,name TEXT NOT NULL DEFAULT '',
              power REAL NOT NULL DEFAULT 0,marked INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL DEFAULT '',PRIMARY KEY(platform,id));
            CREATE TABLE IF NOT EXISTS scan_players(
              platform TEXT NOT NULL,id INTEGER NOT NULL,name TEXT NOT NULL DEFAULT '',
              power REAL NOT NULL DEFAULT 0,legion_id TEXT NOT NULL DEFAULT '0',
              legion_name TEXT NOT NULL DEFAULT '',server_no INTEGER,server_name TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL DEFAULT '',checked_at TEXT NOT NULL DEFAULT '',
              found INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(platform,id));
            CREATE TABLE IF NOT EXISTS scan_task_players(
              task_id INTEGER NOT NULL,player_id INTEGER NOT NULL,PRIMARY KEY(task_id,player_id));
            CREATE INDEX IF NOT EXISTS scan_player_legion ON scan_players(platform,legion_id);
            CREATE TABLE IF NOT EXISTS scan_settings(platform TEXT PRIMARY KEY,min_power REAL NOT NULL DEFAULT 300000000);
            ''')
            columns={r['name'] for r in db.execute('PRAGMA table_info(scan_tasks)')}
            if 'anchor_cursor' not in columns:
                db.execute('ALTER TABLE scan_tasks ADD COLUMN anchor_cursor INTEGER NOT NULL DEFAULT 0')
                db.execute('ALTER TABLE scan_tasks ADD COLUMN anchor_low INTEGER')
                db.execute('ALTER TABLE scan_tasks ADD COLUMN anchor_high INTEGER')
                # Old scans are contiguous around the seed interval. Preserve their
                # completed boundaries before switching to batches of 100.
                db.execute('UPDATE scan_tasks SET anchor_cursor=cursor,anchor_low=MIN(seed_low,COALESCE(scanned_low,seed_low)),anchor_high=MAX(seed_high,COALESCE(scanned_high,seed_high))')
            settings={r['name'] for r in db.execute('PRAGMA table_info(scan_settings)')}
            if 'interval_seconds' not in settings:
                db.execute('ALTER TABLE scan_settings ADD COLUMN interval_seconds REAL NOT NULL DEFAULT 1')
            if 'workers' not in settings:
                db.execute('ALTER TABLE scan_settings ADD COLUMN workers INTEGER NOT NULL DEFAULT 2')
            db.execute('CREATE TABLE IF NOT EXISTS scan_receipts(task_id INTEGER,cursor INTEGER,pid INTEGER,value TEXT NOT NULL,PRIMARY KEY(task_id,cursor))')
            db.execute('CREATE TABLE IF NOT EXISTS scan_control(platform TEXT PRIMARY KEY,halt_reason TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS scan_dynamic_bounds(task_id INTEGER PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS scan_seed_bounds(task_id INTEGER PRIMARY KEY)')
            player_columns={r['name'] for r in db.execute('PRAGMA table_info(scan_players)')}
            if 'last_online_ms' not in player_columns:db.execute('ALTER TABLE scan_players ADD COLUMN last_online_ms INTEGER')
            if 'online' not in player_columns:db.execute('ALTER TABLE scan_players ADD COLUMN online INTEGER')
            db.execute('CREATE TABLE IF NOT EXISTS scan_member_updates(platform TEXT,legion_id TEXT,pid INTEGER,PRIMARY KEY(platform,legion_id,pid))')
        self._migrate_seed_bounds()
        self.calibrate()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _migrate_seed_bounds(self):
        with self.connect() as db:
            for row in db.execute('SELECT * FROM scan_tasks').fetchall():
                task=dict(row)
                if db.execute('SELECT 1 FROM scan_seed_bounds WHERE task_id=?',(task['id'],)).fetchone():continue
                receipts=db.execute('SELECT * FROM scan_receipts WHERE task_id=?',(task['id'],)).fetchall()
                ids=[task['seed_low'],task['seed_high']]+[r['pid'] for r in receipts]
                ids += [v for v in (task['scanned_low'],task['scanned_high']) if v is not None]
                task.update(range_low=min(ids),range_high=max(ids),anchor_cursor=task['cursor'],
                    anchor_low=min(task['seed_low'],task['scanned_low'] or task['seed_low']),
                    anchor_high=max(task['seed_high'],task['scanned_high'] or task['seed_high']))
                db.execute('UPDATE scan_tasks SET range_low=?,range_high=?,anchor_cursor=?,anchor_low=?,anchor_high=? WHERE id=?',
                    (task['range_low'],task['range_high'],task['anchor_cursor'],task['anchor_low'],task['anchor_high'],task['id']))
                db.execute('DELETE FROM scan_receipts WHERE task_id=?',(task['id'],))
                for receipt in receipts:
                    db.execute('INSERT INTO scan_receipts VALUES(?,?,?,?)',(task['id'],self.candidate_index(task,receipt['pid']),receipt['pid'],receipt['value']))
                db.execute('INSERT INTO scan_seed_bounds VALUES(?)',(task['id'],))

    def tasks(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM scan_tasks WHERE platform=? ORDER BY id', (self.platform,))]

    def min_power(self):
        with self.connect() as db:
            row=db.execute('SELECT min_power FROM scan_settings WHERE platform=?',(self.platform,)).fetchone()
            return float(row[0]) if row else 300000000

    def set_min_power(self, value):
        value=float(value)
        if value<0:raise ValueError('战力门槛不能为负数')
        with self.connect() as db:
            db.execute('INSERT INTO scan_settings(platform,min_power) VALUES(?,?) ON CONFLICT(platform) DO UPDATE SET min_power=excluded.min_power',(self.platform,value))

    def interval(self):
        with self.connect() as db:
            row=db.execute('SELECT interval_seconds FROM scan_settings WHERE platform=?',(self.platform,)).fetchone()
            return float(row[0]) if row else 1.0

    def workers(self):
        with self.connect() as db:
            row=db.execute('SELECT workers FROM scan_settings WHERE platform=?',(self.platform,)).fetchone()
            return int(row[0]) if row else 2

    def halt_reason(self):
        with self.connect() as db:
            row=db.execute('SELECT halt_reason FROM scan_control WHERE platform=?',(self.platform,)).fetchone()
            return row[0] if row else ''

    def halt(self, reason):
        with self.connect() as db:
            db.execute('INSERT INTO scan_control VALUES(?,?) ON CONFLICT(platform) DO UPDATE SET halt_reason=excluded.halt_reason',(self.platform,str(reason)))

    def set_workers(self,value):
        value=int(value)
        if not 1<=value<=10:raise ValueError('并发数须为1至10')
        with self.connect() as db:
            db.execute('INSERT INTO scan_settings(platform,workers) VALUES(?,?) ON CONFLICT(platform) DO UPDATE SET workers=excluded.workers',(self.platform,value))

    def receipt(self,task,cursor):
        with self.connect() as db:
            row=db.execute('SELECT pid,value FROM scan_receipts WHERE task_id=? AND cursor=?',(task['id'],cursor)).fetchone()
            if row:return True,json.loads(row['value'])
            return False,None

    def save_receipt(self,task,cursor,pid,row):
        if self.candidate({**task,'cursor':cursor})!=pid:raise ValueError('批量查询位置不匹配')
        if row is not None and (not isinstance(row,dict) or str(row.get('id'))!=str(pid)):raise ValueError('批量查询玩家ID不匹配')
        with self.connect() as db:
            current=db.execute('SELECT * FROM scan_tasks WHERE id=? AND platform=?',(task['id'],self.platform)).fetchone()
            if current is None:raise ValueError('扫描任务不存在')
            if self.candidate({**dict(current),'cursor':cursor})!=pid:
                cursor=self.candidate_index(dict(current),pid)
            db.execute('INSERT OR REPLACE INTO scan_receipts VALUES(?,?,?,?)',(task['id'],cursor,pid,json.dumps(row,ensure_ascii=False,allow_nan=False)))
            if row is not None:
                self._player(db,row)
                db.execute('INSERT OR IGNORE INTO scan_task_players VALUES(?,?)',(task['id'],pid))

    def set_interval(self, value):
        value=float(value)
        if not math.isfinite(value) or not 0.1<=value<=3600:
            raise ValueError('扫描间隔须在0.1至3600秒之间')
        with self.connect() as db:
            db.execute('INSERT INTO scan_settings(platform,interval_seconds) VALUES(?,?) ON CONFLICT(platform) DO UPDATE SET interval_seconds=excluded.interval_seconds',(self.platform,value))

    @staticmethod
    def candidate(task):
        cursor = task['cursor']
        width = task['seed_high'] - task['seed_low'] + 1
        if cursor >= task['range_high'] - task['range_low'] + 1:
            return None
        if cursor < width:
            return task['seed_low'] + cursor
        keys=task.keys()
        low=(task['anchor_low'] if 'anchor_low' in keys else None) or task['seed_low']
        high=(task['anchor_high'] if 'anchor_high' in keys else None) or task['seed_high']
        anchor=task['anchor_cursor'] if 'anchor_cursor' in keys else 0
        offset=cursor-max(width,anchor)
        left,right=low-task['range_low'],task['range_high']-high
        cycles=min(left//100,right//100)
        if offset<cycles*200:
            cycle,within=divmod(offset,200)
            return high+cycle*100+within+1 if within<100 else low-cycle*100-(within-100)-1
        offset-=cycles*200;left-=cycles*100;right-=cycles*100
        low-=cycles*100;high+=cycles*100
        while left or right:
            if not left:return high+offset+1
            if not right:return low-offset-1
            count=min(100,right)
            if offset<count:return high+offset+1
            offset-=count;right-=count;high+=count
            count=min(100,left)
            if offset<count:return low-offset-1
            offset-=count;left-=count;low-=count
        return None

    def create_task(self, info):
        seeds = sorted({int(m['id']) for m in info['members'] if m.get('job') in (1, 2) and str(m.get('id', '')).isdigit()})
        if len(seeds) < 3:
            raise ValueError('阴司预览未返回三名阎君/判官的玩家ID，无法建立区段')
        low, high = seeds[0], seeds[-1]
        if low < MIN_ID or high > MAX_ID:
            raise ValueError('管理成员的玩家ID不是8位整数')
        width = high-low+1
        start,end=low,high
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO scan_tasks(platform,legion_id,name,seed_low,seed_high,range_low,range_high,created_at) VALUES(?,?,?,?,?,?,?,?)',
                       (self.platform,str(info['id']),info.get('name',''),low,high,start,end,now()))
            task = dict(db.execute('SELECT * FROM scan_tasks WHERE platform=? AND legion_id=?',(self.platform,str(info['id']))).fetchone())
            db.execute('INSERT OR IGNORE INTO scan_seed_bounds VALUES(?)',(task['id'],))
            self._legion(db, info)
            for member in info['members']:
                if str(member.get('id','')).isdigit():
                    row = {**member,'legionId':str(info['id']),'legionName':info.get('name','')}
                    self._player(db,row, fresh=False)
                    db.execute('INSERT OR IGNORE INTO scan_task_players VALUES(?,?)',(task['id'],int(row['id'])))
        self.calibrate()
        return next(t for t in self.tasks() if t['id']==task['id'])

    def _legion(self, db, info):
        db.execute('''INSERT INTO scan_legions(platform,id,name,power,updated_at) VALUES(?,?,?,?,?)
          ON CONFLICT(platform,id) DO UPDATE SET name=excluded.name,power=excluded.power,updated_at=excluded.updated_at''',
          (self.platform,str(info['id']),info.get('name',''),float(info.get('fightPower',info.get('totalPower',0)) or 0),now()))

    def save_legion(self, info):
        with self.connect() as db:
            self._legion(db, info)
            # Preview is partial. Never delete unreturned members from local knowledge.
            for member in info['members']:
                if str(member.get('id','')).isdigit():
                    self._player(db,{**member,'legionId':str(info['id']),'legionName':info.get('name','')},fresh=False)
        self.calibrate()

    @staticmethod
    def candidate_index(task,pid):
        """Find a pending ID's position after reanchoring, without walking the range."""
        width=task['seed_high']-task['seed_low']+1
        if task['seed_low']<=pid<=task['seed_high']:return pid-task['seed_low']
        low=task['anchor_low'] or task['seed_low'];high=task['anchor_high'] or task['seed_high']
        left=low-task['range_low'];right=task['range_high']-high
        cycles=min(left//100,right//100);base=max(width,task['anchor_cursor'])
        distance=pid-high-1 if pid>high else low-pid-1
        if distance<0:raise ValueError('已完成的ID不应保留待提交回执')
        if distance<cycles*100:
            return base+distance//100*200+(0 if pid>high else 100)+distance%100
        base+=cycles*200;low-=cycles*100;high+=cycles*100;left-=cycles*100;right-=cycles*100
        while left or right:
            if not left:return base+pid-high-1
            if not right:return base+low-pid-1
            count=min(100,right)
            if high<pid<=high+count:return base+pid-high-1
            base+=count;right-=count;high+=count
            count=min(100,left)
            if low-count<=pid<low:return base+low-pid-1
            base+=count;left-=count;low-=count
        raise ValueError('玩家不在校准后的范围内')

    def calibrate(self):
        """Expand each task to include known members of its discovered legions."""
        with self.connect() as db:
            for source in db.execute('SELECT * FROM scan_tasks WHERE platform=?',(self.platform,)).fetchall():
                task=dict(source)
                bounds=db.execute('''SELECT MIN(p.id),MAX(p.id) FROM scan_players p WHERE p.platform=? AND p.found=1
                  AND p.id BETWEEN ? AND ? AND (p.id IN (SELECT player_id FROM scan_task_players WHERE task_id=?)
                  OR p.legion_id IN (SELECT q.legion_id FROM scan_players q JOIN scan_task_players t ON t.player_id=q.id
                  WHERE q.platform=? AND t.task_id=? AND q.legion_id<>'0') OR p.legion_id=?)''',
                  (self.platform,MIN_ID,MAX_ID,task['id'],self.platform,task['id'],task['legion_id'])).fetchone()
                low=min(task['range_low'],bounds[0] or task['range_low'])
                high=max(task['range_high'],bounds[1] or task['range_high'])
                if (low,high)==(task['range_low'],task['range_high']):continue
                task.update(range_low=low,range_high=high,anchor_cursor=task['cursor'],
                    anchor_low=min(task['seed_low'],task['scanned_low'] or task['seed_low']),
                    anchor_high=max(task['seed_high'],task['scanned_high'] or task['seed_high']))
                receipts=db.execute('SELECT * FROM scan_receipts WHERE task_id=?',(task['id'],)).fetchall()
                db.execute('DELETE FROM scan_receipts WHERE task_id=?',(task['id'],))
                for receipt in receipts:
                    cursor=self.candidate_index(task,receipt['pid'])
                    db.execute('INSERT INTO scan_receipts VALUES(?,?,?,?)',(task['id'],cursor,receipt['pid'],receipt['value']))
                db.execute('''UPDATE scan_tasks SET range_low=?,range_high=?,anchor_cursor=?,anchor_low=?,anchor_high=? WHERE id=?''',
                    (low,high,task['anchor_cursor'],task['anchor_low'],task['anchor_high'],task['id']))
                db.execute('INSERT OR IGNORE INTO scan_dynamic_bounds VALUES(?)',(task['id'],))

    def _player(self, db, row, fresh=True):
        pid = int(row['id'])
        lid = str(row.get('legionId') or '0')
        if lid != '0':
            db.execute('INSERT OR IGNORE INTO scan_legions(platform,id,name) VALUES(?,?,?)',(self.platform,lid,row.get('legionName','')))
        stamp = now() if fresh else ''
        db.execute('''INSERT INTO scan_players(platform,id,name,power,legion_id,legion_name,server_no,server_name,updated_at,checked_at,found)
          VALUES(?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(platform,id) DO UPDATE SET
          name=excluded.name,power=excluded.power,legion_id=excluded.legion_id,legion_name=excluded.legion_name,
          server_no=COALESCE(excluded.server_no,scan_players.server_no),server_name=CASE WHEN excluded.server_name='' THEN scan_players.server_name ELSE excluded.server_name END,
          updated_at=CASE WHEN excluded.updated_at='' THEN scan_players.updated_at ELSE excluded.updated_at END,
          checked_at=CASE WHEN excluded.checked_at='' THEN scan_players.checked_at ELSE excluded.checked_at END,found=1''',
          (self.platform,pid,row.get('name',''),float(row.get('fightPower') or 0),lid,row.get('legionName',''),server_number(row),row.get('sName',''),stamp,stamp))
        value=row.get('lastOnlineTime')
        if isinstance(value,(int,float)) and math.isfinite(value) and value>0:
            # Interfaces normally use milliseconds; accept legacy seconds too.
            value=int(value*1000 if value<100000000000 else value)
            db.execute('UPDATE scan_players SET last_online_ms=? WHERE platform=? AND id=?',(value,self.platform,pid))
        if isinstance(row.get('online'),bool):
            db.execute('UPDATE scan_players SET online=? WHERE platform=? AND id=?',(int(row['online']),self.platform,pid))

    def enqueue_members(self,lid):
        with self.connect() as db:
            db.execute('''INSERT OR IGNORE INTO scan_member_updates SELECT platform,legion_id,id FROM scan_players
              WHERE platform=? AND legion_id=? AND found=1''',(self.platform,str(lid)))
            return db.execute('SELECT COUNT(*) FROM scan_member_updates WHERE platform=? AND legion_id=?',(self.platform,str(lid))).fetchone()[0]

    def queued_members(self,limit):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT platform,MIN(legion_id) AS legion_id,pid FROM scan_member_updates WHERE platform=? GROUP BY pid ORDER BY MIN(rowid) LIMIT ?',(self.platform,limit))]

    def finish_member(self,lid,pid):
        with self.connect() as db:
            db.execute('DELETE FROM scan_member_updates WHERE platform=? AND pid=?',(self.platform,int(pid)))

    def record(self, pid, row, task=None):
        with self.connect() as db:
            if row:
                if int(row['id']) != int(pid):
                    raise ValueError('玩家查询ID不匹配')
                self._player(db,row)
            else:
                db.execute('UPDATE scan_players SET checked_at=?,found=0 WHERE platform=? AND id=?',(now(),self.platform,pid))
            if task:
                current = db.execute('SELECT * FROM scan_tasks WHERE id=? AND platform=?',(task['id'],self.platform)).fetchone()
                if current is None or current['cursor']!=task['cursor'] or self.candidate(current)!=pid:
                    raise ValueError('扫描进度发生变化，未推进断点')
                if row:
                    db.execute('INSERT OR IGNORE INTO scan_task_players VALUES(?,?)',(task['id'],pid))
                db.execute('UPDATE scan_tasks SET cursor=cursor+1,scanned_low=?,scanned_high=?,error=\'\' WHERE id=?',
                           (min(pid,current['scanned_low'] or pid),max(pid,current['scanned_high'] or pid),task['id']))
                db.execute('DELETE FROM scan_receipts WHERE task_id=? AND cursor=?',(task['id'],current['cursor']))

    def mark(self, lid, enabled):
        with self.connect() as db:
            db.execute('UPDATE scan_legions SET marked=? WHERE platform=? AND id=?',(int(enabled),self.platform,str(lid)))

    def pause(self, task_id, enabled):
        with self.connect() as db:
            db.execute('UPDATE scan_tasks SET paused=? WHERE id=? AND platform=?',(int(enabled),task_id,self.platform))

    def task_error(self, task_id, message):
        with self.connect() as db:
            db.execute('UPDATE scan_tasks SET error=? WHERE id=? AND platform=?',(str(message)[:500],task_id,self.platform))

    def stale_legion(self, refreshed=None):
        threshold=self.min_power()
        with self.connect() as db:
            for row in db.execute('SELECT * FROM scan_legions WHERE platform=? ORDER BY id',(self.platform,)):
                if row['updated_at'] and not row['marked'] and row['power'] < threshold:continue
                if row['id'] not in (refreshed or set()) or row['updated_at'][:10] != now()[:10]:
                    return dict(row)
            return None

    def stale_marked_player(self):
        threshold=self.min_power()
        with self.connect() as db:
            row = db.execute('''SELECT p.* FROM scan_players p JOIN scan_legions l ON l.platform=p.platform AND l.id=p.legion_id
              WHERE p.platform=? AND (l.marked=1 OR l.power>=?) AND substr(p.checked_at,1,10)<>? ORDER BY p.id LIMIT 1''',(self.platform,threshold,now()[:10])).fetchone()
            return dict(row) if row else None

    def tree(self, task_id):
        with self.connect() as db:
            players = [dict(row) for row in db.execute('''SELECT p.* FROM scan_players p WHERE p.platform=? AND p.found=1 AND
              (p.id IN (SELECT player_id FROM scan_task_players WHERE task_id=?) OR p.legion_id IN
              (SELECT q.legion_id FROM scan_players q JOIN scan_task_players t ON t.player_id=q.id WHERE q.platform=? AND t.task_id=? AND q.legion_id<>'0'))
              ORDER BY p.power DESC''',(self.platform,task_id,self.platform,task_id))]
            legions = {row['id']:dict(row) for row in db.execute('SELECT * FROM scan_legions WHERE platform=?',(self.platform,))}
        groups = {}
        for player in players:
            lid=player['legion_id']
            group=groups.setdefault(lid,{**legions.get(lid,{'id':lid,'name':'未加入阴司' if lid=='0' else player['legion_name'],'power':0,'marked':0,'updated_at':''}),'players':[]})
            group['players'].append(player)
        return sorted(groups.values(),key=lambda g:g['power'],reverse=True)

    def groups(self, task_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT p.legion_id AS id,
              COALESCE(l.name,p.legion_name) AS name,COALESCE(l.power,0) AS power,
              COALESCE(l.marked,0) AS marked,COALESCE(l.updated_at,'') AS updated_at,
              COUNT(*) AS count FROM scan_players p LEFT JOIN scan_legions l ON l.platform=p.platform AND l.id=p.legion_id
              WHERE p.platform=? AND p.found=1 AND (p.id IN (SELECT player_id FROM scan_task_players WHERE task_id=?)
              OR p.legion_id IN (SELECT q.legion_id FROM scan_players q JOIN scan_task_players t ON t.player_id=q.id
              WHERE q.platform=? AND t.task_id=? AND q.legion_id<>'0')) GROUP BY p.legion_id ORDER BY power DESC,p.legion_id''',
              (self.platform,task_id,self.platform,task_id))]

    def servers(self, task_id):
        with self.connect() as db:
            return tuple(db.execute('''SELECT MIN(p.server_no),MAX(p.server_no) FROM scan_players p
              JOIN scan_task_players t ON t.player_id=p.id WHERE p.platform=? AND t.task_id=? AND p.found=1''',(self.platform,task_id)).fetchone())

    def members(self, task_id, lid, offset=0, limit=500):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT * FROM scan_players WHERE platform=? AND legion_id=? AND found=1
              AND (legion_id<>'0' OR id IN (SELECT player_id FROM scan_task_players WHERE task_id=?))
              ORDER BY power DESC,id LIMIT ? OFFSET ?''',(self.platform,lid,task_id,limit,offset))]
