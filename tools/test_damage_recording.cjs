// Execute both the previous analyzer and the recording-only path against the
// same deterministic native observations. Python consumes this oracle fixture.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('tools/js/damage_curve_probe.js','utf8');
const table=rows=>({list:rows,getById:id=>rows.find(row=>row.id===Number(id))});
async function run(raw){
 const cfg={SkillCfg:table([{id:1,name:'普攻',type:1,skillFunctionType:1},
  {id:2001,name:'测试天书',type:4,skillFunctionType:4,bookId:2000},
  {id:3001,name:'雷击',type:1,skillFunctionType:7},
  {id:4001,name:'战旗技能',type:4,skillFunctionType:4},
  {id:5001,name:'召唤入口',skillFunctionType:17,bookId:2000,_properties:[{name:'sumSkill',expression:'5002'}]},
  {id:5002,name:'召唤物伤害',type:4,skillFunctionType:4}]),
  SkillBookCfg:table([{id:2000,name:'测试天书',type:0}]),
  EvolutionSkillCfg:table([{id:9,skillId:5001,evolutionId:20,skillLevel:1},{id:10,skillId:5001,evolutionId:20,skillLevel:2}]),
  SkillBookEvolutionCfg:table([{id:20,name:'分支',skillBookBelong:2000,evolutionPath:2}]),
  FashionCfg:table([{id:3,name:'雷法尊者',skill:[],attackSkill:[[3001]]}]),
  SeasonWarRestraintCfg:table([{id:4,name:'战旗甲',pvpSkill:[4001]}]),
  BuffCfg:table([])};
 const ctx={console:{log(){}},Map,WeakMap,Set,Date,Promise,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},__e0e1RegisterRuntimeToggle(){}};
 const api=await vm.runInNewContext('(async()=>{'+source+`;return {
 configure(cfg,raw){E0E1_CFG=cfg;E0E1_RECORD_ONLY=raw;E0E1_TYPE_COMPONENTS={CompFly:class{}};},
 state:e0e1NewState,handler:e0e1MakeHandler,inputs:e0e1FactorInputs,sample:e0e1SampleFormulaState,
 set(state){E0E1_SIDES.self=state;E0E1_RECORD_CATALOG=e0e1RecordCatalog();},
 frame(frame){E0E1_DAMAGE_STACK=[frame];},collect:damageCurveJson,
 pvp(){E0E1_PVP={instanceKey:'pair',battleType:26,cfg:{PVPInitScore:100,PVPBaseBonus:10,PVPInitVariable:2},
   skipped:false,samples:[{t:0,sec:0,selfBoss:100,otherBoss:0,selfScore:105,otherScore:95},
   {t:1,sec:1,selfBoss:100,otherBoss:100,selfScore:95,otherScore:105}],
   attrSeconds:[{sec:0,self:{117:.5},other:{118:.1},selfSources:{},otherSources:{}}]};},
 failAnalysis(){e0e1Classify=e0e1Bump=e0e1FactorParts=e0e1BuildBuffGraph=e0e1DerivedScores=function(){throw Error('analysis executed in game');};},
 guards(){JSON.stringify=function(){throw Error('hot-path stringify');};},status:damageCurveStatus
 };})()`,ctx);
 api.configure(cfg,raw);
 function attrs(values){const map=new Map(Object.entries(values).map(([key,value])=>[Number(key),{baseValue:value*([1,4].includes(Number(key))?1:10000),addScaleValue:0,addAbsoluteValue:0}]));const group={attributes:map,get:key=>values[key]||0};return {attributes:group,get:group.get};}
 const hero={uuid:10,name:'英雄',compCampFriend:true,compAttributes:attrs({1:100,4:1000,104:.5,115:.2,117:.4,123:.1,708:.3}),
  compSkillAssistant:{allSkills:new Map()},compLife:{max:1000},getComponent(){return null;}};
 const boss={uuid:11,name:'首领',compBoss:{},compMonster:{},compAttributes:attrs({4:1000,105:.1,118:.2}),
  compLife:{current:900,max:1000},getComponent(){return null;}};
 const world={instanceId:1,options:{battleData:{type:26,randomSeed:7}},battleTime:{battleTime:0},getFightHero:()=>hero};
 const state=api.state(world,'self',false);state.activeBranches=[{bookId:2000,bookName:'测试天书',branchId:20,branchName:'分支',level:3,path:2,pathName:'主阶',skillIds:[5001]}];
 api.set(state);const handler=api.handler(state);
 if(raw){api.failAnalysis();api.guards();}
 const inputs=[{skill:1,dmg:40,t:.2},{skill:2001,dmg:60,t:1.2},{skill:3001,dmg:80,t:2.2},
   {skill:4001,dmg:10,t:3.2},{skill:5002,dmg:70,t:4.2},{skill:2001,dmg:0,t:5.2}];
 for(const event of inputs){
   world.battleTime.battleTime=event.t;
   const context={battleWorld:world,source:hero,target:boss,skillId:event.skill,sourceAttr:hero.compAttributes.attributes,targetAttr:boss.compAttributes.attributes,
    atk:100,damage:event.dmg+10,isCrit:false,isSkillCrit:false,multiplier:{baseCoeff:1,dmgAddRate:1.4,elementAddRate:1,dmgTypeRate:0,hpDmgAddRate:0,skillTypeAddRate:.2,attackDmgRate:0,finalDmgRate:.1,pvpDmgRate:.2},
    skillContext:{shareData:{getElementAttrType:()=>[],getElementAttrTypeSpecialSkill:()=>[],getQualityAttrTypeSpecialSkill:()=>[]}}};
   api.frame({context,snapshot:api.inputs(context)});handler(hero,event.skill,event.dmg,boss,false);api.sample(state);
 }
 api.pvp();const packet=api.collect();
 if(raw){
  assert.equal(packet.recordingSchema,1);assert.equal(packet.self.events.length,5);
  assert.equal(Object.keys(state.total).length,0);assert.equal(state.factorSnapshots.length,0);
  assert.equal(packet.self.hits.length,6);assert.equal(api.status().recordOnly,true);
  const next=api.collect({stream:packet.stream,includeCatalog:false,self:{instanceId:1,events:5,hits:6},pair:'pair',samples:2,attrs:1});
  assert.equal(next.catalog,undefined);assert.equal(next.self.events.length,0);assert.equal(next.self.hits.length,0);
  assert.equal(next.pvp.sampleStart,1);assert.equal(next.pvp.samples.length,1);
 }
 return packet;
}
(async()=>{
 const imports=[],runtime={console:{log(){}},Map,WeakMap,Set,Date,Promise,setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},
  UIManager:{ins:{viewParams:{}}},System:{import:async name=>{imports.push(name);return name.endsWith('configs.ts')?{}:name.endsWith('battle-manager.ts')?{BattleManager:{ins:{getBattles:()=>[]}}}:{};}}};
 runtime.__e0e1RegisterRuntimeToggle=toggle=>{runtime.toggle=toggle;};
 await vm.runInNewContext('(async()=>{'+source+'})()',runtime);
 await runtime.toggle.enable();
 assert.equal(runtime.damageCurveStatus().recordOnly,true);assert.equal(runtime.damageCurveJson().recordingSchema,1);
 assert.equal(imports.some(name=>/\/(damage-context|skill-context|DecimalNumber|comp-hero)\.ts$/.test(name)),false);
 const firstStream=runtime.damageCurveJson().stream;
 await runtime.toggle.disable();
 await vm.runInNewContext('(async()=>{'+source+'})()',runtime);
 await runtime.toggle.enable();assert.notEqual(runtime.damageCurveJson().stream,firstStream);
 await runtime.toggle.disable();
 const legacy=await run(false),raw=await run(true);
 if(process.argv.includes('--json'))process.stdout.write(JSON.stringify({legacy,raw}));
 else console.log('PASS recording hot path never classifies, aggregates, executes formulas, builds buff graph or stringifies; acknowledged deltas omit old events/catalog');
})().catch(error=>{console.error(error);process.exitCode=1;});
