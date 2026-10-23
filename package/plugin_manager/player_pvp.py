"""Per-player Erlang equipment observations, isolated by platform."""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sqlite3

BEIJING=timezone(timedelta(hours=8))
ERLANG_SET_BONUS=10.0


class PlayerPvpHistory:
    def __init__(self,path,platform):
        self.path=Path(path);self.platform=platform
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS player_erlang_history(
              platform TEXT NOT NULL,player_id TEXT NOT NULL,equipment TEXT NOT NULL,
              updated_at TEXT NOT NULL,PRIMARY KEY(platform,player_id))''')

    def observe(self,stats):
        pid=str(stats.get('player_id') or '')
        if not pid.isascii() or not pid.isdigit() or int(pid)<=0:return None
        with sqlite3.connect(self.path) as db:
            if stats.get('face_kind')=='erlang' and stats.get('face_complete') and stats.get('erlang_snapshot') and len(stats.get('faces',[]))==8:
                data={'pvp':stats['face_pvp'],'set_bonus':ERLANG_SET_BONUS,'faces':stats['faces'],'snapshot':stats.get('erlang_snapshot'),
                    'equipment_plan':stats.get('equipment_plan'),'suits':stats.get('suits',[]),
                    'observed_base_up':stats.get('base_up'),'observed_base_down':stats.get('base_down')}
                db.execute('''INSERT INTO player_erlang_history VALUES(?,?,?,?) ON CONFLICT(platform,player_id)
                  DO UPDATE SET equipment=excluded.equipment,updated_at=excluded.updated_at''',
                  (self.platform,pid,json.dumps(data,ensure_ascii=False,allow_nan=False),datetime.now(BEIJING).isoformat(timespec='seconds')))
            row=db.execute('SELECT equipment,updated_at FROM player_erlang_history WHERE platform=? AND player_id=?',(self.platform,pid)).fetchone()
            return {**json.loads(row[0]),'updated_at':row[1]} if row else None

    def decorate(self,result):
        if not isinstance(result,dict) or not isinstance(result.get('pvp_estimate'),dict):return result
        stats=result['pvp_estimate'];history=self.observe(stats)
        estimate=estimate_pvp(stats,history)
        lines=['── PVP加成预估 ──']
        lo,hi=estimate['low'],estimate['high']
        lines.append('PVP增伤＋减免预估：'+percent(lo)+(('～'+percent(hi)) if lo!=hi else ''))
        lines.append('属性合计 '+percent(estimate['base'])+'（增伤 '+percent(stats['base_up'])+'＋减免 '+percent(stats['base_down'])+'）')
        lines.append('三尸补差 '+percent(estimate['desire_extra'])+'；法器补差 '+percent(estimate['magic_extra']))
        desire=stats['desire']
        lines.append('三尸方案：当前 '+percent(desire['current'])+'；最高 '+percent(desire['best'])+
            '（方案'+str(desire.get('best_id','—'))+'），补差 '+percent(estimate['desire_extra']))
        magic=stats['magic']
        lines.append('法器方案：当前 '+percent(magic['current'])+'；最高 '+percent(magic['best'])+
            '（方案'+str(magic.get('best_id','—'))+'「'+str(magic.get('best_name') or '未命名')+'」），补差 '+percent(estimate['magic_extra']))
        lines.append(estimate['face_note'])
        if estimate.get('missing'):
            lines.append('以下缺失项未计入，已按现有数据预估：'+'、'.join(estimate['missing']))
        magic=stats.get('magic',{})
        lines.append('当前法器方案：'+str(magic.get('current_id') if magic.get('current_id') is not None else '未下发')+
            ('「'+str(magic['current_name'])+'」' if magic.get('current_name') else '')+'（实际装备）')
        if magic.get('best_id') is not None:
            lines.append('最高PVP候选方案：'+str(magic['best_id'])+'「'+str(magic.get('best_name') or '未命名')+'」（仅作补差预估）')
        if history:
            lines+=['','── 历史记录二郎套装 ──','记录时间：'+history['updated_at']+'（北京时间）',
                '八件脸谱PVP合计：'+percent(history['pvp'])+'；方案：'+str(history.get('equipment_plan','未下发'))]
            bonus=float(history.get('set_bonus',ERLANG_SET_BONUS))
            lines.append('二郎套装额外加成：'+percent(bonus)+'；替换用PVP合计：'+percent(float(history['pvp'])+bonus))
            for face in history.get('faces',[]):
                lines.append('部位'+str(face['slot'])+' '+face['name']+' · Lv'+str(face['level'])+
                    ' · 品质'+str(face.get('quality','—'))+' · 星级'+str(face.get('star','—'))+' · PVP '+percent(face['pvp']))
                base=face.get('base_attributes',[])
                if base:lines.append('  基础：'+'、'.join(attribute_text(a) for a in base))
                entries=face.get('entries',[])
                if entries:lines.append('  词条：'+'、'.join(attribute_text(a) for a in entries))
        return {**result,'pvp_result':estimate,'text':'\n'.join(lines)+'\n\n'+result.get('text','')}


def percent(value):
    return f'{float(value or 0):.2f}'.rstrip('0').rstrip('.')+'%'


def attribute_text(row):
    value=percent(float(row.get('value',0))/100) if row.get('style')==2 else str(row.get('value','—'))
    return str(row.get('name') or row.get('id','—'))+' '+value


def estimate_pvp(stats,history=None):
    missing=list(stats.get('missing') or [])
    base=float(stats.get('base_up') or 0)+float(stats.get('base_down') or 0)
    desire=max(0,float(stats.get('desire',{}).get('best') or 0)-float(stats.get('desire',{}).get('current') or 0))
    magic=max(0,float(stats.get('magic',{}).get('best') or 0)-float(stats.get('magic',{}).get('current') or 0))
    low=high=base+desire+magic
    kind=stats.get('face_kind')
    if kind=='wukong':
        low-=float(stats.get('face_pvp') or 0);high=low
        if history:
            bonus=float(history.get('set_bonus',ERLANG_SET_BONUS))
            low+=float(history['pvp'])+bonus;high=low
            note='悟空脸谱扣除 '+percent(stats['face_pvp'])+'，替换为历史二郎脸谱 '+percent(history['pvp'])+'＋套装 '+percent(bonus)
        else:
            low+=40+ERLANG_SET_BONUS;high+=50+ERLANG_SET_BONUS
            note='悟空脸谱扣除 '+percent(stats['face_pvp'])+'；无二郎历史，脸谱40%–50%＋套装10%，按50%–60%补入'
    elif kind=='erlang':note='当前穿二郎：保留属性中的脸谱及套装10%加成，不作扣除、不重复添加'
    else:note='当前不是完整二郎／悟空套装：保留当前脸谱，不作替换'
    return {'low':round(low,6),'high':round(high,6),'base':base,'desire_extra':desire,'magic_extra':magic,'face_note':note,'missing':missing}
