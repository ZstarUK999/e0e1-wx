const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const source=fs.readFileSync(path.join(__dirname,'js/damage_curve_probe.js'),'utf8');
 const api=await vm.runInNewContext('(async()=>{'+source+';return {eligible:e0e1ReportableWorld,watch:e0e1WatchWorld,counts:()=>[E0E1_WATCHED.length,E0E1_HOOKS.length]};})()', {console:{log(){}},setTimeout,clearTimeout,setInterval,clearInterval,Map,Date,Promise,__e0e1RegisterRuntimeToggle(){}});
 for(const type of [0,1,2,3,4,5,6,7,9,10,11,12,13,14,17,21,22,23,27,101,102,undefined]) {
  const w={options:{battleData:{type}},battleSignal:{$skillDamageCollect:{add(){throw Error('PvE must not subscribe');}}}};
  assert.equal(api.eligible(w),false);api.watch(w);
 }
 assert.deepEqual(Array.from(api.counts()),[0,0]);
 for(const type of [8,16,18,19,20,24,25,26]) assert.equal(api.eligible({options:{battleData:{type}}}),true);
 console.log('PASS: PvE never watched/subscribed; official PvP types retained');
})().catch(e=>{console.error(e);process.exitCode=1;});
