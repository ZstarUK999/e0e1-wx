"""Offline processing of recording-only game packets (no game objects or JS)."""
from __future__ import annotations

import copy
import itertools
import json
import math
import re
from collections import defaultdict

CATEGORIES={'attack':'普攻','card':'符咒','book':'天书','pet':'鬼仆','desire':'三尸','epic':'法器',
            'flag':'战旗','leifa':'雷法尊者','fashion':'傀儡装','store':'鬼店','base':'法相','monster':'怪物','other':'其它'}
TYPE_CATEGORY={1:'attack',2:'monster',3:'card',4:'book',5:'pet',6:'desire',7:'fashion',8:'store',9:'pet',
               10:'pet',11:'pet',12:'base',13:'book',14:'base',15:'epic',16:'epic',17:'book',18:'flag'}
PATH_NAMES={1:'主觉醒',2:'主阶',3:'分阶',4:'副觉醒'}
ORIGINS=[('MagicArtifactBaseCfg',['skill'],'法器'),('MagicArtifactStoneCfg',['skill'],'法器宝石'),
         ('MagicArtifactTemperSkillCfg',['skill'],'法器淬炼'),('EquipmentSuitSkillCfg',['skillId'],'脸谱套装'),
         ('FashionCfg',['skill','attackSkill'],'傀儡装'),('BaseSkinCfg',['skill'],'基地法相'),
         ('DesireCfg',['skill'],'三尸'),('SeasonWarRestraintCfg',['pveSkill','pvpSkill'],'战旗')]


class RecordingStream:
    """Acknowledged offsets live in Python; retries never drain the game buffers."""
    def __init__(self):
        self.context=None
        self.data=None

    def cursor(self,context):
        if self.context!=context or not self.data:return None
        data=self.data;pvp=data.get('pvp') or {}
        out=dict(stream=data['stream'],includeCatalog=not bool(data.get('catalog')),pair=pvp.get('instanceKey'),
                 samples=len(pvp.get('samples',[])),attrs=len(pvp.get('attrSeconds',[])))
        for key in ('self','other'):
            side=data.get(key)
            if side:out[key]=dict(instanceId=side['instanceId'],events=len(side['events']),hits=len(side['hits']))
        return out

    def merge(self,packet,context):
        if packet.get('recordingSchema')!=1:return packet
        old=self.data if self.context==context and self.data and self.data['stream']==packet['stream'] else {}
        result=dict(packet,catalog=packet.get('catalog') or old.get('catalog') or {})
        # Build a new committed packet. On malformed offsets the old cursor is
        # retained, allowing the exact delta to be retried without missing rows.
        def merge_rows(previous,incoming,name,offset):
            start=incoming.get(offset,0)
            existing=previous.get(name,[])
            if not isinstance(start,int) or start<0 or start>len(existing):
                raise ValueError(f'伤害增量偏移无效：{name} {start}/{len(existing)}')
            return existing[:start]+incoming.get(name,[])
        for key in ('self','other'):
            side=packet.get(key)
            if side is None:result[key]=None;continue
            prev=old.get(key) or {}
            if prev.get('instanceId')!=side['instanceId']:prev={}
            result[key]=dict(side,events=merge_rows(prev,side,'events','eventStart'),
                             hits=merge_rows(prev,side,'hits','hitStart'),eventStart=0,hitStart=0)
        pvp=packet.get('pvp') or {};prev=old.get('pvp') or {}
        if prev.get('instanceKey')!=pvp.get('instanceKey'):prev={}
        result['pvp']=dict(pvp,samples=merge_rows(prev,pvp,'samples','sampleStart'),
                           attrSeconds=merge_rows(prev,pvp,'attrSeconds','attrStart'),sampleStart=0,attrStart=0)
        self.data=result;self.context=context
        return result


def _flatten(value):
    if isinstance(value,list):
        for item in value:yield from _flatten(item)
    elif isinstance(value,(float,int)) and not isinstance(value,bool) and value>0:yield int(value)


class Catalog:
    def __init__(self,tables):
        self.tables={name:{str(r['id']):r for r in rows} for name,rows in tables.items()}
        self.origins=defaultdict(list);self.fashion={};self.evolution={};self.buff_roots={}
        for table,fields,label in ORIGINS:
            for row in self.tables.get(table,{}).values():
                name=row.get('name') or row.get('itemName') or self.name('ItemCfg',row.get('c_item_itemId'))
                origin=label+(' · '+str(name) if name else '')
                for field in fields:
                    for sid in _flatten(row.get(field)):
                        if origin not in self.origins[sid]:self.origins[sid].append(origin)
                        if table=='FashionCfg':self.fashion[sid]=name
        for row in self.tables.get('EvolutionSkillCfg',{}).values():
            if not row.get('skillId'):continue
            sid=int(row['skillId']);branch=self.row('SkillBookEvolutionCfg',row.get('evolutionId'))
            bid=branch.get('id') or row.get('evolutionId');previous=self.evolution.get(sid,{})
            self.evolution[sid]=dict(branchId=bid,branchName=branch.get('name') or branch.get('nodeName'),
                branchLevel=None if previous.get('branchId')==bid else row.get('skillLevel'),
                path=branch.get('evolutionPath'),bookId=branch.get('skillBookBelong'))
        for _ in range(4):
            changed=False
            for row in self.tables.get('SkillCfg',{}).values():
                meta=self.evolution.get(int(row['id']))
                if not meta:continue
                for prop in row.get('_properties',[]):
                    text=str(prop.get('expression') or '')
                    if prop.get('name')=='sumSkill' and text.isdigit() and self.row('SkillCfg',text) and int(text) not in self.evolution:
                        self.evolution[int(text)]=dict(meta);changed=True
            if not changed:break
        self.parents=defaultdict(set)
        links={'SkillCfg':{'_passive':'PassiveSkillCfg','_active':'ActiveSkillCfg'},'ActiveSkillCfg':{'_emitters':'EmitterCfg'},'EmitterCfg':{'bulletIds':'BulletCfg'}}
        def edge(parent,table,identity):
            if self.row(table,identity):self.parents[f'{table}:{identity}'].add(parent)
        for table in ('SkillCfg','PassiveSkillCfg','ActiveSkillCfg','EmitterCfg','BulletCfg','BuffCfg'):
            for row in self.tables.get(table,{}).values():
                parent=f"{table}:{row['id']}"
                for field,target in links.get(table,{}).items():
                    for identity in row.get(field,[]):edge(parent,target,identity)
                for field,expressions in row.items():
                    if not re.match(r'^_.*[Ee]ffects$',field) or not isinstance(expressions,list):continue
                    for expression in expressions:
                        for method,identity in re.findall(r'\b(SELF_BUFF_FORCE|SELF_BUFF|OWNER_BUFF|PLAYER_BUFF|BUFF|ACTIVE|ADD_SKILL)\(\s*(\d+)\s*(?=[,)])',str(expression)):
                            edge(parent,'ActiveSkillCfg' if method=='ACTIVE' else 'SkillCfg' if method=='ADD_SKILL' else 'BuffCfg',identity)
                        for identity in re.findall(r'\b(?:PROB_BUFF|PROB_OWNER_BUFF|ATTR_PROB_BUFF)\(\s*[^,()]+,\s*(\d+)\s*(?=[,)])',str(expression)):edge(parent,'BuffCfg',identity)
                        for first,second in re.findall(r'\bBUFF_CONDITION\(\s*[^,()]+,\s*(\d+)\s*,\s*(\d+)\s*\)',str(expression)):
                            edge(parent,'BuffCfg',first);edge(parent,'BuffCfg',second)

    def row(self,table,identity):return self.tables.get(table,{}).get(str(identity),{})

    def name(self,table,identity):
        row=self.row(table,identity)
        for key in ('name','Name','cfgName','title','itemName'):
            text=str(row.get(key) or '')
            if re.search('[一-龥]',text):return text
        return None

    def origin(self,sid):return ' / '.join(self.origins.get(int(sid),[])) or None

    def roots(self,buff_id):
        key=str(buff_id)
        if key not in self.buff_roots:
            queue=[f'BuffCfg:{key}'];seen=set();result=[]
            for node in queue:
                if node in seen:continue
                seen.add(node)
                if node.startswith('SkillCfg:'):
                    sid=int(node.split(':')[1]);name=self.name('SkillCfg',sid)
                    if name:result.append(dict(skillId=sid,name=name,origin=self.origin(sid)))
                queue.extend(sorted(self.parents[node]-seen))
            self.buff_roots[key]=result
        return self.buff_roots[key]

    def classify(self,sid,active):
        row=self.row('SkillCfg',sid);sft=row.get('skillFunctionType',-1);cat=TYPE_CATEGORY.get(sft,'other')
        book=row.get('bookId') or row.get('sourceBookId') or None
        if cat=='book' and not book and self.row('SkillBookCfg',100*(sid//100)):book=100*(sid//100)
        if self.fashion.get(sid)=='雷法尊者':cat='leifa';book=None
        evo=self.evolution.get(sid,{})
        if evo.get('bookId'):book=evo['bookId']
        origin=self.origin(sid)
        if any(label.startswith('战旗 · ') for label in (origin or '').split(' / ')):cat='flag';book=None
        level=evo.get('branchLevel')
        for branch in active:
            if branch.get('branchId')==evo.get('branchId'):level=branch.get('level')
        return dict(skillName=self.name('SkillCfg',sid) or f'技能{sid}',cat=cat,book=book,
            bookName=(self.name('SkillBookCfg',book) or f'天书{book}') if book else None,
            branch=evo.get('branchId'),branchName=evo.get('branchName') or (f"分支{evo['branchId']}" if evo.get('branchId') else None),
            branchLevel=level,branchPath=evo.get('path'),branchPathName=PATH_NAMES.get(evo.get('path'),'未知') if evo else None,
            origin=origin,elem={1:'火',2:'水',3:'土',4:'风'}.get(row.get('elementalType'),'') if cat=='card' else '',
            kind={4:'主技能',13:'召唤物',17:'施法'}.get(sft,'其它') if cat=='book' else '')


def _source_label(change,catalog):
    if change.get('kind')=='skill':return '技能：'+str(catalog.name('SkillCfg',change.get('skillId')) or change.get('skillId'))
    roots=catalog.roots(change.get('id'));names=[(r['origin']+' / ' if r['origin'] else '')+r['name'] for r in roots]
    label=f"Buff：{change.get('name') or change.get('id')}（{change.get('piles')}层）"
    label+=('；配置'+('来源：' if len(names)==1 else '候选来源：')+'、'.join(names[:6])+(f'等{len(names)}项（共享Buff）' if len(names)>6 else '')) if names else '；授予来源未解析'
    if change.get('skillId'):label+='；关联技能：'+str(catalog.row('SkillCfg',change['skillId']).get('name') or change['skillId'])
    if change.get('state'):label+=' · 状态属性'
    return label


def sources(raw,catalog,meta):
    if not raw.get('raw'):return raw
    known=defaultdict(list)
    for change in raw.get('changes',[]):
        for key,value in change['values']:known[str(key)].append(dict(label=_source_label(change,catalog),raw=value))
    out={}
    for key,attr in raw.get('attributes',{}).items():
        base,scale,absolute,total=(attr.get(k) for k in ('base','scale','absolute','total'))
        if None in (base,scale,absolute,total):continue
        divisor=10000 if meta.get(str(key),{}).get('percent') else 1;rows=[]
        if base:rows.append(dict(label='基础面板',value=base/divisor))
        if base*scale:rows.append(dict(label='面板比例修正',value=base*scale/divisor))
        attributed=sum(r['raw'] for r in known[key])
        rows.extend(dict(label=r['label'],value=r['raw']/divisor) for r in known[key])
        if absolute-attributed:rows.append(dict(label='其他即时变化（未归属）',value=(absolute-attributed)/divisor))
        difference=total-(base*(1+scale)+absolute)/divisor
        if abs(difference)>1e-8:rows.append(dict(label='属性上下限/模式修正',value=difference))
        out[key]=rows
    return out


def _boss_buffs(raw,catalog,meta):
    rows=[]
    for buff in raw.get('buffs',[]):
        cfg=catalog.row('BuffCfg',buff.get('id'));roots=catalog.roots(buff.get('id'));changes=[]
        for change in raw.get('changes',[]):
            if change.get('kind')!='buff' or change.get('id')!=buff.get('id'):continue
            for key,value in change['values']:
                info=meta.get(str(key),{});percent=info.get('percent')
                reductions={103,105,118,119,120,124,126,128,130,132,134,200104,200106,200108,200110,200112,709,1003,234,236,238}
                reductions.update(itertools.chain(range(205,209),range(213,217),range(221,225),range(229,233)))
                usage=('BOSS受击时在扣血阶段处理，不重复乘入增伤' if key in (410,1006) else
                    '当前客户端类型区读取但未实际抵扣，按实测倍率展示' if key==128 else
                    'BOSS受击时抵扣（满足适用条件时）' if key in reductions else 'BOSS自身属性/输出；不直接视为受击增伤')
                changes.append(dict(key=key,name=info.get('label') or f'属性{key}',value=value/10000 if percent else value,percent=percent,zone=attr_zone(key),usage=usage))
        duration=buff.get('timeMax') or 0
        rows.append(dict(buff,name=buff.get('name') or f"Buff {buff.get('id')}",configuredSources=roots[:6],configuredSourceCount=len(roots),changes=changes,
            skillName=catalog.name('SkillCfg',buff.get('skillId')),remainingSeconds=max(0,math.ceil(duration-(buff.get('time') or 0))) if duration>0 else None,
            effectDescriptions=[label+'：'+str(expr) for field,label in [('_beginEffects','获得时'),('_loopEffects','周期触发'),('_endEffects','结束时'),('_deadEndEffects','死亡结束时')] for expr in cfg.get(field,[])]))
    return rows


def attr_zone(key):
    if key in (410,1006):return 'BOSS扣血结算机制（非增伤乘区）'
    if key in (1,2,3,19,20):return '攻击区'
    if key in (104,105,125,126,1002,1003,1004):return '普通增伤区'
    if 201<=key<=216:return '元素增伤区'
    if key in (108,109,110,111,127,128):return '类型增伤区 / 首领、精英、空地'
    if key in (113,114):return '类型增伤区 / 高低血量'
    if key in (115,116,119,120,131,133,134) or 225<=key<=238:return '类型增伤区 / 天书、符咒及技能'
    if key in (708,709):return '类型增伤区 / 普攻'
    if key in (117,118):return 'PVP增伤区（对局指标优先）'
    if key in (123,124,129):return '最终增伤区'
    if key in (101,102,103,106,107,130,132,601,602) or 217<=key<=224:return '暴击区（触发时）'
    if key in (705,706):return '技能系数区'
    if key in (200103,200104):return '赛季最终增伤区'
    if 200105<=key<=200112:return '致命一击区（触发时）'
    return '其他属性 / 特殊机制（未确认乘区）'


def factor_parts(hit,inputs,factors,context,catalog,battle_type):
    parts=defaultdict(list);cfg=catalog.row('SkillCfg',hit['skillId'])
    if all(factors.get(k)==0 for k in ('attack','coefficient','damage','element','targetType','hp','skillType','attackBonus')):return {}
    def add(zone,side,key):
        value=inputs.get(side,{}).get(str(key))
        if value is not None:parts[zone].append(dict(side=side,key=key,value=-value if side=='target' else value))
    def pair(method,zone):
        keys=hit.get('pairs',{}).get(method) or []
        if len(keys)>=2:add(zone,'self',keys[0]);add(zone,'target',keys[1])
    add('damage','self',104);add('damage','target',105)
    if battle_type==1:add('damage','self',125);add('damage','target',126)
    pair('getElementAttrType','element');pair('getElementAttrTypeSpecialSkill','element')
    if hit.get('monster'):
        add('targetType','self',109);add('targetType','self',127);add('targetType','self',110 if hit.get('fly') else 111)
    ratio=context.get('targetHpRatio')
    if ratio is not None:
        if ratio>.8:add('hp','self',113)
        elif ratio<.2:add('hp','self',114)
    book=catalog.row('SkillBookCfg',cfg.get('bookId'));sft=cfg.get('skillFunctionType');element=cfg.get('elementalType');offset={1:1,2:2,3:4,4:3}.get(element)
    if book and book.get('type')==1:
        add('skillType','self',116);add('skillType','target',120)
        if offset:add('skillType','self',224+offset);add('skillType','target',228+offset)
    elif (not book and sft!=12) or sft in (4,13,17):
        add('skillType','self',115)
        if sft in (4,13,17):add('skillType','target',119)
    if sft in (5,9,10,11):add('skillType','self',131)
    if sft in (15,16):add('skillType','self',133);add('skillType','target',134)
    pair('getQualityAttrTypeSpecialSkill','skillType')
    if cfg.get('type')==1:add('attackBonus','self',708);add('attackBonus','target',709)
    is_pvp=battle_type in (8,16,19,20,26)
    if is_pvp:
        add('pvp','self',117)
        if 'opponentPvpRed' in context:parts['pvp'].append(dict(side='opponent',key=118,label='对面PVP减伤',value=-context['opponentPvpRed']))
        else:add('pvp','target',118)
    add('final','self',123)
    if is_pvp:add('final','self',129)
    add('final','target',124)
    if hit.get('isCrit'):add('crit','self',102)
    if hit.get('isSkillCrit'):
        if book.get('type')==4:add('skillCrit','self',602)
        else:
            add('skillCrit','self',107);add('skillCrit','target',130)
            if offset:add('skillCrit','self',216+offset);add('skillCrit','target',220+offset)
    if 'season' in factors:add('season','self',200103);add('season','target',200104)
    for zone,rows in parts.items():
        actual=factors.get(zone)
        if actual is None:continue
        expected=actual if zone in ('targetType','hp','skillType','attackBonus') else actual-1
        rest=expected-sum(r['value'] for r in rows)
        if abs(rest)>1e-8:rows.append(dict(label='对局减伤指标/倍率下限修正' if zone=='pvp' and 'opponentPvpRed' in context else '条件效果、倍率下限或未拆分部分',value=rest))
    return dict(parts)


def analyze_hit(hit,side,catalog,meta,source_rows,source_index,skill_meta):
    sid=hit['skillId']
    if sid not in skill_meta:skill_meta[sid]=catalog.classify(sid,side.get('activeBranches',[]))
    info=skill_meta[sid]
    if info['cat']=='flag':return None
    mul=hit.get('multiplier') or {};context=dict(hit.get('context') or {})
    if (context.get('targetHpMax') or 0)>0 and context.get('targetHpCurrent') is not None:context['targetHpRatio']=context['targetHpCurrent']/context['targetHpMax']
    factors={target:mul.get(source) for target,source in [('coefficient','baseCoeff'),('damage','dmgAddRate'),('element','elementAddRate'),
        ('targetType','dmgTypeRate'),('hp','hpDmgAddRate'),('skillType','skillTypeAddRate'),('attackBonus','attackDmgRate')]}
    factors.update(attack=hit.get('attack'),pvp=max(.5,1+(mul.get('pvpDmgRate') or 0)),final=max(.25,1+(mul.get('finalDmgRate') or 0)),
        crit=max(1,1+(hit.get('critPwr') or 0)) if hit.get('isCrit') else 1,
        skillCrit=max(1,1+(hit.get('skillCritPwr') or 0)) if hit.get('isSkillCrit') else 1)
    factors['type']=1+sum(factors[k] or 0 for k in ('targetType','hp','skillType','attackBonus'))
    settlement=dict(hit.get('settlement') or {});damage=hit.get('damage',0)
    if (settlement.get('inputDamage') or 0)>0:factors['settlement']=damage/settlement['inputDamage']
    inputs=hit.get('inputs') or {};battle_type=side['battleType']
    if battle_type in (20,27):
        own=inputs.get('self') or {};other=inputs.get('target') or {};attack=own.get('200103');red=other.get('200104')
        factors['season']=None if attack is None or red is None else 1+attack-red
        aoe=hit.get('spCritAoeLimit') is not None and (hit.get('hitCount') or 0)>hit['spCritAoeLimit']
        factors['spCrit']=1+(own.get('200107') or 0)-(other.get('200108') or 0)+((own.get('200111') or 0)-(other.get('200112') or 0) if aoe else 0) if hit.get('isSpCrit') else 1
        factors['spCritAoe']=aoe
        if battle_type==20 and context.get('stamina'):
            factors.update(staminaSkill=context['stamina']['skillDamage'],staminaFinal=context['stamina']['finalDamage'])
    raw=hit.get('provenance') or {};provenance={key:sources(raw.get(key) or {},catalog,meta) for key in ('self','target')}
    provenance['targetBuffs']=_boss_buffs(raw.get('target') or {},catalog,meta)
    # Canonical source deduplication happens entirely outside the game process.
    signature=json.dumps(provenance,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    if signature not in source_index:source_index[signature]=len(source_rows);source_rows.append(provenance)
    row=dict(sec=math.floor(hit['t']),firstT=hit['t'],lastT=hit['t'],skillId=sid,name=info['skillName'],bookName=info['bookName'],
        category=info['cat'],group='attack' if catalog.row('SkillCfg',sid).get('type')==1 else 'book' if info['cat']=='book' else 'skill',
        sourceId=hit.get('sourceId'),sourceName=hit.get('sourceName'),targetId=hit.get('targetId'),targetName=hit.get('targetName'),
        boss=True,element=info['elem'],sourceRef=source_index[signature],trueDamage=hit.get('trueDamage',False),seckill=hit.get('seckill',False),
        formulaMode='independent' if all(factors.get(k)==0 for k in ('attack','coefficient','damage','element','targetType','hp','skillType','attackBonus')) else 'standard',
        factors=factors,inputs=inputs,context=context,settlement=settlement,hits=1,damage=damage)
    row['parts']=factor_parts(hit,inputs,factors,context,catalog,battle_type)
    return row


def _curve(rows,count):return [rows.get(i,0) for i in range(count)]


def analyze_side(side,catalog,meta):
    if side is None:return None
    info={};events=[];categories={};skills={};books={};branches={}
    curves={kind:defaultdict(lambda:defaultdict(float)) for kind in ('category','boss','skill','skillBoss','book','bookBoss','branch','branchBoss')}
    for raw in side.get('events',[]):
        sid=raw['skill']
        if sid not in info:info[sid]=catalog.classify(sid,side.get('activeBranches',[]))
        item=info[sid]
        event=dict(raw,**{k:v for k,v in item.items() if k!='branchPathName'});events.append(event)
        dmg=event['dmg'];sec=math.floor(event['t']);cat=item['cat']
        targets=[categories.setdefault(cat,dict(key=cat,label=CATEGORIES[cat],dmg=0,hits=0,crits=0)),
            skills.setdefault(sid,dict(skillId=sid,name=item['skillName'],cat=cat,catLabel=CATEGORIES[cat],bookId=item['book'],bookName=item['bookName'],
                branchId=item['branch'],branchName=item['branchName'],branchLevel=item['branchLevel'],elem=item['elem'],kind=item['kind'],origin=item['origin'],dmg=0,hits=0,crits=0))]
        if item['book'] and cat=='book':targets.append(books.setdefault(item['book'],dict(bookId=item['book'],name=item['bookName'],dmg=0,hits=0)))
        if item['branch']:targets.append(branches.setdefault(item['branch'],dict(branchId=item['branch'],name=item['branchName'],bookId=item['book'],bookName=item['bookName'],level=item['branchLevel'],path=item['branchPath'],pathName=item['branchPathName'],dmg=0,hits=0)))
        for target in targets:
            target['dmg']+=dmg;target['hits']+=1
            if 'crits' in target:target['crits']+=bool(event.get('crit'))
        for kind,key in [('category',cat),('category','__total'),('skill',sid)]+([('book',item['book'])] if item['book'] and cat=='book' else [])+([('branch',item['branch'])] if item['branch'] else []):
            curves[kind][key][sec]+=dmg
            if event.get('boss'):curves[{'category':'boss','skill':'skillBoss','book':'bookBoss','branch':'branchBoss'}[kind]][key][sec]+=dmg
    count=1+max(curves['category']['__total'],default=-1)
    def attach(row,kind,key):
        ps=_curve(curves[kind][key],count)
        return dict(row,perSecond=ps,bossPerSecond=_curve(curves['boss' if kind=='category' else kind+'Boss'][key],count),cumulative=list(itertools.accumulate(ps)))
    def ordered(values):return sorted(values,key=lambda r:-r['dmg'])
    skills=ordered(attach(r,'skill',key) for key,r in skills.items())
    branches=ordered(attach(r,'branch',key) for key,r in branches.items())
    books=ordered(attach(r,'book',key) for key,r in books.items())
    for book in books:
        book['branches']=[r for r in branches if r['bookId']==book['bookId']]
        book['skillsByBranch']=[r for r in skills if r['bookId']==book['bookId'] and r['branchId']]
        book['skillsNoBranch']=[r for r in skills if r['bookId']==book['bookId'] and not r['branchId']]
    active=[]
    for branch in side.get('activeBranches',[]):
        matched=next((r for r in branches if r['branchId']==branch['branchId']),{})
        active.append(dict(branch,dmg=matched.get('dmg',0),hits=matched.get('hits',0),perSecond=matched.get('perSecond',[]),cumulative=matched.get('cumulative',[]),dealtDamage=bool(matched)))
    def top(kind):
        out=[]
        for sec in range(count):
            rows=[dict(skillId=r['skillId'],name=r['name'],origin=r['origin'],cat=r['cat'],book=r['bookName'],branch=r['branchName'],dmg=curves[kind][r['skillId']].get(sec,0)) for r in skills]
            out.append(ordered(r for r in rows if r['dmg']>0)[:8])
        return out
    total=sum(e['dmg'] for e in events);boss=sum(e['dmg'] for e in events if e.get('boss'))
    category_rows=ordered(categories.values());sources_rows=[];source_index={};hits=[];last_hit={}
    for hit in side.get('hits',[]):
        row=analyze_hit(hit,side,catalog,meta,sources_rows,source_index,info)
        if row is not None:
            identity=(row['skillId'],row['sourceId'],row['targetId'])
            signature=json.dumps({k:v for k,v in row.items() if k not in ('firstT','lastT','hits','damage')},sort_keys=True,separators=(',',':'))
            previous=last_hit.get(identity)
            if previous and previous[0]==signature:
                previous[1].update(lastT=row['lastT'],hits=previous[1]['hits']+1,damage=previous[1]['damage']+row['damage'])
            else:
                last_hit[identity]=(signature,row);hits.append(row)
    result={key:value for key,value in side.items() if key not in ('hits','eventStart','hitStart')}
    result.update(events=events,totalDamage=total,bossDamage=boss,buckets=count,categories=category_rows,
        curves=[attach(r,'category',r['key']) for r in category_rows]+[attach(dict(key='__total',label='合计',dmg=total),'category','__total')],
        skills=skills,books=books,branches=branches,activeBranches=ordered(active),perSecondTop=top('skill'),perSecondBossTop=top('skillBoss'),
        factorRows=hits,factorSources=sources_rows,factorSnapshots=[],
        recordingOnly=True,analysisNotes=['乘区来自真实命中，不再在游戏内额外模拟未发生的技能。'])
    if side.get('truncated'):
        result['analysisNotes'].append('原始事件已达采集上限，伤害汇总和曲线仅涵盖已保存事件。')
    return result


def analyze_recording(data):
    """Legacy reports pass through; raw recordings are analyzed on the host."""
    if not isinstance(data,dict) or data.get('recordingSchema')!=1:return data
    catalog=Catalog(data.get('catalog') or {});meta={str(r['key']):r for r in data.get('attrMeta',[])}
    out=dict(mode=data.get('mode','single'),self=analyze_side(data.get('self'),catalog,meta),
             other=analyze_side(data.get('other'),catalog,meta),pvp=None,rawRecording=data)
    pvp=data.get('pvp') or {};samples=pvp.get('samples') or []
    if samples:
        cfg=pvp.get('cfg') or {};own=other=cfg.get('PVPInitScore') or 0;prev_own=prev_other=0;derived=[]
        for sample in samples:
            a=sample['selfBoss']-prev_own;b=sample['otherBoss']-prev_other;prev_own=sample['selfBoss'];prev_other=sample['otherBoss']
            weight=(cfg.get('PVPInitVariable') or 0)**sample['sec']*(cfg.get('PVPBaseBonus') or 0)
            share=a/(a+b) if a+b>0 else None;delta=weight*(share-.5) if share is not None else 0
            other_delta=weight*((1-share)-.5) if share is not None else 0
            own+=delta;other+=other_delta
            derived.append(dict(t=sample['t'],sec=sample['sec'],selfDmg=a,otherDmg=b,share=share,weight=weight,
                                deltaSelf=delta,deltaOther=other_delta,selfScore=own,otherScore=other))
        attrs=[]
        for sample in pvp.get('attrSeconds',[]):
            row=copy.deepcopy(sample)
            for key,opponent in [('self','other'),('other','self')]:
                values=row.get(key) or {};red=(row.get(key+'Context') or {}).get('opponentPvpRed',(row.get(opponent) or {}).get('118'))
                if values.get('117') is not None and red is not None:values['finalPvp']=values['117']-red
                row[key]=values;row[key+'Sources']=sources(row.get(key+'Sources') or {},catalog,meta)
            attrs.append(row)
        bt=pvp.get('battleType');name=next((s.get('battleTypeName') for s in (out['self'],out['other']) if s and s.get('battleType')==bt),None)
        out['pvp']=dict(pvp,battleTypeName=name,skipSafe=bt==26,winLine=2*(cfg.get('PVPInitScore') or 0),samples=samples,
            attrMeta=data.get('attrMeta',[]),attrSeconds=attrs,derived=derived,derivedSelfScore=own,derivedOtherScore=other,
            finalSelfScore=samples[-1]['selfScore'],finalOtherScore=samples[-1]['otherScore'])
    return out
