const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'tools/js/damage_curve_probe.js'),'utf8');
const table=rows=>({list:rows,getById:id=>rows.find(r=>r.id===Number(id))});
class D{constructor(v){this.v=v;}toNumber(){return this.v;}add(x){return new D(this.v+Number(x.toNumber?x.toNumber():x));}sub(x){return new D(this.v-Number(x.toNumber?x.toNumber():x));}}
D.ZERO=new D(0);
(async()=>{
 const api=await vm.runInNewContext('(async()=>{'+source+`;return {configure(cfg,modules){E0E1_CFG=cfg;E0E1_FORMULA_MODULES=modules;},sample:e0e1SampleFormulaState,state:e0e1NewState,collect:e0e1CollectSide};})()`,{console:{log(){}},Map,Date,Promise,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},__e0e1RegisterRuntimeToggle(){}});
 const values={1:100,104:.5,115:.1,117:.4},targetValues={};
 function attrs(values){const group={attributes:new Map(),get:k=>new D(values[k]||0)};return {attributes:group,get:group.get};}
 const hero={uuid:1,name:'我方',getComponent(){return null;},compLife:{max:100},compAttributes:attrs(values),compSkillAssistant:{allSkills:new Map([[20,{cfg:{id:20,type:3,skillFunctionType:4,bookId:100},getActiveSkillCfg(){throw new Error('must not execute skill setup');}}]])}};
 const boss={uuid:2,compBoss:{},getComponent(){return null;},compLife:{current:100,max:100},compAttributes:attrs(targetValues)};
 const enemies=[boss],world={options:{battleData:{type:26}},battleTime:{battleTime:0},sceneEntity:{battleContext:{awakenedEnemies:enemies}},getFightHero:()=>hero};
 Object.defineProperty(world,'random',{get(){throw new Error('sampling must not consume RNG');}});
 let calculations=0;
 class Context{calcDmgRate(){calculations++;assert.notEqual(this.multiplier,hero);this.multiplier.dmgAddRate=new D(1+this.sourceAttr.get(104).toNumber());this.multiplier.elementAddRate=new D(2);this.multiplier.skillTypeAddRate=this.sourceAttr.get(115);this.multiplier.pvpDmgRate=this.sourceAttr.get(117);this.multiplier.finalDmgRate=new D(.2);}}
 class Share{getElementAttrType(){return [];}getElementAttrTypeSpecialSkill(){return [];}getQualityAttrTypeSpecialSkill(){return [];}}
 const cfg={SkillCfg:table([{id:20,name:'测试天书',type:3,skillFunctionType:4,bookId:100}]),SkillBookCfg:table([{id:100,name:'天书',type:0}])};
 api.configure(cfg,{damage:{DamageContext:Context},skill:{SkillContextShareData:Share},decimal:{DecimalNumber:D},hero:{}});
 const state=api.state(world,'self',false);api.sample(state);api.sample(state);
 assert.equal(calculations,1);assert.equal(state.factorSnapshots.length,1);assert.equal(state.factorSnapshots[0].sec,0);assert.equal(state.factorSnapshots[0].factors.coefficient,null);
 assert.equal(state.factorSnapshots[0].factors.damage,1.5);assert.equal(state.factorSnapshots[0].factors.crit,1);
 world.battleTime.battleTime=1;values[104]=.8;api.sample(state);assert.equal(state.factorSnapshots[1].factors.damage,1.8);
 world.battleTime.battleTime=2;enemies.length=0;api.sample(state);assert.equal(state.factorSnapshots.length,2);
 enemies.push(boss);api.sample(state);assert.equal(state.factorSnapshots.length,3);
 const output=api.collect(state);assert.equal(output.factorSnapshots.length,3);assert.equal(output.eventCount,0);assert.equal(output.totalDamage,0);
 console.log('PASS per-second snapshots before first hit, same-second dedupe, live attribute changes, unavailable-target retry, null coefficient, no RNG/skill execution and unchanged damage totals');
})().catch(error=>{console.error(error);process.exitCode=1;});
