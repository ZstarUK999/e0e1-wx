// Offline game-module fixtures. No browser, game, sockets or real RPCs.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const defaultSource = fs.existsSync(path.join(__dirname, 'js/season_bloodmoon.js'))
  ? path.join(__dirname, 'js/season_bloodmoon.js') : path.join(__dirname, 'season_bloodmoon.js');
const source = fs.readFileSync(process.argv[2] || defaultSource, 'utf8');

function fixture(options = {}) {
  let now = 100000, next = 0, tasks = [], logs = [], sent = [];
  const timers = (fn, ms) => { tasks.push({ id: ++next, at: now + ms, fn }); return next; };
  const me = { id: 1, name: 'self', lId: 10, state: 2, power: 1000, planPower: [1000], position: {x: 1, y: 1} };
  const enemy = { id: 2, name: 'enemy', lId: 20, state: 1, power: 500, planPower: [500] };
  const move = {id: 1, from: {x:1,y:1}, to: {x:2,y:2}, start: 90000, arrive: 500000};
  const data = { roles: new Map([[1,me],[2,enemy]]), legions: new Map(), moveInfos: new Map([[1,move]]),
    buildings: new Map([['1_1', {members: new Set([1,2])}]]) };
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
      resolve(options.malformed ? {} : {err: options.reject ? {code:7,error:'denied'} : null, resp:{}});
    }, options.delay || 100));
  }};
  function button(name, click, role) {
    const b = {interactable:true, enabledInHierarchy:true, continuous:false, clickInteractable:true,
      cbTarget: role ? {role,showAttack:true} : null};
    b.node = { name, activeInHierarchy:true, emit(type) { if(type==='end') click(); } };
    return b;
  }
  const op = { _speedCooldownUntil:0, _speedUpDisabledReason:'' };
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
  let queue = null;
  const cell = {btn_attack:button('attack',()=>manager.service(rpc.startPVPBattle,{warId:7,targetId:options.wrongRow?1:2}).catch(()=>{}), options.wrongRow ? me : enemy)};
  const row = {getComponent:()=>cell};
  const list = {getItemByListId:()=>row};
  const module = { enteredMapId:7, getSeasonMapData:()=>data, getSeasonMapMyRole:()=>me,
    getBuildingOpSnapshot:()=>({attackQueue:[{role:enemy,arriveAt:0}],defenseQueue:[]}) };
  const conf={ MarchSpeed:1, MarchSpeedUpCD:30, MarchSpeedUpMinTime:10, MarchSpeedUpItem:[101,5] };
  const mods = {
    'cc': {Node:{EventType:{TOUCH_START:'start',TOUCH_END:'end'}}, Button:class{}},
    'define-index.ts': {SeasonService:rpc}, 'configs.ts':{SeasonConstantCfg:{config:conf}},
    'role-helper.ts':{roleHelper:{getItemCount:()=>100}},
    'shop-helper.ts':{shopHelper:{getItemCount:()=>{if(options.itemThrows)throw Error('inventory unavailable');return options.items ?? 100;}}},
    'service-manager.ts':{ServiceManager:{ins:manager}}, 'button-plus.ts':{default:class{}},
    'season-map-signal.ts':{SeasonMapInnerSignal:{buildingInteracted:{emit(){}}}},
    'season-queue-detail-role-cell.ts':{SeasonQueueDetailRoleCell:class{}},
    'date-util.ts':{default:{get serverTime(){return options.noClock ? 0 : now;}}}
  };
  const context = {console:{info:(...v)=>logs.push(v)}, ROLE:me, seasonModule:module,
    System:{import:async name=>mods[name.replace('chunks:///_virtual/','')]},
    UIManager:{ins:{findOpen(name){return name==='SeasonMapUI'?{view:{op}}:name==='SeasonQueueDetailUI'?queue:name==='SeasonMarchSpeedUpUI'?dialog:null;},
      open(){queue={attackEntries:[{roleId:2,role:enemy}],defenseEntries:[],view:{list_attack:list},canAttack:()=>true};}}},
    Date:class extends Date { static now(){return now;} }, setTimeout:timers,clearTimeout(){},
    setInterval:()=>1, clearInterval(){}, eval:undefined, Function:undefined
  };
  vm.runInNewContext(source,context);
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
  return {api:context.e0e1Season,me,enemy,move,data,op,sent,rpc,logs,run,manager};
}

async function test(name, fn) { await fn(); console.log('PASS',name); }
(async()=>{
  await test('slow correct receipt wins over unrelated first RPC; branch trace serializes',async()=>{
    const f=fixture({delay:2200,unrelated:true});
    const r=await f.run(f.api.speedUp({max_times:3}));
    assert.equal(r.confirmed,true); assert.ok(r.trace.some(x=>x.step==='rpc.ignored'));
    assert.ok(r.trace.some(x=>x.step==='speed.preflight'));
  });
  await test('normal confirmation dialog emits exactly one speed request',async()=>{
    const f=fixture({dialog:true});const r=await f.run(f.api.speedUp({max_times:3}));
    assert.equal(r.confirmed,true);assert.equal(f.sent.length,1);
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
    assert.equal(result.trace.find(x=>x.step==='speed.preflight').values.move.arrive,500000);
    const march=await f.run(f.api.march()); assert.equal(march.speed_up.times,1);
    assert.equal((await f.run(f.api.speedUp({max_times:1}))).status,'rejected');
    assert.equal(f.sent.length,1);
    f.me.state=1; await f.run(f.api.march()); f.me.state=2;
    assert.equal((await f.run(f.api.march())).speed_up.times,0);
  });
  for (const opt of [{networkError:true},{malformed:true},{wrongWar:true},{noRequest:true},{duplicate:true}]) {
    await test('ambiguous outcome stops '+JSON.stringify(opt),async()=>{
      const f=fixture(opt);assert.equal((await f.run(f.api.speedUp({}))).status,'uncertain');
      const n=f.sent.length; await f.run(f.api.speedUp({})); assert.equal(f.sent.length,n);
    });
  }
  await test('server rejection is rejected and includes server code in trace',async()=>{
    const f=fixture({reject:true});const r=await f.run(f.api.speedUp({}));
    assert.equal(r.status,'rejected');assert.ok(r.message.includes('7'));
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
  await test('recycled row binding prevents clicking wrong target',async()=>{
    const f=fixture({wrongRow:true});f.me.state=1;
    assert.equal((await f.run(f.api.attack({roleId:2}))).ok,false);assert.equal(f.sent.length,0);
  });
  await test('threshold recheck prevents stale or over-limit target',async()=>{
    const f=fixture();f.me.state=1;
    assert.equal((await f.run(f.api.attack({roleId:2,power_limit:400}))).ok,false);assert.equal(f.sent.length,0);
  });
  console.log('All offline bloodmoon JS fixtures passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
