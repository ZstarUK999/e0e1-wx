const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'js/damage_curve_probe.js'),'utf8');
class Signal{constructor(){this.handlers=[];}add(fn){this.handlers.push(fn);}remove(fn){this.handlers=this.handlers.filter(h=>h!==fn);}dispatch(){this.handlers.slice().forEach(fn=>fn());}}
(async()=>{
 const api=await vm.runInNewContext('(async()=>{'+source+`;return {attach:e0e1TryAttachWorld,sample:e0e1SamplePvp,collect:e0e1Collect,stop:damageCurveStop};})()`,{console:{log(){}},Map,Date,Promise,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},__e0e1RegisterRuntimeToggle(){}});
 let serial=0;
 function world(type,isSelf,metrics){
  const values={1:isSelf?100:80,4:1000,117:.5,118:.2},hero={compAttributes:{get:k=>values[k]||0}};
  return {instanceId:++serial,values,options:{mineInfo:{isSelf,score:0,pvpMetrics:metrics},battleData:{type,randomSeed:1}},battleTime:{battleTime:0},getFightHero:()=>hero,
   battleSignal:{$skillDamageCollect:new Signal(),timeBattleTickSignal:new Signal(),battleRunningSignal:new Signal()}};
 }
 for(const type of [26,20])for(const enemyFirst of [false,true]){
  const metrics={},a=world(type,true,metrics),b=world(type,false,metrics);
  for(const w of enemyFirst?[b,a]:[a,b]){assert(api.attach(w));w.battleSignal.battleRunningSignal.dispatch();}
  let report=api.collect();
  assert.equal(report.self.initialAttributes.status,'captured');assert.equal(report.other.initialAttributes.status,'captured');
  assert.equal(report.self.initialAttributes.attributes[1],100);assert.equal(report.other.initialAttributes.attributes[1],80);
  assert.equal(report.self.initialAttributes.time,0);assert.equal(report.self.eventCount,0);assert.equal(report.other.totalDamage,0);
  a.values[1]=999;a.battleTime.battleTime=1;a.battleSignal.battleRunningSignal.dispatch();api.sample();
  assert.equal(api.collect().self.initialAttributes.attributes[1],100,'initial snapshot must remain frozen');
  api.stop();
  for(const w of [a,b])for(const sig of Object.values(w.battleSignal))assert.equal(sig.handlers.length,0,'remove all listeners');
 }
 const late=world(20,true,{});late.battleTime.battleTime=2;api.attach(late);api.sample();
 assert.equal(api.collect().self.initialAttributes.status,'missed');assert.equal(api.collect().self.initialAttributes.attributes,undefined);
 api.stop();
 console.log('PASS zero-damage initial attributes for friend/season and both creation orders; frozen values, late capture explicitly missing and listener cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
