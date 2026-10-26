// Offline game-module fixtures. No browser, game, sockets or real RPCs.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const defaultSource = fs.existsSync(path.join(__dirname, 'js/season_bloodmoon.js'))
  ? path.join(__dirname, 'js/season_bloodmoon.js') : path.join(__dirname, 'season_bloodmoon.js');
const source = fs.readFileSync(process.argv[2] || defaultSource, 'utf8');
const originalGamePath = path.join(__dirname, '../output/wx6d5e82c174635a48/65/subpackages/game/game.js');
let originalSpeedCheck = null, originalCanAttack = null, originalModuleCanAttack = null, originalMarchUpdate = null;
if(fs.existsSync(originalGamePath) && fs.statSync(originalGamePath).size > 0) {
  const original=fs.readFileSync(originalGamePath,'utf8');
  const match=original.match(/l\.getSpeedUpDisabledReason = (function\(e\) \{[\s\S]*?\n          \}), l\.getAttackGuardDisabledReason/);
  assert.ok(match,'original UI speed eligibility method must be found');
  originalSpeedCheck = new Function('w','A','S','I','return '+match[1]);
  const canAttack=original.match(/r\.canAttack = (function\(e\) \{[\s\S]*?\n          \}), r\.tryStartBattle/);
  assert.ok(canAttack,'original UI attack eligibility method must be found');
  originalCanAttack = new Function('d','p','return '+canAttack[1]);
}
// Optional current Douyin cache path: execute the actual 0.1.75 eligibility
// functions against the same boundary fixtures instead of the old WX copy.
if (process.env.BLOODMOON_GAME_SOURCE) {
  const original=fs.readFileSync(process.env.BLOODMOON_GAME_SOURCE,'utf8');
  function method(moduleName,name){
    const start=original.indexOf('System.register("chunks:///_virtual/'+moduleName+'"');
    assert(start>=0,moduleName);
    const end=original.indexOf('System.register(',start+1);
    const part=original.slice(start,end<0?undefined:end);
    const match=part.match(new RegExp('\\w+\\.'+name+'=(function[\\s\\S]*?)(?=,\\w+\\.\\w+=function)'));
    assert(match,name);return match[1];
  }
  originalSpeedCheck=new Function('w','B','I','S','return '+method('ui-season-op.ts','getSpeedUpDisabledReason'));
  originalCanAttack=new Function('d','f','return '+method('ui-season-queue-detail.ts','canAttack'));
  originalModuleCanAttack=new Function('y','return '+method('season-module.ts','canAttack'));
  originalMarchUpdate=new Function('q','z','H','v','L','return '+method('season-map-scene.ts','_doMarchUpdate'));
}


function fixture(options = {}) {
  const intervals=new Map();let intervalId=0;
  const listeners = new Set();
  const exitSignal = {on(fn){listeners.add(fn);},off(fn){listeners.delete(fn);},
    emit(event){for(const fn of [...listeners])fn(event);}};
  let now = 100000, next = 0, tasks = [], logs = [], sent = [];
  const timers = (fn, ms) => { tasks.push({ id: ++next, at: now + ms, fn }); return next; };
  const me = { id: 1, name: 'self', lId: 10, state: 2, power: 1000, planPower: [1000], position: {x: 1, y: 1} };
  const enemy = { id: 2, name: 'enemy', lId: 20, state: 1, power: 500, planPower: [500] };
  const move = {id: 1, from: {x:1,y:1}, to: {x:2,y:2}, start: 90000, arrive: 500000};
  const data = { roles: new Map([[1,me],[2,enemy]]), legions: new Map(), moveInfos: new Map([[1,move]]),
    buildings: new Map([['1_1', {members: new Set([1,2])}]]) };
  const helper={isStealth(role){return !!(role && role.ext && role.ext.get(4));},
    shouldHideStealthMarch(role){return !!(role && role.id!==me.id && role.lId!==me.lId && role.ext && role.ext.get(4));}};
  const originalHide=helper.shouldHideStealthMarch;
  const scene={sourceMap:{},_dirtyMarch:false,_marchArr:[],_isTargetBuildingVisible:()=>true,
    _flyFishManager:{_flyFishMap:new Map(),syncMarches(rows){this.rows=JSON.parse(JSON.stringify(rows));
      this._flyFishMap=new Map(rows.map(row=>[row.marchId,{march:row.march}]));},refreshVisibility(fn){this.visible=fn;}}};
  const rpc = { moveSpeedUp(){}, startPVPBattle(){}, background(){} };
  const manager = { service(fn, params) {
    sent.push({fn,params});
    if (fn === rpc.background) return Promise.resolve({err:null,resp:{}});
    return new Promise((resolve,reject) => timers(() => {
      if (options.networkError) return reject(new Error('offline network failure'));
      if (!options.reject) {
        move.arrive = now + (move.arrive-now)/2;
        if (options.changeStart) {move.start=now; move.from={x:9,y:9};}
      }
      resolve(options.malformed ? {} : {err: options.reject ? {code:options.rejectCode || 7,error:options.rejectCode===350018?'目标行军中，稍后再试':'denied'} : null, resp:{}});
    }, options.delay || 100));
  }};
  const originalService = manager.service;
  let manualInjected = false;
  function button(name, click, role) {
    const b = {interactable:true, enabledInHierarchy:true, continuous:false, clickInteractable:true,
      cbTarget: role ? {role,showAttack:true} : null};
    b.node = { name, activeInHierarchy:true, emit(type) { if(type==='end') click(); } };
    return b;
  }
  const op = { _bx:2, _by:2, _speedCooldownUntil:0, _speedUpDisabledReason:'',
    getSpeedUpDisabledReason(isMarching) {
      if(!isMarching) return '当前没有可加速的行军';
      if(options.nativeDenied) return 'UI禁止加速';
      if(originalSpeedCheck) return originalSpeedCheck({config:conf}, {get serverTime(){return now;}},
          {getItemCount:()=>options.items ?? 100}, {getById:()=>({name:'道具'})}).call({_module:module,_speedCooldownUntil:this._speedCooldownUntil},isMarching);
      return move.arrive-now < 10000 ? '剩余时间不足10秒' : '';
    } };
  if (options.noNativeCheck) delete op.getSpeedUpDisabledReason;
  let dialog = null;
  function sendSpeed() {
    if (options.unrelated) manager.service(rpc.background,{});
    if (!options.noRequest) manager.service(rpc.moveSpeedUp,{warId: options.wrongWar ? 99 : 7}).catch(()=>{});
    if (options.duplicate) manager.service(rpc.moveSpeedUp,{warId:7}).catch(()=>{});
  }
  function speedClick() {
    if (options.dialog) dialog={view:{btn_speed_up:button('confirm',sendSpeed)}};
    else sendSpeed();
  }
  op.btn_speed_up = button('speed', speedClick);
  if (options.disabledButton) op.btn_speed_up.interactable = false;
  if(options.staleSelection){op._bx=99;op._by=99;op._speedUpDisabledReason='旧建筑按钮状态';op.btn_speed_up.node.activeInHierarchy=false;}
  let queue = null;
  const cell = {lab_name:{string:enemy.name},btn_attack:button('attack',()=>manager.service(rpc.startPVPBattle,{warId:7,targetId:options.wrongRow?1:2}).catch(()=>{}), options.wrongRow ? me : enemy)};
  class MarkNode {
    constructor(name){this.name=name;this.isValid=true;this.children=[];this.activeInHierarchy=true;}
    addComponent(){return {};}
    setPosition(){}
    addChild(child){child.parent=this;this.children.push(child);}
    destroy(){this.isValid=false;if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);}
  }
  MarkNode.EventType={TOUCH_START:'start',TOUCH_END:'end'};
  const row = new MarkNode('row');row.getComponent=()=>cell;
  const list = {getItemByListId:index=>index===0 && !options.unrendered ? row : null};
  let roleReads=0;
  const module = { enteredMapId:7, getSeasonMapData:()=>data, getSeasonMapMyRole:()=>{
    if(options.manualDuringGuard && !manualInjected && manager.service !== originalService){
      manualInjected=true;manager.service(rpc.moveSpeedUp,{warId:7}).catch(()=>{});
      op._speedCooldownUntil=now+2000;
    }
    if(options.rebindDuringCheck && ++roleReads>=2) cell.btn_attack.cbTarget={role:me,showAttack:true};
    return me;},
    getTimerByRole:()=>options.battleRemainingMs?{startTime:now-1000,endTime:now+options.battleRemainingMs}:null,
    startPVPBattle:params=>manager.service(rpc.startPVPBattle,params),
    isSameLegion:role=>role.lId>0 && role.lId===me.lId,
    canAttack(x,y,role){return originalModuleCanAttack ? originalModuleCanAttack(me).call(this,x,y,role)
      : role.id!==me.id && data.buildings.get(x+'_'+y).members.has(role.id) && role.lId!==me.lId;},
    getBuildingDataByPos:(x,y)=>data.buildings.get(x+'_'+y), getSeasonMapMySideId:()=>me.lId,
    getSeasonMap:()=>scene,
    getBuildingOpSnapshot:()=>({attackQueue:data.moveInfos.has(enemy.id) && helper.shouldHideStealthMarch(enemy)?[]:[{role:enemy,arriveAt:0}],defenseQueue:[]}) };
  scene.module=module;
  const conf={ MarchSpeed:1, MarchSpeedUpCD:30, MarchSpeedUpMinTime:10, MarchSpeedUpItem:[101,5] };
  const uiConfig = Object.fromEntries(['SeasonMapUI','SeasonQueueDetailUI','SeasonMarchSpeedUpUI'].map(id=>[id,{id,prefabPath:id}]));
  const mods = {
    'cc': {Node:MarkNode, Label:class{},Color:class{}, Button:class{}},
    'define-index.ts': {SeasonService:rpc}, 'configs.ts':{SeasonConstantCfg:{config:conf}},
    'role-helper.ts':{roleHelper:{getItemCount:()=>{if(options.itemThrows)throw Error('inventory unavailable');return options.items ?? 100;}}},
    'ui-common-cfg.ts':{CommonUICfgId:uiConfig},
    'ui-season-queue-detail.ts':{UISeasonQueueDetail:class {
      isSameLegion(role){return role.lId>0 && role.lId===this.module.getSeasonMapMySideId();}
      canAttack(role){return originalCanAttack ? originalCanAttack(me,{idle:1}).call(this,role) : role.id!==me.id && me.state===1 && !this.isSameLegion(role);}
    }},
    'shop-helper.ts':{shopHelper:{}},
    'season-helper.ts':{seasonHelper:helper},
    'service-manager.ts':{ServiceManager:{ins:manager}}, 'button-plus.ts':{default:class{}},
    'season-map-signal.ts':{SeasonMapInnerSignal:{buildingInteracted:{emit(value){op._bx=value.x;op._by=value.y;if(options.staleSelection){op._speedUpDisabledReason='';op.btn_speed_up.node.activeInHierarchy=true;}if(options.wrongDestination)op._bx+=1;if(options.expireOnSelect)move.arrive=now+9000;if(options.disableOnSelect)op.btn_speed_up.interactable=false;}}}},
    'season-queue-detail-role-cell.ts':{SeasonQueueDetailRoleCell:class{}},
    'season-op-queue-cell.ts':{SeasonOpQueueCell:class{}},
    'date-util.ts':{default:{get serverTime(){return options.noClock ? 0 : now;}}}
  };
  mods['season-map-signal.ts'].SeasonMapInnerSignal.mySeasonRoleExitedBattle = exitSignal;
  const context = {console:{info:(...v)=>logs.push(v)}, ROLE:me, seasonModule:module,
    System:{import:async name=>mods[name.replace('chunks:///_virtual/','')]},
    UIManager:{ins:{findOpen(cfg){assert.equal(typeof cfg,'object','UIManager requires configuration object');const name=cfg.id;assert.equal(cfg,uiConfig[name]);return name==='SeasonMapUI'?{view:{op}}:name==='SeasonQueueDetailUI'?queue:name==='SeasonMarchSpeedUpUI'?dialog:null;},
      open(cfg,params){assert.equal(cfg,uiConfig.SeasonQueueDetailUI,'open must use original config object');queue={buildingX:params.buildingX,buildingY:params.buildingY,attackEntries:[{roleId:2,role:enemy}],defenseEntries:[],view:{list_attack:list},module, isSameLegion:role=>role.lId>0 && role.lId===me.lId, canAttack(role){return originalCanAttack ? originalCanAttack(me,{idle:1}).call(this,role) : role.lId!==me.lId && me.state===1;}};}}},
    Date:class extends Date { static now(){return now;} }, setTimeout:timers,clearTimeout(){},
    setInterval(fn){intervals.set(++intervalId,fn);return intervalId;}, clearInterval(id){intervals.delete(id);}, eval:undefined, Function:undefined
  };
  vm.runInNewContext('(async()=>{'+source+'})()',context);
  async function run(promise) {
    let done=false,result,error;
    promise.then(v=>{result=v;done=true},e=>{error=e;done=true});
    for(let step=0;!done && step<2000;step++){
      // Flush nested module imports/async continuations before advancing virtual time.
      for(let i=0;i<50;i++)await Promise.resolve();
      if(done)break;
      tasks.sort((a,b)=>a.at-b.at);
      const t=tasks.shift(); if(!t)throw Error('unresolved fixture promise');
      now=t.at;t.fn();
    }
    if(error)throw error;
    assert.ok(done,'fixture completed');
    // Return values must serialize over CDP/filesystem bridges, including traces.
    JSON.stringify(result);
    return result;
  }
  function renderMarches(){
    assert(originalMarchUpdate,'route tests require current game source');
    class Vec {set(x,y){this.x=x;this.y=y;}}
    originalMarchUpdate(me,()=>({getChargeLevel:()=>0}),{PAY_GIFT:1},Vec,helper).call(scene);
    scene._dirtyMarch=false;
    return scene._flyFishManager.rows;
  }
  return {api:context.e0e1Season,me,enemy,move,data,op,sent,rpc,logs,run,manager,row,cell,module,ui:context.UIManager.ins,uiConfig,context,exitSignal,listeners,helper,originalHide,scene,renderMarches,intervals};
}

async function test(name, fn) { await fn(); console.log('PASS',name); }
(async()=>{
  await test('stop invalidates a marks activation awaiting module loading',async()=>{
    const f=fixture();const pending=f.api.marks({on:true});
    await f.api.stop();await f.run(pending);
    assert.equal((await f.run(f.api.diagnose())).marks_enabled,false);
  });
  await test('compact busy scan avoids queue construction and trace duplication',async()=>{
    const f=fixture();f.me.state=3;
    const original=f.module.getBuildingOpSnapshot;let calls=0;
    f.module.getBuildingOpSnapshot=function(...args){calls++;return original.apply(this,args);};
    const result=await f.run(f.api.candidates({compact:true}));assert.equal(result.ok,true);assert.equal(calls,0);
    f.me.state=1;const ready=await f.run(f.api.candidates({compact:true}));assert.equal(calls,1);
    assert.equal(ready.trace.find(row=>row.step==='candidates.end').values.result.attack,undefined);
  });
  await test('read-only polling keeps trace receipts without console spam',async()=>{
    const f=fixture();const n=f.logs.length;
    for(let i=0;i<20;i++){const result=await f.run(f.api.candidates());assert(result.trace.some(row=>row.step==='candidates.end'));}
    assert.equal(f.logs.length,n);
  });
  for (const options of [{nativeDenied:true},{noNativeCheck:true},{disabledButton:true},{staleSelection:true},{dialog:true}]) {
    await test('direct speed ignores UI state '+JSON.stringify(options),async()=>{
      const f=fixture(options);f.ui.findOpen=()=>{throw Error('must not inspect UI');};
      const result=await f.run(f.api.speedUp({}));
      assert.equal(result.confirmed,true);assert.equal(result.mode,'direct');
      assert.equal(f.sent.length,1);assert.equal(f.sent[0].fn,f.rpc.moveSpeedUp);
      assert.deepEqual(JSON.parse(JSON.stringify(f.sent[0].params)),{warId:7});
    });
  }
  await test('slow explicit service receipt is accepted',async()=>{
    const f=fixture({delay:2200});const r=await f.run(f.api.speedUp({max_times:3}));
    assert.equal(r.confirmed,true);assert(r.trace.some(x=>x.step==='rpc.settled'));
  });
  await test('timeout latches uncertain; no retry or unsafe reset while request in flight',async()=>{
    const f=fixture({delay:20000}); const r=await f.run(f.api.speedUp({}));
    assert.equal(r.status,'uncertain'); const n=f.sent.length;
    assert.equal((await f.run(f.api.speedUp({}))).status,'uncertain');
    assert.equal(f.sent.length,n); assert.equal((await f.run(f.api.reset())).ok,false);
  });
  await test('arrival/start/from sync changes retain budget; max_times enforced in JS',async()=>{
    const f=fixture({changeStart:true});
    const result=await f.run(f.api.speedUp({max_times:1}));
    assert.equal(result.times,1);
    assert.equal(result.trace.find(x=>x.step==='speed.preflight').values.remaining,400000);
    const march=await f.run(f.api.march()); assert.equal(march.speed_up.times,1);
    assert.equal((await f.run(f.api.speedUp({max_times:1}))).status,'waiting');
    assert.equal(f.sent.length,1);
    f.me.state=1; await f.run(f.api.march()); f.me.state=2;
    assert.equal((await f.run(f.api.march())).speed_up.times,0);
  });
  for (const opt of [{networkError:true},{malformed:true}]) {
    await test('ambiguous outcome stops '+JSON.stringify(opt),async()=>{
      const f=fixture(opt);assert.equal((await f.run(f.api.speedUp({}))).status,'uncertain');
      const n=f.sent.length; await f.run(f.api.speedUp({})); assert.equal(f.sent.length,n);
    });
  }
  await test('definite speed rejection waits instead of permanently stopping',async()=>{
    const f=fixture({reject:true});const r=await f.run(f.api.speedUp({}));
    assert.equal(r.status,'retry_later');assert.ok(r.message.includes('7'));
    assert.equal((await f.run(f.api.speedUp({}))).status,'waiting');assert.equal(f.sent.length,1);
  });
  for (const opt of [{items:0},{itemThrows:true},{noClock:true}]) {
    await test('invalid prerequisites never send '+JSON.stringify(opt),async()=>{
      const f=fixture(opt);const m=await f.run(f.api.march()); assert.equal(m.speed_up.available,false);
      assert.equal((await f.run(f.api.speedUp({}))).ok,false);assert.equal(f.sent.length,0);
    });
  }
  await test('correct rendered target and current threshold permit challenge',async()=>{
    const f=fixture();f.me.state=1; const r=await f.run(f.api.attack({roleId:2,power_ratio:100}));
    assert.equal(r.confirmed,true);assert.equal(r.roleId,2);
  });
  await test('direct attack does not depend on recycled UI row',async()=>{
    const f=fixture({wrongRow:true});f.me.state=1;
    assert.equal((await f.run(f.api.attack({roleId:2}))).confirmed,true);assert.equal(f.sent[0].params.targetId,2);
  });
  await test('direct request targets explicit role despite UI recycling',async()=>{
    const f=fixture({rebindDuringCheck:true});f.me.state=1;
    assert.equal((await f.run(f.api.attack({roleId:2}))).confirmed,true);assert.equal(f.sent[0].params.targetId,2);
  });
  await test('threshold recheck prevents stale or over-limit target',async()=>{
    const f=fixture();f.me.state=1;
    assert.equal((await f.run(f.api.attack({roleId:2,power_limit:400}))).ok,false);assert.equal(f.sent.length,0);
  });
  for(const remain of [7999,8000,9000,10000,10001]) {
    await test('direct speed boundary '+remain+'ms',async()=>{
      const f=fixture();f.move.arrive=100000+remain;
      const r=await f.run(f.api.speedUp({}));assert.equal(r.ok,remain>=8000);
      assert.equal(f.sent.length,remain>=8000?1:0);
      if(remain>=8000)assert.equal(r.final_attempt,remain<=10000);
    });
  }
  for(const state of [0,2,3,4,5]) {
    await test('non-idle state never challenges '+state,async()=>{
      const f=fixture();f.me.state=state;
      assert.equal((await f.run(f.api.attack({roleId:2}))).ok,false);
      assert.equal(f.sent.length,0);
    });
  }
  for(const change of ['sameSide','selfAbsent','targetAbsent','unknownPower','equalPower','lowerCap']) {
    await test('attack eligibility blocks '+change,async()=>{
      const f=fixture();f.me.state=1;
      if(change==='sameSide')f.enemy.lId=f.me.lId;
      if(change==='selfAbsent')f.data.buildings.get('1_1').members.delete(1);
      if(change==='targetAbsent')f.data.buildings.get('1_1').members.delete(2);
      if(change==='unknownPower'){f.enemy.planPower=[0];f.enemy.power=0;}
      if(change==='equalPower'){f.enemy.planPower=[1000];f.enemy.power=1000;}
      const result=await f.run(f.api.attack({roleId:2,power_limit:change==='lowerCap'?500:0}));
      assert.equal(result.ok,false);assert.equal(f.sent.length,0);
    });
  }
  await test('flag reading sorts synchronized members without sending RPC',async()=>{
    const f=fixture();f.me.flagId=3;f.enemy.flagId=4;
    f.module.seasonBattleFlagData={getFlagConfig:id=>({name:'战旗'+id})};
    const flags=await f.run(f.api.flags());
    assert.equal(flags.source,'season_map');assert.equal(flags.groups[0].members[0].roleId,1);
    assert.equal(flags.groups[0].members[0].flag,'战旗3');assert.equal(f.sent.length,0);
  });
  for(const mode of ['visible','unrendered','inactive','recycled','notStealth']) {
    await test('stealth marker respects rendered UI '+mode,async()=>{
      const f=fixture({unrendered:mode==='unrendered'});f.enemy.ext=new Map([[4,mode==='notStealth'?0:1]]);
      f.ui.open(f.uiConfig.SeasonQueueDetailUI,{buildingX:1,buildingY:1});
      if(mode==='inactive')f.row.activeInHierarchy=false;
      if(mode==='recycled')f.cell.lab_name.string='other role';
      const result=await f.run(f.api.marks({on:true}));
      assert.equal(result.marked,mode==='visible'?1:0);assert.equal(f.sent.length,0);
      await f.run(f.api.stop());assert.equal(f.row.children.length,0);
    });
  }
  await test('hot upgrade preserves action budgets and replaces stale script',async()=>{
    const f=fixture();await f.run(f.api.speedUp({max_times:1}));
    f.api.version='old-fixture';
    await f.run(vm.runInNewContext('(async()=>{'+source+'})()',f.context));
    const updated=f.context.e0e1Season;
    assert.equal(updated.version,'2026-10-24-routes-v17');assert.notEqual(updated,f.api);
    assert.equal((await f.run(updated.march())).speed_up.times,1);
    assert.equal((await f.run(updated.speedUp({max_times:1}))).ok,false);
    assert.equal(f.sent.length,1);
  });
  await test('hot upgrade refuses unresolved outcome without resetting old script',async()=>{
    const f=fixture({networkError:true});await f.run(f.api.speedUp({}));f.api.version='old-fixture';
    await assert.rejects(f.run(vm.runInNewContext('(async()=>{'+source+'})()',f.context)),/旧血月脚本/);
    assert.equal(f.context.e0e1Season,f.api);
    assert.equal((await f.run(f.api.diagnose())).uncertain,true);
  });
  await test('native and custom speed intervals use dispatch time',async()=>{
    const f=fixture();assert.equal((await f.run(f.api.speedUp({}))).confirmed,true);
    assert.equal((await f.run(f.api.speedUp({}))).status,'waiting');
    assert.equal((await f.run(f.api.march())).speed_up.interval_seconds,30);
    await f.run(new Promise(r=>f.context.setTimeout(r,1000)));
    assert.equal((await f.run(f.api.speedUp({interval_seconds:1}))).confirmed,true);
    assert.equal(f.sent.length,2);
  });
  await test('final window rejection is attempted once and does not affect next march',async()=>{
    const options={reject:true};const f=fixture(options);f.move.arrive=109000;
    assert.equal((await f.run(f.api.speedUp({interval_seconds:1}))).status,'retry_later');
    await f.run(new Promise(r=>f.context.setTimeout(r,1000)));f.move.arrive=109500;
    assert.equal((await f.run(f.api.speedUp({interval_seconds:1}))).status,'waiting');assert.equal(f.sent.length,1);
    f.me.state=1;await f.run(f.api.march());f.me.state=2;f.move.arrive=500000;options.reject=false;
    assert.equal((await f.run(f.api.speedUp({interval_seconds:1}))).confirmed,true);assert.equal(f.sent.length,2);
  });
  await test('accepted challenge blocks duplicate then immediately chains after matching end',async()=>{
    const f=fixture();f.me.state=1;
    assert.equal((await f.run(f.api.attack({roleId:2}))).confirmed,true);
    assert.equal((await f.run(f.api.attack({roleId:2}))).status,'waiting');assert.equal(f.sent.length,1);
    f.exitSignal.emit({buildingId:'1_1',other:2,isRobot:false,isMeAtk:true});
    assert.equal((await f.run(f.api.attack({roleId:2}))).confirmed,true);assert.equal(f.sent.length,2);
  });
  await test('battle state transition releases next challenge without end event',async()=>{
    const f=fixture();f.me.state=1;await f.run(f.api.attack({roleId:2}));
    f.me.state=3;await f.run(f.api.candidates({compact:true}));
    f.me.state=1;await f.run(f.api.candidates({compact:true}));
    assert.equal((await f.run(f.api.attack({roleId:2}))).confirmed,true);assert.equal(f.sent.length,2);
  });
  await test('direct timeout stops replay until outstanding request settles',async()=>{
    const f=fixture({delay:20000});f.me.state=1;
    const result=await f.run(f.api.attack({roleId:2}));assert.equal(result.status,'uncertain');
    assert.equal((await f.run(f.api.attack({roleId:2}))).status,'uncertain');
    assert.equal(f.sent.length,1);assert.equal((await f.run(f.api.reset())).ok,false);
  });
  await test('native battle timer supports 200ms preparation without premature request',async()=>{
    const f=fixture({battleRemainingMs:200});f.me.state=3;
    const snapshot=await f.run(f.api.candidates());
    assert.equal(snapshot.battle_end_time-snapshot.server_now,200);
    assert.equal((await f.run(f.api.attack({roleId:2}))).ok,false);assert.equal(f.sent.length,0);
  });
  await test('known moving target response does not poison future attacks',async()=>{
    const f=fixture({reject:true,rejectCode:350018});f.me.state=1;
    const result=await f.run(f.api.attack({roleId:2}));
    assert.equal(result.status,'target_unavailable');assert.equal(result.roleId,2);
    assert.equal(result.request_sent,true);assert.equal((await f.run(f.api.diagnose())).uncertain,false);
  });
  await test('definite challenge rejection permits later retry without resetting success count',async()=>{
    const options={reject:true};const f=fixture(options);f.me.state=1;
    const rejected=await f.run(f.api.attack({roleId:2}));
    assert.equal(rejected.status,'retry_later');assert.equal(rejected.request_sent,true);
    options.reject=false;
    assert.equal((await f.run(f.api.attack({roleId:2}))).battles,1);
  });
  await test('visible resident stealth role remains attackable without changing visibility',async()=>{
    const f=fixture();f.me.state=1;f.enemy.ext=new Map([[4,1]]);
    const snapshot=await f.run(f.api.candidates());
    assert.equal(snapshot.attack[0].stealth,true);assert.equal(snapshot.attack[0].attackable,true);
    f.ui.findOpen=()=>{throw Error('must not require UI');};
    assert.equal((await f.run(f.api.attack({roleId:2}))).confirmed,true);
    assert.equal(f.enemy.ext.get(4),1);
  });
  await test('map sidebar uses its own cell type without opening full queue',async()=>{
    const f=fixture();f.enemy.ext=new Map([[4,1]]);
    f.op._attackEntries=[{role:f.enemy}];f.op.list_attack={getItemByListId:()=>f.row};
    f.cell.lab_name=undefined;
    f.cell.head={node:{getChildByName:name=>name==='nd_sneath'?{active:true}:null}};
    const result=await f.run(f.api.marks({on:true}));assert.equal(result.marked,1);
    assert.equal(f.ui.findOpen(f.uiConfig.SeasonQueueDetailUI),null);assert.equal(f.sent.length,0);
    assert.equal((await f.run(f.api.diagnose())).marks_enabled,true);
    await f.run(f.api.stop());assert.equal(f.row.children.length,0);
  });
  await test('flag probe uses queue base power instead of combined power',async()=>{
    const f=fixture();f.me.power=2000;f.me.planPower=[800,1200];f.enemy.power=1500;f.enemy.planPower=[1000,500];
    f.enemy.lId=f.me.lId;
    const result=await f.run(f.api.flags());const members=result.groups[0].members;
    assert.equal(members[0].roleId,2);assert.equal(members[0].power,1000);
    assert.equal(members[0].season_power,500);assert.equal(members[0].total_power,1500);
    delete f.enemy.planPower;
    const next=await f.run(f.api.flags());assert.equal(next.groups[0].members.find(r=>r.roleId===2).power,null);
  });
  await test('unsent arrival and missing clock recover without permanent rejection',async()=>{
    for(const options of [{noClock:true},{}]){
      const f=fixture(options);if(!options.noClock)f.me.state=1;
      const r=await f.run(f.api.speedUp({}));
      assert(['waiting','unavailable'].includes(r.status));assert.equal(r.request_sent,false);
      assert.equal(f.sent.length,0);assert.equal((await f.run(f.api.diagnose())).uncertain,false);
      options.noClock=false;f.me.state=2;
      assert.equal((await f.run(f.api.speedUp({}))).confirmed,true);
    }
  });
  await test('native end event confirms only this challenge and survives stop/upgrade',async()=>{
    const f=fixture();f.me.state=1;
    const receipt=await f.run(f.api.attack({roleId:2}));
    const event={buildingId:'1_1',other:2,isRobot:false,isMeAtk:true};
    for(const patch of [{other:3},{buildingId:'2_2'},{isRobot:true},{isMeAtk:false}]){
      f.exitSignal.emit({...event,...patch});
      assert.equal((await f.run(f.api.candidates())).attack_observation.completed,false);
    }
    await f.run(f.api.stop());assert.equal(f.listeners.size,1);
    f.api.version='old-fixture';await f.run(vm.runInNewContext('(async()=>{'+source+'})()',f.context));
    const api=f.context.e0e1Season;await f.run(api.candidates());assert.equal(f.listeners.size,1);
    f.exitSignal.emit(event);
    const snapshot=await f.run(api.candidates());
    assert.equal(snapshot.attack_observation.token,receipt.attack_token);
    assert.equal(snapshot.attack_observation.completed,true);assert.equal(f.listeners.size,0);
    await f.run(api.reset());assert.equal((await f.run(api.candidates())).attack_observation,null);
    assert.equal(f.sent.length,1);
  });
  await test('fast battle end before successful receipt is retained; wrong war ignored',async()=>{
    const f=fixture({delay:2200});f.me.state=1;
    f.context.setTimeout(()=>{
      const event={buildingId:'1_1',other:2,isRobot:false,isMeAtk:true};
      f.module.enteredMapId=8;f.exitSignal.emit(event);assert.equal(f.listeners.size,1);
      f.module.enteredMapId=7;f.exitSignal.emit(event);
    },1000);
    const receipt=await f.run(f.api.attack({roleId:2}));
    assert.equal(receipt.confirmed,true);
    const snapshot=await f.run(f.api.candidates());
    assert.equal(snapshot.self_state,1);
    assert.equal(snapshot.attack_observation.token,receipt.attack_token);
    assert.equal(snapshot.attack_observation.completed,true);
    assert.equal(f.sent.length,1);
  });
  await test('reveal restores native march and route data and stop restores original filter',async()=>{
    const f=fixture();f.me.state=1;f.enemy.ext=new Map([[4,1]]);f.enemy.state=2;
    const hidden={id:2,from:{x:3,y:4},to:{x:5,y:6},start:90000,arrive:200000};
    f.data.moveInfos.set(2,hidden);
    assert.equal((await f.run(f.api.candidates())).attack.length,0);
    if(originalMarchUpdate)assert.equal(f.renderMarches().some(row=>row.marchId===2),false);
    const result=await f.run(f.api.marks({on:true}));assert.equal(result.routes_enabled,true);
    assert.equal(f.scene._dirtyMarch,true);
    assert.equal((await f.run(f.api.candidates())).attack.length,1);
    assert.equal((await f.run(f.api.candidates())).attack[0].attackable,false);
    if(originalMarchUpdate){
      const march=f.renderMarches().find(row=>row.marchId===2).march;
      assert.deepEqual(march.from,{x:3,y:4});assert.deepEqual(march.to,{x:5,y:6});
      assert.equal(march.startTime,90000);assert.equal(march.endTime,200000);
      assert.equal(march.player.isStealth,true);assert.equal(march.player.roleId,2);
    }
    assert.equal(f.enemy.ext.get(4),1);assert.equal(f.data.moveInfos.get(2),hidden);
    await f.run(f.api.stop());
    assert.equal(f.helper.shouldHideStealthMarch,f.originalHide);
    assert.equal(f.scene._dirtyMarch,true);assert.equal(f.intervals.size,0);
    if(originalMarchUpdate)assert.equal(f.renderMarches().some(row=>row.marchId===2),false);
    assert.equal((await f.run(f.api.diagnose())).routes_enabled,false);assert.equal(f.sent.length,0);
  });
  await test('reveal refreshes a replacement scene and hot upgrade restores hooks without stacking',async()=>{
    const f=fixture();await f.run(f.api.marks({on:true}));const oldHook=f.helper.shouldHideStealthMarch;
    const next={sourceMap:{},_dirtyMarch:false};f.module.getSeasonMap=()=>next;
    for(const fn of f.intervals.values())fn();assert.equal(next._dirtyMarch,true);
    f.api.version='old-fixture';await f.run(vm.runInNewContext('(async()=>{'+source+'})()',f.context));
    assert.equal(f.helper.shouldHideStealthMarch,f.originalHide);
    const api=f.context.e0e1Season;await f.run(api.marks({on:true}));
    assert.notEqual(f.helper.shouldHideStealthMarch,oldHook);assert.equal(f.intervals.size,1);
    await f.run(api.marks({on:false}));assert.equal(f.helper.shouldHideStealthMarch,f.originalHide);
    assert.equal(f.intervals.size,0);
  });
  await test('route reveal tolerates native map getter throwing outside the battlefield',async()=>{
    const f=fixture();f.module.getSeasonMap=()=>{throw Error('season_map is absent');};
    assert.equal((await f.run(f.api.marks({on:true}))).routes_enabled,true);
    for(const fn of f.intervals.values())fn();
    const info=await f.run(f.api.diagnose());assert.equal(info.ok,true);
    assert.equal(info.rendered_marches,0);assert.equal(info.mark_error,null);
    await f.run(f.api.stop());assert.equal(f.helper.shouldHideStealthMarch,f.originalHide);
  });
  console.log('Original UI eligibility source: '+(process.env.BLOODMOON_GAME_SOURCE || (originalSpeedCheck ? 'verified from output game.js' : 'not available; fallback fixture')));
  console.log('All offline bloodmoon JS fixtures passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
