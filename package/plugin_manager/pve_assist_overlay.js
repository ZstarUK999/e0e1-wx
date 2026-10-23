// PvE presentation only. No service calls, action-log edits, RNG, or battle-result edits.
function createPveAssistOverlay(g,cc,modules) {
  const ui=g.UIManager.ins,valid=n=>!!n && (typeof cc.isValid==='function'?cc.isValid(n,true):n.isValid!==false),num=v=>Number(v && v.toNumber?v.toNumber():v);
  const nodes=new Map(),tracked=new Map(),patches=[];
  let battle=null,config=null,helpers=null,host=null,expanded=true,tab='home',page=0,position=null,model=[],lastSpeedUi=null,previousHeight=0,waveUnavailable=false;
  const zcfg=()=>config && config.zhongkui || {};
  const isZ=()=>battle && [10,11].includes(battle.world.options.battleData.type);
  const activeZ=()=>isZ() && zcfg().enabled;
  const color=(r,g,b,a=255)=>new cc.Color(r,g,b,a);
  function destroyNodes(){for(const x of nodes.values()){if(cc.Tween)cc.Tween.stopAllByTarget(x.node);if(valid(x.node))x.node.destroy();}nodes.clear();}
  function restoreSpeed(){for(const p of patches.splice(0))if(p.owner[p.key]===p.wrapper){if(p.own)p.owner[p.key]=p.original;else delete p.owner[p.key];}if(lastSpeedUi && valid(lastSpeedUi.node) && lastSpeedUi.refreshSpeedUpButtonVisible)lastSpeedUi.refreshSpeedUpButtonVisible();lastSpeedUi=null;}
  function patchSpeed() {
    if(!activeZ() || !zcfg().unlock_speed){if(patches.length)restoreSpeed();return;}
    const proto=modules.subdue && modules.subdue.UISubdueBattle && modules.subdue.UISubdueBattle.prototype;
    if(proto && !patches.length)for(const key of ['isSpeedUpVisible','getSpeedUpConfig']) {
      const original=proto[key],own=Object.prototype.hasOwnProperty.call(proto,key);
      if(typeof original!=='function')continue;
      const wrapper=function(...args){
        if(activeZ() && zcfg().unlock_speed && this.battleWorld===battle.world)return key==='isSpeedUpVisible'?true:[0,3];
        return original.apply(this,args);
      };
      proto[key]=wrapper;patches.push({owner:proto,key,original,wrapper,own});
    }
    const root=ui.root;
    if(root && root.getComponentsInChildren && modules.subdue) {
      const cached=lastSpeedUi && valid(lastSpeedUi.node) && lastSpeedUi.battleWorld===battle.world;
      const view=cached?lastSpeedUi:root.getComponentsInChildren(modules.subdue.UISubdueBattle).find(v=>v.battleWorld===battle.world);
      if(view && view.speedUpNode && view.refreshSpeedUpButtonVisible){
        const refresh=lastSpeedUi!==view || !view.speedUpNode.active;
        lastSpeedUi=view;if(refresh)view.refreshSpeedUpButtonVisible();
        for(const text of view.speedUpNode.getComponentsInChildren(cc.Label))if(text.string!=='3倍速')text.string='3倍速';
      }
    }
  }
  function project(entity) {
    const node=entity.compCharacterNodeView && entity.compCharacterNodeView.node;
    if(!valid(node) || !node.worldPosition || !ui.camera || !battle.world.battleNode)return null;
    const cameras=battle.world.battleNode.getComponentsInChildren(cc.Camera);
    const camera=cameras.find(c=>c.enabledInHierarchy!==false && c.camera && (!c.visibility || (c.visibility & node.layer)!==0));
    const targetTransform=host.getComponent(cc.UITransform);
    if(!camera || !targetTransform || !ui.camera.camera)return null;
    const screen=new cc.Vec3(),world=new cc.Vec3(),out=new cc.Vec3();
    camera.camera.worldToScreen(screen,node.worldPosition);
    ui.camera.camera.screenToWorld(world,screen);targetTransform.convertToNodeSpaceAR(world,out);
    return Number.isFinite(out.x+out.y)?{x:out.x,y:out.y}:null;
  }
  function scanMonsters() {
    if(!activeZ()){tracked.clear();model=[];return;}
    const world=battle.world,scene=world.sceneEntity;
    const context=scene && modules.context && scene.getComponent(modules.context.CompBattleContext);
    if(!context){tracked.clear();model=[];return;}
    const live=new Map(),time=Date.now();
    const phases=((world.options.stageConfig || {}).phase || []).map(Number);
    waveUnavailable=!phases.length;
    for(const e of context.pickupMonsters || []) {
      const m=e.compMonster,l=e.compLife;
      if(!m || !l || e.compDead || e.compDestroy || num(l.current)<=0)continue;
      const phase=Number(m.phase),wave=phases.indexOf(phase)+1;
      if(!Number.isFinite(phase) || wave<=0){waveUnavailable=true;continue;}
      const cfg=m.config || {},id=String(e.uuid),max=num(l.max),hp=num(l.current);
      live.set(id,{id,entity:e,phase,wave,name:cfg.name || e.name || `怪物${cfg.id || id}`,hp,max,
        ratio:max>0?Math.max(0,Math.min(1,hp/max)):0,point:null});
    }
    const lowest=Math.min(...[...live.values()].map(m=>m.wave));
    for(const [id,old] of tracked) {
      if(old.deadUntil){if(time>=old.deadUntil)tracked.delete(id);continue;}
      const next=live.get(id);
      if(next) {if(next.wave!==lowest)tracked.delete(id);else tracked.set(id,next);}
      else {
        // pickupMonsters excludes CompDead. Copy display data before pooled entities are reused.
        const e=old.entity,dead=e && (e.uuid!==Number(id) || e.compDead || !e.compLife || num(e.compLife.current)<=0);
        if(dead)tracked.set(id,{...old,entity:null,hp:0,ratio:0,point:null,deadUntil:time+2000});
        else tracked.delete(id); // Despawn/transform is not presented as a confirmed death.
      }
    }
    const limit=Math.max(1,Math.min(20,zcfg().monster_count || 5));
    for(const next of [...live.values()].filter(m=>m.wave===lowest).sort((a,b)=>Number(a.id)-Number(b.id))) {
      if(tracked.size>=limit)break;if(!tracked.has(next.id))tracked.set(next.id,next);
    }
    while(tracked.size>limit)tracked.delete([...tracked.keys()].at(-1));
    model=[...tracked.values()];
  }
  function animate(node){if(!valid(node))return;if(cc.tween && cc.Vec3){if(cc.Tween)cc.Tween.stopAllByTarget(node);cc.tween(node).to(.09,{scale:new cc.Vec3(.96,.96,1)}).to(.13,{scale:new cc.Vec3(1,1,1)}).start();}}
  function widget(key,parent,width,height,options={}) {
    let x=nodes.get(key);
    if(x && (!valid(x.node) || !valid(x.text) || x.node.parent!==parent)){
      if(valid(x.node))x.node.destroy();nodes.delete(key);x=null;
    }
    if(!x){
      const node=new cc.Node(key);node.layer=host.layer;parent.addChild(node);
      const transform=node.addComponent(cc.UITransform),graph=node.addComponent(cc.Graphics);
      const text=new cc.Node(key+'.text');text.layer=host.layer;node.addChild(text);
      const tt=text.addComponent(cc.UITransform),label=text.addComponent(cc.Label);
      label.fontSize=17;label.lineHeight=23;label.color=color(247,250,255);label.overflow=cc.Label.Overflow.CLAMP;
      label.horizontalAlign=cc.HorizontalTextAlignment.CENTER;
      x={node,transform,graph,text,tt,label,options,width:0,height:0,pressed:false,moved:false};nodes.set(key,x);
      if(options.click || options.drag){
        node.addComponent(cc.BlockInputEvents);
        node.on(cc.Node.EventType.TOUCH_START,event=>{x.moved=false;x.distance=0;x.pressed=true;paint(x);if(event)event.propagationStopped=true;});
        node.on(cc.Node.EventType.TOUCH_MOVE,event=>{
          const d=event.getUIDelta();x.distance+=Math.abs(d.x)+Math.abs(d.y);
          if(x.distance>5){x.moved=true;x.pressed=false;if(x.options.drag){position.x+=d.x;position.y+=d.y;render();}}
          event.propagationStopped=true;
        });
        node.on(cc.Node.EventType.TOUCH_END,event=>{const click=x.pressed && !x.moved;x.pressed=false;if(click && x.options.click){x.options.click();animate(x.node);}paint(x);if(event)event.propagationStopped=true;});
        if(cc.Node.EventType.TOUCH_CANCEL)node.on(cc.Node.EventType.TOUCH_CANCEL,()=>{x.pressed=false;paint(x);});
      }
    }
    x.options=options;x.seen=true;
    if(x.width!==width || x.height!==height){x.width=width;x.height=height;x.transform.setContentSize(width,height);x.tt.setContentSize(width-10,height-4);}
    if(!x.node.active)x.node.active=true;x.label.string=options.text || '';const units=Math.max(1,...x.label.string.split('\n').map(line=>[...line].reduce((n,c)=>n+(c.charCodeAt(0)>255?1:.6),0)));
    x.label.fontSize=Math.min(options.font || 17,Math.max(11,Math.floor((width-12)/units)));paint(x);return x;
  }
  function paint(x) {
    if(!valid(x.node))return;
    const g=x.graph,w=x.width,h=x.height,o=x.options;
    if(o.external)return;
    const c=o.fill,rgba=c?(c.values || [c.r,c.g,c.b,c.a]):null;
    const signature=JSON.stringify([w,h,!!o.circle,!!x.pressed,!!o.click,!!o.active,o.ratio,!!o.dead,rgba]);
    if(x.paintSignature===signature)return;
    x.paintSignature=signature;g.clear();
    g.fillColor=x.pressed?color(27,73,124):o.fill || color(24,34,51,245);
    if(o.circle)g.circle(0,0,w/2);else g.roundRect(-w/2,-h/2,w,h,9);g.fill();
    if(o.click || o.circle){g.strokeColor=o.active?color(97,237,163):color(131,195,255);g.lineWidth=2;
      if(o.circle)g.circle(0,0,w/2);else g.roundRect(-w/2,-h/2,w,h,9);g.stroke();}
    if(o.ratio!==undefined){g.fillColor=color(8,15,25);g.rect(-w/2+10,-h/2+5,w-20,7);g.fill();g.fillColor=o.dead?color(126,134,143):color(49,193,126);g.rect(-w/2+10,-h/2+5,(w-20)*o.ratio,7);g.fill();}
  }
  function chainLines(){
    const rows=[];
    if(config.shijue){
      const setting=config.shijue_settings || {},count=battle.shijueCount || 0;
      const time=helpers.now(battle.world),period=Number(setting.interval)||0;
      const first=battle.shijueFirst;
      const due=period>0 && first!=null?(battle.shijueDue??(first+Math.max(1,Math.ceil((time-first)/period))*period)):time;
      const left=Math.max(0,due-time);
      rows.push(`十绝阵 ${count}/${setting.count || '持续'} · ${period?'首放后'+period+'秒×轮次':'按冷却'}${battle.shijue?(first==null?' · 等待首次释放':left>0?' · 下轮还需'+left.toFixed(1)+'秒':' · 等待冷却／能量'):' · 关闭'}`);
    }
    for(const [id,s] of battle.chains){
      const cfg=modules.cfg.SkillBookCfg.getById(id),name=cfg && cfg.name || id,progress=s.target?`${s.count}/${s.target}`:'';
      if(s.active){const left=Math.max(0,s.due-helpers.now(battle.world)),reason=helpers.blockedReason(battle,s);
        rows.push(`${name} ${progress}：${reason || '等待释放'} ${left.toFixed(1)}秒${helpers.running(battle)?'':'（暂停）'}`);
      }else if(s.noticeUntil>Date.now())rows.push(`${name} ${progress}：${s.status}（${Math.ceil((s.noticeUntil-Date.now())/1000)}秒）`);
    }
    return rows;
  }
  function hideUnused(){for(const x of nodes.values())if(!x.seen && x.node.active)x.node.active=false;}
  function render(){
    if(!battle || !host)return;
    if(g.__e0e1GameOverlaysEnabled===false){destroyNodes();return;}
    for(const x of nodes.values())x.seen=false;
    // Keep all helper controls and markers out of native modal dialogs, without changing battle state.
    if(num(battle.world.battleTime.timeScale)===0 || ['dialog','popup'].some(key=>ui[key] && ui[key].children.some(n=>valid(n) && n.active!==false && n.activeInHierarchy!==false))){hideUnused();return;}
    const visible=cc.view.getVisibleSize(),w=Math.min(390,visible.width-24);
    if(!position)position={x:visible.width/2-w/2-12,y:visible.height/2-190};
    const chain=chainLines();
    if(!expanded){
      position.x=Math.max(-visible.width/2+45,Math.min(visible.width/2-45,position.x));
      position.y=Math.max(-visible.height/2+48,Math.min(visible.height/2-48,position.y));
      const ball=widget('pve.ball',host,84,84,{circle:true,drag:true,font:16,text:'PVE辅助\n点击展开',click(){expanded=true;render();animate(nodes.get('pve.panel').node);}});
      ball.node.setPosition(position.x,position.y,0);
      // A breathing ring remains visible even when the player has not tapped yet.
      const radius=44+Math.sin(Date.now()/450)*2;ball.graph.lineWidth=2;ball.graph.strokeColor=color(115,190,255,180);ball.paintSignature=null;ball.graph.circle(0,0,radius);ball.graph.stroke();hideUnused();return;
    }
    const body=tab==='chain'?chain:tab==='zhongkui' || tab==='none'?[]:['选择下方菜单','控制链：查看衔接与十绝阵','钟馗伏魔：怪物定位与3倍速'];
    const zkLines=tab==='zhongkui'?(activeZ()?[]:[isZ()?'请在桌面GUI开启钟馗伏魔':'当前不是钟馗伏魔']):[];
    const contents=[...body,...zkLines];
    if(tab==='chain' && !chain.length)contents.push('首次释放已开启控制链的天书后显示状态');
    const actionHeight=tab==='chain' && config.shijue || tab==='zhongkui' && activeZ()?42:0;
    const showMonsters=tab==='zhongkui' && activeZ() && zcfg().show_monsters;
    const listLayout=showMonsters?monsterLayout(visible,contents.length*25+actionHeight):null;
    const height=96+contents.length*25+actionHeight+(listLayout?listLayout.height:0);
    if(previousHeight && position)position.y+=(previousHeight-height)/2;
    previousHeight=height;
    position.x=Math.max(-visible.width/2+w/2,Math.min(visible.width/2-w/2,position.x));
    position.y=Math.max(-visible.height/2+height/2,Math.min(visible.height/2-height/2,position.y));
    const panel=widget('pve.panel',host,w,height,{});panel.node.setPosition(position.x,position.y,0);
    widget('pve.collapse',panel.node,w-14,32,{drag:true,text:'PVE辅助 · 点击收起 ▴',click(){expanded=false;render();animate(nodes.get('pve.ball').node);}}).node.setPosition(0,height/2-22,0);
    widget('pve.tab.chain',panel.node,(w-24)/2,32,{text:'控制链 '+(tab==='chain'?'▾':'▸'),active:tab==='chain',click(){tab=tab==='chain'?'none':'chain';page=0;render();}}).node.setPosition(-w/4+2,height/2-60,0);
    widget('pve.tab.zhongkui',panel.node,(w-24)/2,32,{text:'钟馗伏魔 '+(tab==='zhongkui'?'▾':'▸'),active:tab==='zhongkui',click(){tab=tab==='zhongkui'?'none':'zhongkui';page=0;render();}}).node.setPosition(w/4-2,height/2-60,0);
    if(contents.length)widget('pve.contents',panel.node,w-12,contents.length*25,{text:contents.join('\n'),font:16}).node.setPosition(0,height/2-89-contents.length*12.5,0);
    if(tab==='chain' && config.shijue)widget('pve.shijue',panel.node,w-18,34,{text:'十绝阵：'+(battle.shijue?'开启 · 点击关闭':'关闭 · 点击开启'),active:battle.shijue,fill:battle.shijue?color(24,135,83):color(44,105,188),click(){if(helpers.toggleShijue)helpers.toggleShijue(battle,!battle.shijue);else battle.shijue=!battle.shijue;render();}}).node.setPosition(0,-height/2+23,0);
    if(tab==='zhongkui' && activeZ())widget('pve.speed',panel.node,w-18,34,{text:zcfg().unlock_speed?`3倍速：${num(battle.world.battleTime.timeScale)===3?'已开启 · 点击恢复1倍':'点击开启'}`:'3倍速提前解锁已关闭',active:num(battle.world.battleTime.timeScale)===3,click(){
      if(!zcfg().unlock_speed || !helpers.running(battle))return;
      const scale=num(battle.world.battleTime.timeScale)===3?1:3;
      battle.world.battleTime.baseTimeScale=scale;battle.world.battleTime.timeScale=scale;
      if(lastSpeedUi)lastSpeedUi.refreshSpeedNode();render();
    }}).node.setPosition(0,-height/2+23,0);
    if(listLayout)renderMonsters(visible,panel.node,w-12,height/2-84-contents.length*25,listLayout);
    hideUnused();
  }
  function monsterLayout(visible,reserved){
    const perPage=Math.max(1,Math.floor((visible.height-160-reserved)/55));
    const pages=Math.max(1,Math.ceil(model.length/perPage));page=Math.min(page,pages-1);
    const shown=model.slice(page*perPage,(page+1)*perPage);
    return {perPage,pages,shown,height:36+shown.length*55+(pages>1?36:0)};
  }
  function renderMonsters(visible,parent,width,top,layout){
    const {shown,pages,perPage}=layout;
    const phase=model.find(x=>!x.deadUntil);
    widget('pve.monsters.title',parent,width-8,30,{text:phase?`最低存活波次：第${phase.wave}波`:waveUnavailable?'波次配置未匹配':'等待怪物入场',font:16}).node.setPosition(0,top-16,0);
    shown.forEach((m,i)=>{
      const idx=page*perPage+i+1,dead=!!m.deadUntil;
      const text=`${idx}. ${m.name} · 第${m.wave}波\n${dead?'已死亡':`${Math.round(m.ratio*10000)/100}%  ${formatHp(m.hp)}/${formatHp(m.max)}`}`;
      widget('pve.monster.'+i,parent,width-12,52,{text,font:14,ratio:m.ratio,dead}).node.setPosition(0,top-61-i*55,0);
      if(!dead && m.entity){const point=project(m.entity);if(point)drawArrow(idx,point,visible);}
    });
    if(pages>1){widget('pve.prev',parent,(width-20)/2,28,{text:'◂ 上一页',click(){page=Math.max(0,page-1);render();}}).node.setPosition(-width/4,top-36-shown.length*55-16,0);
      widget('pve.next',parent,(width-20)/2,28,{text:'下一页 ▸',click(){page=Math.min(pages-1,page+1);render();}}).node.setPosition(width/4,top-36-shown.length*55-16,0);}
  }
  function formatHp(n){return n>=1e8?(n/1e8).toFixed(2)+'亿':n>=1e4?(n/1e4).toFixed(1)+'万':String(Math.round(n));}
  function drawArrow(index,p,visible){
    const x=Math.max(-visible.width/2+20,Math.min(visible.width/2-20,p.x)),y=Math.max(-visible.height/2+15,Math.min(visible.height/2-85,p.y));
    const marker=widget('pve.arrow.'+index,host,34,64,{text:String(index),font:17,external:true});marker.node.setPosition(x,y+45,0);
    marker.paintSignature=null;const g=marker.graph;g.clear();
    // White outer silhouette + saturated blue remains distinct against dark/blue backgrounds.
    for(const [c,width] of [[color(255,255,255),8],[color(35,114,255),4]]) {
      g.strokeColor=c;g.lineWidth=width;g.moveTo(0,-4);g.lineTo(0,-29);g.moveTo(-9,-20);g.lineTo(0,-29);g.lineTo(9,-20);g.stroke();
    }
    marker.label.color=color(255,255,255);marker.text.setPosition(0,12,0);
  }
  return {
    update(next,cfg,h){
      if(!next || !cfg.enabled || !new Set([1,2,3,4,5,6,7,9,10,11,12,14,17,21,22,23,27]).has(next.world.options.battleData.type) || next.world.options.isReplay){this.clear();return;}
      if(battle && battle.world!==next.world)this.clear();
      battle=next;config=cfg;helpers=h;host=ui.system;
      if(!valid(host)){destroyNodes();return;}
      patchSpeed();scanMonsters();render();
    },
    snapshot(){return {active:!!activeZ(),waveUnavailable,updatedAt:Date.now(),expanded,tab,nodeCount:nodes.size,visibleNodeCount:[...nodes.values()].filter(x=>valid(x.node) && x.node.active!==false).length,monsters:model.map(({entity,...m})=>m),speedUnlocked:activeZ() && !!zcfg().unlock_speed};},
    clear(){restoreSpeed();destroyNodes();tracked.clear();model=[];battle=null;config=null;host=null;expanded=true;tab='home';page=0;previousHeight=0;waveUnavailable=false;},
    destroy(){this.clear();}
  };
}
