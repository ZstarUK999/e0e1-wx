const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=(process.env.BATTLE_ASSIST_CASE==='pve-integration'?fs.readFileSync(path.join(__dirname,'../package/plugin_manager/pve_assist_overlay.js'),'utf8')+'\n':'')+fs.readFileSync(process.env.BATTLE_ASSIST_SOURCE || path.join(__dirname,'../package/plugin_manager/battle_assist_runtime.js'),'utf8');
class Signal {
  constructor(){this.listeners=[];}
  on(f,c){this.listeners.push([f,c]);}
  off(f,c){this.listeners=this.listeners.filter(x=>x[0]!==f || x[1]!==c);}
  emit(...args){for(const [f,c] of [...this.listeners])f.apply(c,args);}
  dispatch(...args){this.emit(...args);}
}
async function setup({cd=0,period=20,positionless=false,overlay=false,awakened=false,fixtureCase=null,fixture=null}={}) {
  let energy=true,interval=null,worlds=[],casts=[],countdowns=[],spawned=[],diagnostics=[];
  const id=fixtureCase?fixtureCase.book:positionless?111200:110300;
  const rootSkill=fixtureCase?fixtureCase.root:awakened?111220:id;
  const cfg={SkillBookCfg:{getById:k=>({id:k,skill:[k],cdProperties1:[period]})},
    SkillCfg:{getById:k=>awakened && k===111220?{id:k,bookId:id,_properties:[{name:'sumSkill',expression:'111230'}],properties:[{name:'sumSkill',expr:{parsed:true}}]}:
      k===id?{id:k,bookId:id,_properties:[{name:'sumSkill',expression:String(id+10)}]}:
      ({id:k,bookId:0,_active:[k],properties:[],cd:k===111230?12:period})},
    ActiveSkillCfg:{getById:k=>({id:k,_emitters:[k]})},EmitterCfg:{getById:k=>({id:k,bulletIds:[k]})},
    BulletCfg:{getById:k=>({id:k,behavior:4,behaviorParams:['0.5','8'],lifeTime:4,_effects:[]})},
    BuffCfg:{getById:()=>null},BuffTag:{FROZEN:1,STUN:2},BulletBehaviorType:{INTERVAL:4}};
  if(fixture){
    for(const [table,rows] of Object.entries(fixture.tables)){
      const byId=new Map(rows.map(r=>[r.id,r]));cfg[table]={getById:k=>byId.get(k)};
    }
    cfg.BuffTag=fixture.BuffTag;cfg.BulletBehaviorType=fixture.BulletBehaviorType;
  }
  class Node {
    static EventType={TOUCH_START:'start',TOUCH_MOVE:'move',TOUCH_END:'end',TOUCH_CANCEL:'cancel'};
    constructor(name){this.name=name;this.children=[];this.handlers={};this.isValid=true;}
    addChild(n){n.parent=this;this.children.push(n);}
    addComponent(T){
      if(T===Graphics || T===Label){assert(!this.renderer,'Only one UIRenderer is allowed per Cocos node');this.renderer=T;}
      const component=new T();component.node=this;return this[T.name]=component;
    }
    getComponent(C){return this[C.name];}
    on(k,f){this.handlers[k]=f;}
    setPosition(){}
    destroy(){this.isValid=false;}
  }
  class UITransform {setContentSize(){}}
  class Graphics {constructor(){this.fills=[];this.strokes=0;}clear(){this.fills=[];this.strokes=0;}roundRect(){}rect(){}circle(){}moveTo(){}lineTo(){}fill(){this.fills.push(this.fillColor);}stroke(){this.strokes++;}}
  class Label {static Overflow={CLAMP:1};}
  const host=new Node('host'),cc={Node,UITransform,Graphics,Label,HorizontalTextAlignment:{CENTER:1},Color:class {constructor(...values){this.values=values;}},BlockInputEvents:class {},view:{getVisibleSize:()=>({width:1000,height:1000})}};
  const logic={checkSpecialCardEnergy:()=>energy,specialCardList:[{cardId:id,cd:0},{cardId:111100,cd:0}],useSpecialCardNum:0,
    onTick(dt){for(const c of this.specialCardList)c.cd=Math.max(0,c.cd-dt);},
    canUseSpecialCard(k){return energy && this.specialCardList.find(c=>c.cardId===k).cd<=0;}};
  const world={options:{battleData:{id:'test',type:1}},battleState:{curState:1},battleTime:{battleTime:0,isSkipping:false},
    systemManager:{getSystem:()=>logic},battleSignal:{useSkill:new Signal(),battleUseSkill:new Signal(),playerAutoUseCard:new Signal()},getFightHero:()=>({})};
  // Battle work and card UI are independent subscribers in the real client.
  world.battleSignal.battleUseSkill.on((skill,start,end)=>spawned.push({skill,end}));
  world.battleSignal.playerAutoUseCard.on((book,uid,end)=>countdowns.push({book,uid,end}));
  world.battleSignal.useSkill.on((skill,start,end,manual,key)=>{
    if(!logic.canUseSpecialCard(key))return;
    logic.specialCardList.find(c=>c.cardId===key).cd=cd;logic.useSpecialCardNum++;
    casts.push({key,skill,start,time:world.battleTime.battleTime,end,manual});
    world.battleSignal.battleUseSkill.emit(skill,start,end,manual,key);
  });
  worlds=[world];
  const helper={isFrameSyncType:k=>k===99,isServerResultPvpType:k=>k===98,
    battleSkillViewIndicatorFixBattlePos:p=>p,getAllRequireSkillLevels:()=>new Map([[111100,1],[id,fixtureCase?fixtureCase.level:awakened?8:1]]),
    getEvolutionSkillId:k=>fixtureCase && k===id?rootSkill:k===111100?111108:rootSkill};
  const modules={'battle-manager.ts':{BattleManager:{ins:{getBattles:()=>worlds}}},'system-card-logic.ts':{SystemCardLogic:class {}},
    'configs.ts':cfg,'battle-helper.ts':{battleHelper:helper},'types-battle.ts':{BattleState:{Running:1}},'vector2.ts':{Vector2:class {constructor(x,y){this.x=x;this.y=y;}}},
    'battle-const.ts':{BattleConst:{HERO_INIT_POS:{clone:()=>({x:0,y:168})}}}};
  const g={console:{info:(tag,value)=>diagnostics.push({tag,...JSON.parse(value)})},System:{import:async name=>name==='cc'?cc:modules[name.split('/').pop()]},UIManager:{ins:{system:host}}};
  let clock=0;
  const ctx={console,Date:{now:()=>clock},setInterval:f=>(interval=f,1),clearInterval:()=>{interval=null;}};
  vm.createContext(ctx);vm.runInContext(source+'\nthis.create=createBattleAssistRuntime;',ctx);
  const api=ctx.create(g),config={enabled:true,shijue:overlay,books:{[id]:{enabled:true,count:5}}};
  await api.configure(config);
  const resources=api.resourceStatus();
  assert.equal(typeof resources.worlds,'number');
  assert.equal(typeof resources.speedWorlds,'number');
  return {api,config,id,logic,world,casts,host,countdowns,spawned,diagnostics,
    manual(){world.battleSignal.useSkill.emit(rootSkill,{x:0,y:0},{x:432,y:10},true,id);},
    tick(t){const dt=t-world.battleTime.battleTime;world.battleTime.battleTime=t;logic.onTick(dt);},
    clock(t){clock=t;},discover(){interval && interval();},energy(v){energy=v;},clearWorlds(){worlds=[];}};
}
(async()=>{
  if(process.env.BATTLE_ASSIST_CASE==='diagnostics') {
    const x=await setup({overlay:true});
    assert.deepEqual(x.diagnostics.map(d=>d.stage),['battle-bound','overlay-before-first-render','overlay-after-first-render','heartbeat']);
    const n=x.diagnostics.length;for(let i=0;i<20;i++)x.discover();assert.equal(x.diagnostics.length,n);
    x.clock(5000);x.tick(13);x.discover();assert.equal(x.diagnostics.at(-1).stage,'heartbeat');assert.equal(x.diagnostics.at(-1).time,13);
    x.world.battleSignal.useSkill.emit(111108,{x:0,y:0},{x:100,y:0},true,111100);
    assert.equal(x.diagnostics.at(-1).stage,'shijue-success');assert.equal(x.diagnostics.at(-1).shijue.first,13);
    x.clearWorlds();x.discover();assert.equal(x.diagnostics.at(-1).stage,'battle-unbind');x.api.destroy();
    console.log('PASS durable diagnostic breadcrumbs, first-render boundaries, 5s throttle, casts and cleanup');return;
  }
  if(process.env.BATTLE_ASSIST_CASE==='shijue-phase') {
    let x=await setup({overlay:true,cd:45});
    await x.api.configure({...x.config,shijue_settings:{count:0,interval:20}});
    const toggle=()=>{const panel=x.host.children.find(n=>n.name==='e0e1_battle_assist');panel.handlers.start();panel.handlers.end({});};
    toggle();x.tick(1);assert.equal(x.casts.length,1,'first release establishes a nonzero anchor immediately');
    assert.equal(x.api.snapshot()[0].shijueFirst,1);
    x.tick(21);x.tick(41);x.tick(46);assert.equal(x.casts.length,1,'CD readiness between anchored rounds must not cast');
    x.energy(false);x.tick(61);x.energy(true);x.tick(62);assert.equal(x.casts.length,1,'energy recovery must not fill a missed round');
    x.tick(81);assert.deepEqual(x.casts.map(c=>c.time),[1,81]);
    assert.equal(x.api.snapshot()[0].shijueFirst,1);x.api.destroy();
    x=await setup({overlay:true,cd:10});
    await x.api.configure({...x.config,shijue_settings:{count:0,interval:20}});
    x.tick(3);x.world.battleSignal.useSkill.emit(111108,{x:0,y:0},{x:100,y:0},true,111100);toggle();
    x.tick(13);x.tick(20);assert.equal(x.casts.length,1);x.tick(23);assert.equal(x.casts.length,2,'manual first release anchors rounds at 23,43,63');
    x.tick(34);x.world.battleSignal.useSkill.emit(111108,{x:0,y:0},{x:100,y:0},true,111100);
    assert.equal(x.api.snapshot()[0].shijueFirst,3,'later manual release preserves first anchor');
    x.tick(43);x.tick(54);assert.equal(x.casts.length,3,'manual cooldown skips 43 and must not move the grid to 54');
    x.tick(63);assert.equal(x.casts.length,4);
    x.tick(90);assert.equal(x.casts.length,4,'late callbacks skip missed grid nodes');
    x.tick(103.03);assert.equal(x.casts.length,5,'fixed tick rounding remains valid');
    assert.equal(x.api.snapshot()[0].shijueDue,123);
    toggle();toggle();x.tick(113.03);assert.equal(x.casts.length,5);
    x.energy(false);x.tick(123);x.energy(true);x.tick(124);assert.equal(x.casts.length,5);x.tick(143);assert.equal(x.casts.length,6);
    assert.equal(x.api.snapshot()[0].shijueFirst,3);
    x.api.destroy();console.log('PASS first-success anchored rounds, energy/CD skips, manual casts, toggle, missed rounds and fixed-tick rounding');return;
  }
  if(process.env.BATTLE_ASSIST_CASE==='shijue-interval-baseline') {
    const x=await setup({overlay:true,cd:10});
    await x.api.configure({...x.config,shijue_settings:{count:0,interval:20}});
    const panel=x.host.children.find(n=>n.name==='e0e1_battle_assist');
    const toggle=()=>{panel.handlers.start();panel.handlers.end({});};
    // The player casts first, then enables the helper. Native cooldown is 10s.
    x.world.battleSignal.useSkill.emit(111108,{x:0,y:0},{x:100,y:0},true,111100);
    assert.equal(x.api.snapshot()[0].shijueLast,0);toggle();
    x.tick(10);assert.equal(x.casts.length,1,'CD ready must not bypass 20-second interval after manual cast');
    x.tick(19.99);assert.equal(x.casts.length,1);x.tick(20);assert.equal(x.casts.length,2);
    assert.equal(x.api.snapshot()[0].shijueCount,1,'success event must not double-count helper casts');
    x.tick(30);assert.equal(x.casts.length,2);x.tick(40);assert.equal(x.casts.length,3);
    // Reopening the switch resets batch count, not the last successful cast.
    toggle();toggle();x.tick(50);assert.equal(x.casts.length,3);
    x.tick(60);assert.equal(x.casts.length,4);assert.equal(x.api.snapshot()[0].shijueCount,1);
    await x.api.configure({...x.config,shijue_settings:{count:0,interval:0}});
    x.tick(70);assert.equal(x.casts.length,5,'zero interval still follows native CD');
    x.api.destroy();console.log('PASS 20s interval with 10s CD, manual baseline, preserved baseline after toggling, count and zero interval');return;
  }
  if(process.env.BATTLE_ASSIST_CASE==='shijue-settings') {
    const x=await setup({overlay:true});
    await x.api.configure({...x.config,shijue_settings:{count:2,interval:5}});
    const panel=x.host.children.find(n=>n.name==='e0e1_battle_assist');
    const toggle=()=>{panel.handlers.start();panel.handlers.end({});};
    toggle();x.tick(5);assert.equal(x.casts.length,1);assert.equal(x.api.snapshot()[0].shijueCount,1);
    x.tick(9.99);assert.equal(x.casts.length,1);
    x.energy(false);x.tick(10);assert.equal(x.casts.length,1);x.energy(true);x.tick(11);assert.equal(x.casts.length,1);x.tick(15);
    assert.equal(x.casts.length,2);assert.equal(x.api.snapshot()[0].shijue,false);
    x.tick(20);assert.equal(x.casts.length,2);toggle();x.tick(25);assert.equal(x.api.snapshot()[0].shijueCount,1);
    x.world.battleState.curState=0;x.tick(40);assert.equal(x.casts.length,3);
    x.world.battleState.curState=1;x.tick(40);assert.equal(x.casts.length,4);
    x.api.destroy();console.log('PASS Shijue count/interval, energy wait, pause, re-enable resets count');return;
  }
  if(process.env.BATTLE_ASSIST_CASE==='pve-integration') {
    const x=await setup({overlay:true});
    function find(name,n=x.host){if(!n.isValid)return null;if(n.name===name)return n;for(const c of n.children){const r=find(name,c);if(r)return r;}return null;}
    function click(name){const n=find(name);assert(n && n.active,name);n.handlers.start({});n.handlers.end({});}
    click('pve.tab.chain');x.manual();x.discover();assert(find('pve.contents').Label===undefined);
    assert(find('pve.contents').children[0].Label.string.includes('等待释放'));
    click('pve.shijue');assert(x.api.snapshot()[0].shijue);
    click('pve.collapse');assert(find('pve.ball').active);click('pve.ball');
    x.clearWorlds();x.discover();assert(!find('pve.panel'));x.api.destroy();
    console.log('PASS production factory integration: manual chain -> status, Shijue, ball, battle cleanup');return;
  }
  if(process.env.BATTLE_ASSIST_CASE==='wind-phase') {
    const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/battle_books.json'),'utf8'));
    const c=fixture.cases.find(c=>c.book===111200 && c.root===111220);
    for(const cd of [0,60]) {
      const x=await setup({fixtureCase:c,fixture,cd});
      await x.api.configure({...x.config,books:{[c.book]:{enabled:true,count:3}}});x.manual();
      assert.equal(x.api.snapshot()[0].chains[0].duration,4);
      const second=cd?64:4,third=cd?128:8;
      x.tick(second-0.01);assert.equal(x.casts.length,1);x.tick(second);
      assert.equal(x.casts.length,2);x.tick(third);assert.equal(x.casts.length,3);
      assert.deepEqual(x.casts.map(c=>c.time%12),[0,4,8]);x.api.destroy();
    }
    const bell=fixture.cases.find(c=>c.book===111600 && c.period===20 && c.duration===8);
    assert(bell,'fixture must contain the 20s/8s bell');
    const x=await setup({fixtureCase:bell,fixture});
    await x.api.configure({...x.config,books:{[bell.book]:{enabled:true,count:3}}});x.manual();
    assert.equal(x.api.snapshot()[0].chains[0].due,20/3);
    x.tick(20/3);x.tick(40/3);assert.equal(x.casts.length,3);x.api.destroy();
    console.log('PASS: wind 4s phases, card cooldown, bell 20/3 spacing');return;
  }
  if(process.env.BATTLE_ASSIST_CASE==='catalog') {
    const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/battle_books.json'),'utf8'));
    let controls=0,shijue=0;
    for(const c of fixture.cases){
      const x=await setup({fixtureCase:c,fixture,overlay:c.book===111100});
      try{
        if(c.book===111100){
          const p=x.host.children.find(n=>n.name==='e0e1_battle_assist');p.handlers.start();p.handlers.end({});x.tick(1);
          assert.equal(x.casts[0].skill,c.root);shijue++;continue;
        }
        x.manual();const s=x.api.snapshot()[0].chains[0];
        assert.equal(s.active,true,JSON.stringify(c));assert.equal(s.period,c.period,JSON.stringify(c));
        assert.equal(s.duration,c.duration,JSON.stringify(c));assert.equal(s.due,Math.min(c.duration,c.period/5),JSON.stringify(c));
        x.tick(s.due);assert.equal(x.casts[1].skill,c.root,JSON.stringify(c));assert.equal(x.countdowns.length,1);controls++;
        const a=await setup({fixtureCase:c,fixture});
        try {
          await a.api.configure({...a.config,books:{[c.book]:{enabled:true,count:0}}});a.manual();
          const state=a.api.snapshot()[0].chains[0],expected=Math.ceil(c.period/c.duration);
          assert.equal(state.target,expected,JSON.stringify(c));assert.equal(state.active,expected>1);
        } finally {a.api.destroy();}
      }finally{x.api.destroy();}
    }
    assert.equal(controls,169);assert.equal(shijue,21);
    console.log(`PASS: all ${fixture.catalog.length} books, ${controls} chain variants, ${shijue} Shijue variants`);return;
  }
  if(process.env.BATTLE_ASSIST_CASE==='awakened-wind') {
    const x=await setup({positionless:true,awakened:true,period:20});x.manual();
    assert.equal(x.api.snapshot()[0].chains[0].active,true,'awakened wind must be armed');
    assert.equal(x.api.snapshot()[0].chains[0].due,2.4,'use actual awakened attack cooldown, not the base-book list');
    x.tick(12);assert.equal(x.casts.length,2);assert.equal(x.casts[1].skill,111220);
    assert.equal(x.countdowns.length,1);x.api.destroy();console.log('PASS: awakened wind 111220 -> 111230, 12s');return;
  }
  if(process.env.BATTLE_ASSIST_CASE==='overlay') {
    const x=await setup({overlay:true});
    const panel=x.host.children.find(n=>n.name==='e0e1_battle_assist');
    const text=panel.children.find(n=>n.name==='十绝阵开关文字');
    assert(text && text.Label.string.includes('十绝阵：关闭'));
    assert.equal(panel.renderer.name,'Graphics');assert.equal(text.renderer.name,'Label');
    assert.equal(panel.Graphics.strokes,1,'button must have a visible border');
    const closed=panel.Graphics.fills.at(-1).values;
    const outside={getUILocation:()=>({x:500,y:500})};
    panel.handlers.start(outside);panel.handlers.end(outside);
    assert.equal(x.api.snapshot()[0].shijue,false,'clicking outside the button must not toggle');
    panel.handlers.start({});const pressed=panel.Graphics.fills.at(-1).values;
    assert.notDeepEqual(pressed,closed,'press must darken the button');
    panel.handlers.cancel();assert.deepEqual(panel.Graphics.fills.at(-1).values,closed);
    panel.handlers.start({});panel.handlers.end({});
    assert(text.Label.string.includes('点击关闭'));
    assert.notDeepEqual(panel.Graphics.fills.at(-1).values,closed,'enabled button must use a different color');
    x.api.destroy();console.log('PASS: separate Cocos renderers and visible switch text');return;
  }
  {
    const x=await setup();
    const preview=x.api.timingPreview().find(r=>r.id===x.id);
    assert.equal(preview.automatic,4);assert.equal(preview.level,1);
    await x.api.configure({...x.config,books:{[x.id]:{enabled:true,count:3,interval:2.5}}});
    assert.equal(x.api.timingPreview().find(r=>r.id===x.id).interval,2.5);
    x.manual();x.tick(2.5);x.tick(5);assert.deepEqual(x.casts.map(c=>c.time),[0,2.5,5]);x.api.destroy();
    const y=await setup({cd:60});
    await y.api.configure({...y.config,books:{[y.id]:{enabled:true,count:3,interval:2.5}}});
    y.manual();y.tick(60);assert.equal(y.casts.length,1);y.tick(62.5);assert.equal(y.casts.length,2);y.api.destroy();
    const z=await setup();z.manual();z.tick(1);
    await z.api.configure({...z.config,books:{[z.id]:{enabled:true,count:5,interval:3}}});
    z.tick(1);assert.equal(z.api.snapshot()[0].chains[0].due,3);z.tick(3);assert.equal(z.casts.length,2);z.api.destroy();
  }
  {
    const x=await setup();
    const text=()=>x.host.children.filter(n=>n.isValid && n.name==='e0e1_battle_assist').at(-1)?.children[0].Label.string;
    x.manual();assert(text().includes('等待4.0秒释放'));
    x.tick(1);x.discover();assert(text().includes('等待3.0秒释放'));
    x.energy(false);x.tick(4);x.discover();assert(text().includes('能量不足，等待能量'));
    x.energy(true);x.tick(5);x.manual();x.discover();assert(text().includes('玩家手动释放'));
    assert(text().includes('5秒'));x.clock(4001);x.discover();assert(text().includes('1秒'));
    x.clock(5001);x.discover();assert.equal(text(),undefined);x.api.destroy();
    const y=await setup();
    await y.api.configure({...y.config,books:{[y.id]:{enabled:true,count:2}}});
    y.manual();y.tick(4);y.discover();
    const p=y.host.children.find(n=>n.isValid && n.name==='e0e1_battle_assist');
    assert(p.children[0].Label.string.includes('控制链已完成'));
    y.clock(5000);y.discover();assert.equal(p.isValid,false);y.api.destroy();
  }
  let x=await setup();x.manual();
  for(const t of [4,8,12,16,20,24])x.tick(t);
  assert.deepEqual(x.casts.map(c=>c.time),[0,4,8,12,16]);
  assert.equal(x.spawned.length,5,'all five placements must reach battleUseSkill');
  assert.equal(x.countdowns.length,4,'four assisted casts must update the official top countdown');
  assert(x.countdowns.every(c=>c.book===110300 && c.end.x===432 && c.end.y===10));
  assert(x.casts.slice(1).every(c=>c.start.x===0 && c.start.y===168),'assisted casts must use the official hero origin');
  assert(x.casts.every(c=>c.end.x===432 && c.end.y===10));
  assert.equal(x.api.snapshot()[0].chains[0].active,false);x.api.destroy();

  x=await setup({cd:60});x.manual();x.tick(60);assert.equal(x.casts.length,1);
  x.tick(64);assert.equal(x.casts.length,2);assert.equal(x.api.snapshot()[0].chains[0].due,128);x.api.destroy();

  x=await setup();x.manual();x.tick(1);x.manual();x.tick(30);
  assert.equal(x.casts.length,2);assert.equal(x.api.snapshot()[0].chains[0].active,false);x.api.destroy();

  x=await setup();x.world.battleSignal.useSkill.emit(x.id,{x:0,y:0},{x:1,y:0},false,x.id);
  assert.equal(x.api.snapshot()[0].chains.length,0);x.api.destroy();

  x=await setup();x.manual();x.energy(false);x.tick(4);x.energy(true);x.tick(5);
  assert.equal(x.casts.length,1);assert.equal(x.countdowns.length,0,'rejected casts must not create a countdown');
  x.tick(24);assert.equal(x.casts.length,2);assert.equal(x.countdowns.length,1);x.api.destroy();

  x=await setup();x.manual();x.world.battleState.curState=0;x.tick(4);
  assert.equal(x.casts.length,1);x.world.battleState.curState=1;x.tick(4);assert.equal(x.casts.length,2);
  await x.api.configure({...x.config,enabled:false});x.tick(8);assert.equal(x.casts.length,2);x.api.destroy();

  x=await setup({positionless:true,period:12});x.manual();x.tick(2);assert.equal(x.casts.length,1);
  x.tick(2.4);assert.equal(x.casts.length,2);assert.equal(x.casts[1].end.x,100);x.api.destroy();

  x=await setup({positionless:true,awakened:true,period:20});x.manual();
  assert.equal(x.api.snapshot()[0].chains[0].active,true);
  assert.equal(x.api.snapshot()[0].chains[0].due,2.4);
  x.tick(12);assert.equal(x.casts[1].skill,111220);assert.equal(x.countdowns.length,1);x.api.destroy();

  x=await setup({overlay:true,cd:2});x.tick(1);assert.equal(x.casts.length,0);
  const panel=x.host.children.find(n=>n.name==='e0e1_battle_assist');assert(panel);
  assert(panel.children[0].Label.string.includes('十绝阵：关闭'));
  panel.handlers.start();panel.handlers.end({});x.tick(2);assert.equal(x.casts[0].key,111100);
  assert.equal(x.countdowns[0].book,111100,'Shijue also needs the official countdown');
  assert.equal(x.casts[0].skill,111108,'Shijue must resolve its current awakening skill');
  assert.equal(x.casts[0].start.y,168,'Shijue must use the official origin');
  x.discover();assert(panel.children[0].Label.string.includes('十绝阵：开启'));
  x.tick(3);assert.equal(x.casts.length,1);x.tick(4);assert.equal(x.casts.length,2);
  x.clearWorlds();x.discover();assert.equal(x.api.snapshot().length,0);assert.equal(panel.isValid,false);x.api.destroy();

  x=await setup({overlay:true});x.manual();let p=x.host.children.find(n=>n.isValid && n.name==='e0e1_battle_assist');
  p.handlers.start();p.handlers.end({});x.tick(4);assert.equal(x.casts.at(-1).key,110300);x.api.destroy();
  console.log('PASS: count, phase, cooldown, location, manual stop, energy, pause, disable, no-position, Shijue toggle, priority, cleanup');
})().catch(e=>{console.error(e);process.exitCode=1;});
