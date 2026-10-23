// Both transports embed this file. Casts always pass through the game's useSkill checks.
function createBattleAssistRuntime(g) {
  const SHIJUE=111100;
  const noPosition=new Set([110400,110800,110900,111000,111200]);
  const supported=new Set([110100,110200,110300,110400,110500,110600,110800,110900,111000,111200,111300,111400,111500,111600,111700]);
  let config={enabled:false,shijue:false,books:{}}, modules=null, loading=null, timer=null;
  let pveOverlay=null;
  let destroyed=false, panel=null, label=null, cc=null, overlayWorld=null, dragPos=null, panelGraph=null, panelTransform=null, textTransform=null, buttonPressed=false, buttonBounds=null;
  const bindings=new Map();
  // EBattleType: main/challenge/novice, legionWar, battlefield (not duel),
  // rougeLike, walkIn, seasonStage (诡道深渊). Independent of card-chain support.
  const speedTypes=new Set([1,2,3,6,13,21,23,27]),speedViews=new Map();
  const valid=n=>!!n && n.isValid!==false;
  const number=x=>typeof x==='number'?x:Number(x && x.toNumber?x.toNumber():x);
  const row=(table,id)=>table && table.getById(Number(id));
  const now=w=>number(w.battleTime.battleTime);
  const enabled=id=>config.enabled && !!(config.books[String(id)] || {}).enabled;

  // Send breadcrumbs to the external plugin log before a stalled VM becomes unreadable.
  // No game services, player data, or extra CDP evaluations are involved.
  let diagnosticAt=null;
  function diagnostic(stage,b) {
    if(!g.console || typeof g.console.info!=='function')return;
    try {
      const w=b && b.world,t=w && w.battleTime,o=pveOverlay && pveOverlay.snapshot();
      g.console.info('[plugin.diagnostic]',JSON.stringify({version:1,stage,wallTime:Date.now(),
        type:w && w.options.battleData.type,time:t && now(w),state:w && w.battleState.curState,
        scale:t && number(t.timeScale),baseScale:t && number(t.baseTimeScale),
        overlays:g.__e0e1GameOverlaysEnabled!==false,autoSpeed:!!config.auto_speed,
        shijue:b && {enabled:b.shijue,count:b.shijueCount,first:b.shijueFirst,last:b.shijueLast,due:b.shijueDue},
        chains:b && [...b.chains].map(([id,s])=>({id,active:s.active,count:s.count,due:s.due})),
        overlay:o && {tab:o.tab,expanded:o.expanded,nodeCount:o.nodeCount,visibleNodeCount:o.visibleNodeCount,monsterCount:o.monsters.length}}));
    }catch(e){console.error('[对战诊断]',e);}
  }

  function speedEligible(world) {
    const options=world && world.options,type=options && options.battleData && options.battleData.type;
    return !!(options && !options.isReplay && world.battleTime && speedTypes.has(type) &&
      !modules.helper.isFrameSyncType(type) && !modules.helper.isServerResultPvpType(type));
  }
  function speedUnlocked(view) {
    return config.enabled && config.auto_speed && speedEligible(view.battleWorld);
  }
  function restoreSpeed(view) {
    const saved=speedViews.get(view);if(!saved)return;
    speedViews.delete(view);
    if(saved.caption && valid(saved.caption))saved.caption.destroy();
    if(saved.highest && valid(saved.highest))saved.highest.active=saved.highestActive;
    for(const {button,callback,target} of saved.buttons)if(valid(button.node))button.addClick(callback,target);
    for(const {label,text} of saved.labels)if(valid(label.node))label.string=text;
    for(const key of ['setSpeed','refreshSpeedNode'])if(view[key]===saved[key].wrapper){
      if(saved[key].own)view[key]=saved[key].original;else delete view[key];
    }
    const node=view.view && view.view.node_gameScale;
    if(node && valid(node))node.active=saved.visible;
    if(valid(view.node))view.refreshSpeedNode();
  }
  function syncSpeed(worlds) {
    for(const view of speedViews.keys())if(!valid(view.node) || !worlds.includes(view.battleWorld) || !speedUnlocked(view))restoreSpeed(view);
    if(!config.enabled || !config.auto_speed)return;
    const ui=g.UIManager && g.UIManager.ins;
    if(!ui)return;
    const root=ui.root,type=modules.speedUi && modules.speedUi.UIBattleBase;
    const views=new Set(Object.values(ui.viewParams || {}).map(p=>p.ui).filter(Boolean));
    if(root && root.getComponentsInChildren && type)for(const view of root.getComponentsInChildren(type))views.add(view);
    for(const view of views){
      const node=view.view && view.view.node_gameScale;
      if(!node || typeof view.setSpeed!=='function' || typeof view.refreshSpeedNode!=='function' || !worlds.includes(view.battleWorld) || !speedUnlocked(view))continue;
      if(!speedViews.has(view)){
        const saved={visible:node.active,buttons:[],labels:[]};
        for(const [index,value] of [[0,1],[1,1.3],[2,1.6]]){
          const child=node.children[index];
          const button=child && child.getComponents(cc.Component).find(c=>typeof c.addClick==='function' && 'clickCallback' in c);
          if(button){saved.buttons.push({button,callback:button.clickCallback,target:button.cbTarget});button.addClick((...args)=>view.setSpeed(value),view);}
        }
        const highest=node.children[2];
        if(highest && cc.Label){
          saved.highest=highest;saved.highestActive=highest.active;
          const labels=highest.getComponentsInChildren(cc.Label);
          for(const label of labels){saved.labels.push({label,text:label.string});label.string='3倍速';}
          // Some prefabs render speed captions as sprites and contain no Label.
          if(!labels.length){
            const caption=new cc.Node('e0e1-speed-caption');caption.layer=highest.layer;
            highest.addChild(caption);caption.addComponent(cc.UITransform).setContentSize(100,30);
            const label=caption.addComponent(cc.Label);label.string='3倍速';label.fontSize=22;label.lineHeight=28;
            label.color=new cc.Color(255,230,130,255);
            const transform=highest.getComponent(cc.UITransform);
            caption.setPosition(0,-((transform && transform.height) || 50)/2-12,0);
            saved.caption=caption;
          }
          highest.active=true;
        }
        for(const key of ['setSpeed','refreshSpeedNode'])saved[key]={original:view[key],own:Object.prototype.hasOwnProperty.call(view,key)};
        saved.setSpeed.wrapper=function(value,initial=false){
          if(!speedUnlocked(this) || initial)return saved.setSpeed.original.call(this,value,initial);
          const world=this.battleWorld;
          if(world.isPaused || world.battleTime.isSkipping || world.battleState.curState!==modules.types.BattleState.Running)return;
          // The native highest-speed button passes 1.6; expose it as manual 3x.
          const scale=value===1.6?3:value;
          world.battleTime.timeScale=scale;world.battleTime.baseTimeScale=scale;
          this.refreshSpeedNode();
        };
        saved.refreshSpeedNode.wrapper=function(...args){
          const result=saved.refreshSpeedNode.original.apply(this,args);
          if(speedUnlocked(this)){
            const buttons=this.view.node_gameScale.children;
            this.view.node_gameScale.active=true;
            for(const index of [1,2]){
              const lock=buttons[index] && buttons[index].getChildByName('lock');if(lock)lock.active=false;
            }
            const selected=buttons[2] && buttons[2].getChildByName('inSelect');
            if(selected)selected.active=number(this.battleWorld.battleTime.timeScale)===3;
          }
          return result;
        };
        speedViews.set(view,saved);
        view.setSpeed=saved.setSpeed.wrapper;view.refreshSpeedNode=saved.refreshSpeedNode.wrapper;
      }
      view.refreshSpeedNode();
    }
  }

  // n + min(l, m/count) + m*k. Skip unavailable cycles instead of shifting the chain's phase.
  function phaseAtOrAfter(base,period,threshold) {
    if(!(period>0) || !Number.isFinite(base+period+threshold))return Infinity;
    return base+Math.max(0,Math.ceil((threshold-base-1e-7)/period))*period;
  }
  function summonedSkill(skill) {
    const p=(skill && (skill._properties || skill.properties) || []).find(p=>p.name==='sumSkill');
    const text=p && (p.expression===undefined?p.expr:p.expression);
    // Numeric references only; never evaluate configuration expressions as JavaScript.
    return /^\d+$/.test(String(text))?row(modules.cfg.SkillCfg,Number(text)):null;
  }
  function skillBullets(skill) {
    const cfg=modules.cfg,result=[];
    for(const aid of skill && skill._active || []) {
      const active=row(cfg.ActiveSkillCfg,aid);
      for(const eid of active && active._emitters || []) {
        const emitter=row(cfg.EmitterCfg,eid);
        for(const bid of emitter && emitter.bulletIds || []) {
          const bullet=row(cfg.BulletCfg,bid);if(bullet)result.push(bullet);
        }
      }
    }
    return result;
  }
  function intervalSpan(b) {
    if(b.behavior!==modules.cfg.BulletBehaviorType.INTERVAL)return 0;
    const p=b.behaviorParams || [],interval=Number(p[0]),count=Number(p[1]);
    return interval>0 && count>0?interval*count:0;
  }
  function buffsFor(bullets) {
    const result=[];
    for(const b of bullets)for(const effect of b._effects || []) {
      const m=/^BUFF\(\s*(\d+)\s*\)$/.exec(effect);
      const buff=m && row(modules.cfg.BuffCfg,Number(m[1]));if(buff)result.push(buff);
    }
    return result;
  }
  function metrics(bookId,skillId,world) {
    const cfg=modules.cfg,book=row(cfg.SkillBookCfg,bookId),root=row(cfg.SkillCfg,skillId);
    if(!book || !root || root.bookId!==bookId)return null;
    const level=modules.helper.getAllRequireSkillLevels(world).get(bookId);
    // Validate against the same per-battle awakening selector used by drag-and-drop.
    if(!(level>0) || modules.helper.getEvolutionSkillId(bookId,level,world)!==skillId)return null;
    const child=summonedSkill(root),period=number(child && child.cd);
    if(!(period>0))return null;
    const bullets=skillBullets(child),buffs=buffsFor(bullets);
    const max=values=>Math.max(0,...values.map(number).filter(Number.isFinite));
    let duration,mode='效果时长';
    if(bookId===111200) {
      // Positionless is a targeting rule, not a timing rule. Wind's repeated
      // hits share the four-second main debuff; don't phase-lock copies by CD.
      duration=max(buffs.filter(b=>b.id>=111210 && b.id<=111213).map(b=>b.duration));
      mode='风煞主控制效果错相';
      if(!duration){duration=period;mode='低阶无主控制效果，按冷却';}
    }
    else if(bookId===110800) {
      duration=max(buffs.filter(b=>b.tag===cfg.BuffTag.STUN).map(b=>b.duration));
      mode='主眩晕时长';
    } else if(bookId===111000) {
      duration=max(buffs.filter(b=>b.id===111012).map(b=>b.duration));
      mode='主减速时长';
      if(!duration){duration=period;mode='低阶无减速，按冷却';}
    } else if(noPosition.has(bookId)){duration=period;mode='攻击冷却';}
    else if(bookId===110300 || bookId===111600)duration=max(bullets.map(intervalSpan));
    else if(bookId===110100) {
      duration=max(bullets.filter(b=>(b._effects || []).some(e=>/^DMG_BURN\(/.test(e))).map(b=>b.lifeTime));
      if(!duration){duration=period;mode='瞬发伤害，按冷却';}
    } else if(bookId===110500) {
      duration=max(buffs.map(b=>b.duration));
      if(!duration){duration=period;mode='无持续灼烧，按冷却';}
    } else if(bookId===110200)duration=max(buffs.filter(b=>b.tag===cfg.BuffTag.STUN).map(b=>b.duration));
    else if(bookId===110600 || bookId===111400) {
      duration=max(buffs.filter(b=>b.tag===cfg.BuffTag.FROZEN).map(b=>b.duration));
      mode='基础冰冻时长（受目标抗性影响）';
    } else if(bookId===111500) {
      // Tier 1/2 poison predates CORPSE_POISON_INIT; both versions explicitly carry duration.
      duration=max(buffs.map(b=>b.duration));
    } else if(bookId===111700)duration=max(bullets.map(b=>b.lifeTime));
    else if(bookId===111300) {
      // Qianjiang: root -> repeating summon -> entrance attack -> created aura bullet.
      const entrance=summonedSkill(child),auras=[];
      for(const b of skillBullets(entrance))for(const effect of b._destroyEffects || []) {
        const m=/^BULLET_CREATE\(\s*(\d+)\s*\)$/.exec(effect);
        const aura=m && row(cfg.BulletCfg,Number(m[1]));if(aura)auras.push(aura);
      }
      duration=max(auras.map(intervalSpan));
    }
    if(!(duration>0))return null;
    return {period,duration,level,mode,attackSkillId:child.id,recommendedCount:Math.ceil(period/duration)};
  }
  function acceptable(world) {
    if(!world || !world.battleSignal || !world.battleTime || world.options.isReplay)return false;
    const type=world.options.battleData && world.options.battleData.type;
    return new Set([1,2,3,4,5,6,7,9,10,11,12,14,17,21,22,23,27]).has(type) && !modules.helper.isFrameSyncType(type) && !modules.helper.isServerResultPvpType(type);
  }
  function running(b) {
    return acceptable(b.world) && b.world.battleState.curState===modules.types.BattleState.Running && !b.world.battleTime.isSkipping;
  }
  function chainInterval(state,setting) {
    const value=setting && setting.interval;
    return typeof value==='number' && Number.isFinite(value) && value>0 && value<=3600
      ?value:Math.min(state.duration,state.period/state.target);
  }
  function nextDue(state,time,cardCd) {
    return phaseAtOrAfter(state.last+state.interval,state.period,time+Math.max(0,cardCd));
  }
  function targetCount(setting,timing) {
    return setting.count===0?Math.max(1,Math.min(20,timing.recommendedCount)):setting.count;
  }
  function finish(state,message) {
    state.active=false;state.status=message;state.noticeUntil=Date.now()+5000;
  }
  function blockedReason(b,state) {
    const card=b.logic.specialCardList.find(c=>c.cardId===state.bookId);
    if(!card)return '卡牌不可用';
    if(typeof b.logic.checkSpecialCardUseMax==='function' && b.logic.checkSpecialCardUseMax())return '达到本场释放上限';
    if(typeof b.logic.checkSpecialCardEnergy==='function' && !b.logic.checkSpecialCardEnergy(state.bookId))return '能量不足，等待能量';
    if(number(card.cd)>0)return '卡牌冷却中';
    return '';
  }
  function success(b,skillId,start,end,manual,bookId) {
    bookId=Number(bookId);
    // All successful casts establish the interval baseline, including the
    // player's first cast before enabling the helper and other native inputs.
    if(bookId===SHIJUE){recordShijue(b,now(b.world));return;}
    if(b.sending || manual!==true || !supported.has(bookId) || !enabled(bookId))return;
    const existing=b.chains.get(bookId);
    if(existing && existing.active){finish(existing,'玩家手动释放，控制链已停止');renderOverlay();return;}
    const timing=metrics(bookId,skillId,b.world);
    if(!timing){const state={active:false,skillId,bookId,count:1};finish(state,'无法解析本场技能，未接管');b.chains.set(bookId,state);renderOverlay();return;}
    const time=now(b.world), setting=config.books[String(bookId)], card=b.logic.specialCardList.find(c=>c.cardId===bookId);
    const target=targetCount(setting,timing);
    const state={...timing,active:target>1,count:1,target,last:time,
      skillId,bookId,start:{x:start.x,y:start.y},end:{x:end.x,y:end.y},status:target>1?'等待衔接':'已完成'};
    state.interval=chainInterval(state,setting);
    state.due=nextDue(state,time,number(card && card.cd)||0);
    if(!state.active)finish(state,'控制链已完成');
    b.chains.set(bookId,state);
    renderOverlay();
  }
  function cast(b,state) {
    const V=modules.vector.Vector2, start=modules.consts.BattleConst.HERO_INIT_POS.clone(), end=new V(state.end.x,state.end.y);
    // Use the same position correction as the official auto-cast for positionless books.
    if(noPosition.has(state.bookId) || state.bookId===SHIJUE) {
      const p=modules.helper.battleSkillViewIndicatorFixBattlePos(new V(100,0),state.skillId);
      end.x=p.x;end.y=p.y;
    }
    if(!b.logic.canUseSpecialCard(state.bookId,state.skillId,end))return false;
    const before=b.logic.useSpecialCardNum;
    b.sending=true;
    try {b.world.battleSignal.useSkill.emit(state.skillId,start,end,false,state.bookId);}
    finally {b.sending=false;}
    const accepted=b.logic.useSpecialCardNum>before;
    // useSkill performs the battle-side work only. The official card component
    // separately creates the top countdown and refreshes energy on this signal.
    // Do not send playerManualUseCard: it would cast a second time and toggle us off.
    if(accepted)b.world.battleSignal.playerAutoUseCard.dispatch(state.bookId,undefined,end);
    return accepted;
  }
  function toggleShijue(b,value) {
    b.shijue=value;
    if(value)b.shijueCount=0;
  }
  function recordShijue(b,time) {
    b.shijueLast=time;
    if(b.shijueFirst===null)b.shijueFirst=time;
    const period=Number((config.shijue_settings || {}).interval)||0;
    b.shijueDue=period>0?phaseAtOrAfter(b.shijueFirst+period,period,time+1e-5):null;
    b.shijuePeriod=period;
    if(b.shijue && config.shijue){
      b.shijueCount++;
      const limit=Number((config.shijue_settings || {}).count)||0;
      if(limit>0 && b.shijueCount>=limit)b.shijue=false;
    }
    diagnostic('shijue-success',b);
  }
  function tick(b) {
    if(destroyed || !config.enabled || !running(b))return;
    const time=now(b.world);
    // Control-chain casts have priority over the optional energy-consuming Shijue loop.
    for(const [id,s] of b.chains) {
      const setting=config.books[String(id)];
      if(!enabled(id)){if(s.active)finish(s,'控制链已关闭');continue;}
      if(!(s.period>0 && s.duration>0))continue;
      const target=targetCount(setting,s),previousInterval=s.interval;
      s.target=target;s.interval=chainInterval(s,setting);
      if(s.interval!==previousInterval) {
        const card=b.logic.specialCardList.find(c=>c.cardId===id);
        s.due=nextDue(s,time,number(card && card.cd)||0);
      }
      if(s.active && s.count>=s.target)finish(s,'控制链已完成');
      if(!s.active || time+1e-7<s.due)continue;
      if(cast(b,s)) {
        s.count++;s.last=time;s.active=s.count<s.target;
        const card=b.logic.specialCardList.find(c=>c.cardId===id);
        s.due=nextDue(s,time,number(card && card.cd)||0);s.status=s.active?'等待衔接':'控制链已完成';
        s.blocked='';if(!s.active)finish(s,'控制链已完成');
        return;
      }
      s.blocked=blockedReason(b,s) || '释放条件未满足';
      s.status=s.blocked+'，等待下一周期';
      s.due=phaseAtOrAfter(s.due+s.period,s.period,time);
    }
    if(b.shijue && config.shijue) {
      const setting=config.shijue_settings || {},limit=Number(setting.count)||0,interval=Number(setting.interval)||0;
      if(limit>0 && b.shijueCount>=limit){b.shijue=false;return;}
      if(interval>0 && b.shijueFirst!==null){
        if(b.shijuePeriod!==interval || b.shijueDue===null){
          b.shijuePeriod=interval;
          b.shijueDue=phaseAtOrAfter(b.shijueFirst+interval,interval,time);
        }
        // Stay on first-success + n*interval nodes. A delayed callback must not
        // replay a missed round; allow only fixed-tick rounding at the boundary.
        if(time>b.shijueDue+0.125)b.shijueDue=phaseAtOrAfter(b.shijueFirst+interval,interval,time);
        if(time+1e-7<b.shijueDue)return;
        b.shijueDue+=interval;
      }else {b.shijueDue=null;b.shijuePeriod=0;}
      const book=row(modules.cfg.SkillBookCfg,SHIJUE);
      const levels=modules.helper.getAllRequireSkillLevels(b.world);
      const level=levels.get(SHIJUE);
      if(!book || !(level>0) || !book.skill[level-1])return;
      const skillId=modules.helper.getEvolutionSkillId(SHIJUE,level,b.world);
      const previousCount=b.shijueCount;
      if(cast(b,{bookId:SHIJUE,skillId,end:{x:100,y:0}}) && b.shijueCount===previousCount)
        recordShijue(b,time); // Fallback for clients without the success signal.
    }
  }
  function bind(world) {
    if(bindings.has(world) || !acceptable(world))return;
    const logic=world.systemManager.getSystem(modules.card.SystemCardLogic);
    if(!logic || typeof logic.canUseSpecialCard!=='function')return;
    const b={world,logic,chains:new Map(),sending:false,shijue:false,shijueCount:0,shijueLast:null,shijueFirst:null,shijueDue:null,shijuePeriod:0,original:logic.onTick,wrapper:null};
    b.onSuccess=(...args)=>success(b,...args);
    b.wrapper=function(dt){b.original.call(this,dt);try{tick(b);}catch(e){b.shijue=false;for(const s of b.chains.values())s.active=false;console.error('[对战辅助]',e);}};
    logic.onTick=b.wrapper;
    world.battleSignal.battleUseSkill.on(b.onSuccess,b);
    bindings.set(world,b);
    diagnostic('battle-bound',b);
  }
  function unbind(b) {
    diagnostic('battle-unbind',b);
    if(b.logic.onTick===b.wrapper)b.logic.onTick=b.original;
    try{b.world.battleSignal.battleUseSkill.off(b.onSuccess,b);}catch(_){}
    b.chains.clear();b.shijue=false;bindings.delete(b.world);
  }
  function removePanel(){if(valid(panel))panel.destroy();panel=label=null;panelGraph=panelTransform=textTransform=null;overlayWorld=null;buttonPressed=false;buttonBounds=null;}
  function renderOverlay() {
    if(typeof createPveAssistOverlay==='function' && cc && modules) {
      if(!pveOverlay)pveOverlay=createPveAssistOverlay(g,cc,modules);
      const b=[...bindings.values()].find(b=>acceptable(b.world) && b.world.getFightHero && b.world.getFightHero());
      pveOverlay.update(b,config,{running,now,blockedReason,toggleShijue,render:renderOverlay});return;
    }
    const candidates=[...bindings.values()].filter(b=>acceptable(b.world));
    const b=candidates.find(b=>b.world.getFightHero && b.world.getFightHero());
    const host=g.UIManager && g.UIManager.ins && g.UIManager.ins.system;
    const rows=[];
    if(b)for(const [id,state] of b.chains) {
      const book=row(modules.cfg.SkillBookCfg,id),name=book && book.name || String(id);
      const progress=state.target?` ${state.count}/${state.target}`:'';
      if(state.active) {
        const seconds=Math.max(0,state.due-now(b.world)),reason=blockedReason(b,state);
        const paused=running(b)?'':'（战斗暂停）';
        const text=reason?`${reason}；${seconds.toFixed(1)}秒后衔接`:
          state.blocked && seconds>0?`等待${seconds.toFixed(1)}秒后再次检查释放条件`:`等待${seconds.toFixed(1)}秒释放`;
        rows.push(`${name}${progress}：${text}${paused}`);
      } else if(state.noticeUntil>Date.now()) {
        rows.push(`${name}${progress}：${state.status}（${Math.ceil((state.noticeUntil-Date.now())/1000)}秒）`);
      }
    }
    if(!config.enabled || !b || !cc || !valid(host) || (!config.shijue && !rows.length)){removePanel();return;}
    const lines=config.shijue?['十绝阵：'+(b.shijue?'开启':'关闭')+' · 点击'+(b.shijue?'关闭':'开启'),'拖动浮窗可移位',...rows]:rows;
    const visible=cc.view.getVisibleSize(),width=Math.min(rows.length?560:320,visible.width-20);
    const height=lines.length*24+12;
    if(overlayWorld!==b.world || !valid(panel) || panel.parent!==host) {
      removePanel();overlayWorld=b.world;
      panel=new cc.Node('e0e1_battle_assist');panel.layer=host.layer;
      panelTransform=panel.addComponent(cc.UITransform);host.addChild(panel);
      panelGraph=panel.addComponent(cc.Graphics);panelGraph.fillColor=new cc.Color(24,30,42,235);
      panel.addComponent(cc.BlockInputEvents);
      // Cocos allows a single UIRenderer per node.
      const text=new cc.Node('十绝阵开关文字');text.layer=host.layer;
      textTransform=text.addComponent(cc.UITransform);panel.addChild(text);text.setPosition(0,0,0);
      label=text.addComponent(cc.Label);label.fontSize=19;label.lineHeight=24;label.color=new cc.Color(245,247,250,255);
      label.overflow=cc.Label.Overflow.CLAMP;label.horizontalAlign=cc.HorizontalTextAlignment.CENTER;
      if(!dragPos)dragPos={x:visible.width/2-width/2-15,y:visible.height/2-320};
      let moved=false;
      const inButton=event=>{
        if(!config.shijue || !buttonBounds)return false;
        const point=event.getUILocation && event.getUILocation();
        if(!point)return true;
        const x=point.x-visible.width/2-dragPos.x,y=point.y-visible.height/2-dragPos.y;
        return Math.abs(x)<=buttonBounds.width/2 && y>=buttonBounds.bottom && y<=buttonBounds.top;
      };
      panel.on(cc.Node.EventType.TOUCH_START,event=>{moved=false;buttonPressed=inButton(event || {});renderOverlay();});
      panel.on(cc.Node.EventType.TOUCH_MOVE,event=>{
        const d=event.getUIDelta();moved=true;buttonPressed=false;dragPos.x+=d.x;dragPos.y+=d.y;
        renderOverlay();
        panel.setPosition(dragPos.x,dragPos.y,0);event.propagationStopped=true;
      });
      panel.on(cc.Node.EventType.TOUCH_END,event=>{
        const clicked=buttonPressed && !moved && inButton(event);
        buttonPressed=false;
        if(clicked)toggleShijue(b,!b.shijue);
        renderOverlay();
        event.propagationStopped=true;
      });
    }
    if(cc.Node.EventType.TOUCH_CANCEL && !panel.__assistCancelBound) {
      panel.__assistCancelBound=true;
      panel.on(cc.Node.EventType.TOUCH_CANCEL,()=>{buttonPressed=false;renderOverlay();});
    }
    panelTransform.setContentSize(width,height);textTransform.setContentSize(width-12,height-8);
    panelGraph.clear();panelGraph.fillColor=new cc.Color(24,30,42,235);
    panelGraph.roundRect(-width/2,-height/2,width,height,8);panelGraph.fill();
    buttonBounds=null;
    if(config.shijue) {
      const bw=width-24,top=height/2-4,bottom=top-27;
      buttonBounds={width:bw,top,bottom};
      // Raised shadow, solid action color, and a bright border give the control a button silhouette.
      panelGraph.fillColor=new cc.Color(8,12,20,255);
      panelGraph.roundRect(-bw/2,bottom-3,bw,27,6);panelGraph.fill();
      const color=b.shijue?(buttonPressed?[22,109,73]:[30,151,96]):(buttonPressed?[37,79,142]:[48,111,194]);
      panelGraph.fillColor=new cc.Color(...color,255);
      panelGraph.roundRect(-bw/2,bottom,bw,27,6);panelGraph.fill();
      panelGraph.lineWidth=2;panelGraph.strokeColor=new cc.Color(...(b.shijue?[109,234,160]:[138,193,255]),255);
      panelGraph.roundRect(-bw/2,bottom,bw,27,6);panelGraph.stroke();
    }
    dragPos.x=Math.max(-visible.width/2+width/2,Math.min(visible.width/2-width/2,dragPos.x));
    dragPos.y=Math.max(-visible.height/2+height/2,Math.min(visible.height/2-height/2,dragPos.y));
    const units=Math.max(...lines.map(line=>[...line].reduce((n,c)=>n+(c.charCodeAt(0)>255?1:0.6),0)));
    label.fontSize=Math.min(19,Math.max(12,Math.floor((width-20)/Math.max(1,units))));
    panel.setPosition(dragPos.x,dragPos.y,0);label.string=lines.join('\n');
  }
  async function load() {
    if(modules)return;
    if(!loading)loading=Promise.all(['battle-manager.ts','system-card-logic.ts','configs.ts','battle-helper.ts','types-battle.ts','vector2.ts','battle-const.ts']
      .map(name=>g.System.import('chunks:///_virtual/'+name))).then(([manager,card,cfg,helper,types,vector,consts])=>{
        modules={manager,card,cfg,helper:helper.battleHelper,types,vector,consts};
      }).finally(()=>{loading=null;});
    await loading;
  }
  function discover() {
    if(!modules || destroyed)return;
    const worlds=modules.manager.BattleManager.ins.getBattles();
    syncSpeed(worlds);
    for(const [w,b] of bindings)if(!worlds.includes(w) || !acceptable(w))unbind(b);
    if(config.enabled)for(const w of worlds)bind(w);
    const first=[...bindings.values()].find(b=>!b.diagnosticRendered);
    if(first)diagnostic('overlay-before-first-render',first);
    renderOverlay();
    if(first){first.diagnosticRendered=true;diagnostic('overlay-after-first-render',first);}
    const wall=Date.now();
    if(bindings.size && (diagnosticAt===null || wall-diagnosticAt>=5000)){
      diagnosticAt=wall;for(const b of bindings.values())diagnostic('heartbeat',b);
    }
  }
  const api={
    async configure(value) {
      config=value || {enabled:false,shijue:false,books:{}};
      if(!config.enabled){syncSpeed([]);for(const b of [...bindings.values()])unbind(b);removePanel();if(pveOverlay){pveOverlay.destroy();pveOverlay=null;}if(timer!==null){clearInterval(timer);timer=null;}return;}
      await load();if(destroyed)return;
      if(!cc)cc=await g.System.import('cc');
      if(config.auto_speed && !modules.speedUi)modules.speedUi=await g.System.import('chunks:///_virtual/ui-battle-base.ts');
      if(typeof createPveAssistOverlay==='function' && !modules.context) {
        const [context,subdue]=await Promise.all(['comp-battle-context.ts','ui-subdue-battle.ts'].map(n=>g.System.import('chunks:///_virtual/'+n)));
        modules.context=context;modules.subdue=subdue;
      }
      for(const b of bindings.values()){
        if(!config.shijue)b.shijue=false;
        for(const [id,s] of b.chains)if(!enabled(id) && s.active)finish(s,'控制链已关闭');
      }
      discover();if(timer===null)timer=setInterval(()=>{try{discover();}catch(e){console.error('[对战辅助]',e);}},250);
    },
    resourceStatus(){const o=pveOverlay && pveOverlay.snapshot();return {worlds:bindings.size,chains:[...bindings.values()].reduce((n,b)=>n+b.chains.size,0),timer:timer!==null,speedWorlds:speedWorlds.size,overlayNodes:o?o.nodeCount:0};},
    pveStatus(){return pveOverlay?pveOverlay.snapshot():null;},
    timingPreview(){
      if(!modules || destroyed)return [];
      const result=[];
      for(const b of bindings.values()) {
        if(!acceptable(b.world))continue;
        const levels=modules.helper.getAllRequireSkillLevels(b.world);
        for(const id of supported) {
          const level=levels.get(id);if(!(level>0))continue;
          const skill=modules.helper.getEvolutionSkillId(id,level,b.world),timing=metrics(id,skill,b.world);
          if(!timing)continue;
          const setting=config.books[String(id)] || {count:0},target=targetCount(setting,timing);
          const automatic=Math.min(timing.duration,timing.period/target);
          result.push({id,level,skillId:skill,period:timing.period,duration:timing.duration,target,
            automatic,interval:chainInterval({...timing,target},setting)});
        }
        break; // Display one current local battle; never combine two worlds' levels.
      }
      return result;
    },
    snapshot(){return [...bindings.values()].map(b=>({battleId:b.world.options.battleData.id,shijue:b.shijue,shijueCount:b.shijueCount,shijueLast:b.shijueLast,shijueFirst:b.shijueFirst,shijueDue:b.shijueDue,
      chains:[...b.chains].map(([id,s])=>({id,skillId:s.skillId,attackSkillId:s.attackSkillId,level:s.level,period:s.period,duration:s.duration,interval:s.interval,mode:s.mode,recommendedCount:s.recommendedCount,active:s.active,count:s.count,target:s.target,due:s.due,status:s.status}))}));},
    destroy(){destroyed=true;config={enabled:false,shijue:false,books:{}};syncSpeed([]);if(timer!==null)clearInterval(timer);timer=null;for(const b of [...bindings.values()])unbind(b);removePanel();if(pveOverlay){pveOverlay.destroy();pveOverlay=null;}}
  };
  return api;
}
