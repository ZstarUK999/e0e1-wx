// Uses the game's actual synchronous fast-forward function; no game/network actions.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const game=fs.readFileSync(path.join(root,'output/wx6d5e82c174635a48/65/subpackages/game/game.js'),'utf8');
const match=game.match(/n\.skipBattleLocalFastForward = (function\(\) \{[\s\S]*?)\}, n\.configureSkipLogicClock/);assert(match,'native friend fast-forward function');
const source=fs.readFileSync(path.join(root,'tools/js/damage_curve_probe.js'),'utf8');
class Signal{constructor(){this.handlers=[];}add(fn){this.handlers.push(fn);}remove(fn){this.handlers=this.handlers.filter(v=>v!==fn);}dispatch(...args){this.handlers.slice().forEach(fn=>fn(...args));}}
(async()=>{
 const recording=process.argv.includes('--record-only');
 let intervals=0,loops=0,controller;
 const table=rows=>({list:rows,getById:id=>rows.find(row=>row.id===Number(id))});
 const cfg={SkillCfg:table([{id:10,name:'主角普攻',type:1,skillFunctionType:1},{id:20,name:'测试天书',type:3,skillFunctionType:4,bookId:100}]),SkillBookCfg:table([{id:100,name:'测试天书',type:0}])};
 const helper={subLife(ctx){const w=ctx.battleWorld;w.damage+=ctx.damage;w.options.mineInfo.score+=ctx.damage;w.battleSignal.$skillDamageCollect.dispatch(ctx.source,ctx.skillId,ctx.damage,ctx.target,false);return ctx.damage;}};
 const manager={timestamp:0,battles:[],getBattles(){return this.battles;},detachBattleWorlds(worlds){this.battles=this.battles.filter(w=>!worlds.includes(w));}};
 const native=new Function('w','T','p','return ('+match[1]+'});')({TICK_INTERVAL:.125},{ins:manager},{debug(){}});
 class Controller{constructor(){this.fightIng=true;this._pvpCfg={PVPLimitTime:3};}configureSkipLogicClock(w){w.battleTime.isSkipping=true;}disableBattleViewSystems(){}skipBattleLocalFastForward(){return native.call(this);}}
 const original=Controller.prototype.skipBattleLocalFastForward;
 const api=await vm.runInNewContext('(async()=>{'+source+`;return {setup(raw){E0E1_RECORD_ONLY=raw;E0E1_CFG=cfg;E0E1_CHARACTER={characterHelper:helper};E0E1_BM={BattleManager:{ins:manager}};E0E1_LOCAL_DUAL={DualScorePvpBattleManager:Controller};},patch:e0e1PatchBattleManager,collect:damageCurveJson,stop:damageCurveStop,attach:e0e1AttachAll};})()`,{cfg,helper,manager,Controller,Map,Date,Promise,setTimeout,clearTimeout,setInterval(){intervals++;return 1;},clearInterval(){},console:{log(){}},__e0e1RegisterRuntimeToggle(){}});
 api.setup(recording);api.patch();
 function world(self,id){
  const attributes={attributes:new Map(),get:key=>key===1?100:0},hero={uuid:id,compAttributes:{attributes,get:attributes.get},compLife:{current:100,max:100}},target={uuid:id+10,compBoss:{},compAttributes:{attributes,get:attributes.get},compLife:{current:10000,max:10000}};
  const w={instanceId:id,options:{battleData:{type:26,randomSeed:1},mineInfo:{isSelf:self,score:1000}},battleTime:{battleTime:0},timeManager:{},damage:0,count:0,statistics:{get(){return w.damage;}},getFightHero:()=>hero,battleSignal:{$skillDamageCollect:new Signal(),timeBattleTickSignal:new Signal()},update(timestamp){
    loops++;this.count++;this.battleTime.battleTime=timestamp/1000;this.battleSignal.timeBattleTickSignal.dispatch();
    const damage=this.count%2?10:20;
    helper.subLife({battleWorld:this,source:hero,target,skillId:this.count%2?10:20,damage,atk:100,sourceAttr:attributes,targetAttr:attributes,multiplier:{baseCoeff:1,dmgAddRate:1,elementAddRate:1,dmgTypeRate:0,hpDmgAddRate:0,skillTypeAddRate:0,attackDmgRate:0,pvpDmgRate:0,finalDmgRate:0},skillContext:{shareData:{},effectParams:{}}});
    if(self && this.count===20)controller.fightIng=false;
  }};return w;
 }
 controller=new Controller();controller.selfBattleWorld=world(true,1);controller.otherBattleWorld=world(false,2);manager.battles=[controller.selfBattleWorld,controller.otherBattleWorld];
 // No polling can run inside this call; the skip hook must attach before native detach.
 assert.equal(controller.skipBattleLocalFastForward(),undefined);
 const data=api.collect();assert.equal(intervals,0);assert.equal(loops,40);assert.equal(manager.battles.length,0);
 assert.equal(data.self.initialAttributes.attributes[1],100);assert.equal(data.other.initialAttributes.attributes[1],100);
 assert.equal(data.self.initialAttributes.time,0);assert.equal(data.other.initialAttributes.time,0);
 assert.equal(data.self.eventCount,20);assert.equal(data.other.eventCount,20);
 for(const side of [data.self,data.other])assert.equal(recording ? side.events.reduce((n,row)=>n+row.dmg,0) : side.totalDamage,300);
 assert.equal(data.self.events.at(-1).t,2.5);assert.equal(data.pvp.skipped,true);
 assert.deepEqual(Array.from(data.pvp.samples,row=>row.sec),[0,1,2]);assert.equal(data.pvp.samples.at(-1).selfBoss,300);assert.equal(data.pvp.samples.at(-1).otherBoss,300);
 assert.equal(data.pvp.samples.at(-1).selfScore,1300);assert.equal(data.pvp.samples.at(-1).t,2.5);
 for(const side of [data.self,data.other])assert.equal(recording ? side.hits.length : side.factorRows.reduce((n,row)=>n+row.hits,0),20);
 assert.equal(new Set(data.pvp.samples.map(row=>row.sec)).size,data.pvp.samples.length);
 api.stop();assert.equal(Controller.prototype.skipBattleLocalFastForward,original);
 if(process.argv.includes('--json'))process.stdout.write(JSON.stringify(data));
 else console.log('PASS actual native friend skip captures both full event streams, normal/book factor hits, every game second and final-frame scores without timers, duplicate seconds or altered native steps'+(recording ? ' (recording-only)' : ''));
})().catch(e=>{console.error(e);process.exitCode=1;});
