const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
 const source=fs.readFileSync(require('node:path').join(__dirname,'js/damage_curve_probe.js'),'utf8');
 const removed=[],cleared=[];
 const api=await vm.runInNewContext('(async()=>{'+source+`;return {
 setup(world){const state=e0e1NewState(world,'self',false);state.eventCount=3;E0E1_SIDES.self=state;E0E1_HOOKS=[{world,state,handler:1,tickHandler:2}];E0E1_REPLAY_CONTEXTS=[{controller:{}}];E0E1_BM_PATCHED=true;E0E1_TIMER=42;e0e1FindWorlds=()=>[];},
 attach:e0e1AttachAll,stop:damageCurveStop,
 inspect:()=>({world:E0E1_SIDES.self && E0E1_SIDES.self.world,events:E0E1_SIDES.self && E0E1_SIDES.self.eventCount,hooks:E0E1_HOOKS.length,replays:E0E1_REPLAY_CONTEXTS.length,timer:E0E1_TIMER})};})()`,
 {console:{log(){}},Map,Date,Promise,setTimeout,clearTimeout,setInterval,clearInterval:id=>cleared.push(id),__e0e1RegisterRuntimeToggle(){}});
 const signal={remove:h=>removed.push(h)};
 api.setup({battleSignal:{$skillDamageCollect:signal,timeBattleTickSignal:signal}});
 api.attach();let state=api.inspect();
 assert.equal(state.world,null);assert.equal(state.events,3);assert.equal(state.hooks,0);assert.equal(state.replays,0);
 assert.deepEqual(removed,[1,2]);api.stop();api.stop();
 assert.deepEqual(cleared,[42]);assert.equal(api.inspect().timer,null);
 console.log('PASS: detached world released, report retained, listeners removed, empty replay controller released, stop idempotent');
})().catch(e=>{console.error(e);process.exitCode=1;});
