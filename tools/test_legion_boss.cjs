const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname+'/../package/plugin_manager/legion_boss_runtime.js','utf8'),context);
function fixture(size=123){
  const role={id:10},calls=[];
  const roster={id:42,name:'本阴司',memberNum:2,members:new Map([[10,{name:'同名',job:1}],[11,{name:'同名',job:9}]])};
  const module={legionId:42,legionInfo:{sentinel:true},async sendGetLegionInfo(id){assert.equal(id,42);calls.push('roster');return roster;}};
  const theater={myBfId:'bf-old',getRoleInfo:()=>null};
  const service={
    async getBattlefieldInfo(p){assert.equal(p.legionId,42);calls.push('field');return {code:0,getData:()=>({info:{bfId:'bf-current',bossDmgMax:5}})};},
    async getBattlefieldRoleBossDmgRank(p){assert.equal(p.bfId,'bf-current');assert.equal(p.activityId,undefined);calls.push(p);return {code:0,getData:()=>({rankList:Array.from({length:size},(_,i)=>({roleId:1000+i,info:{name:'外服'},rank:i+1,score:1000-i})).slice(p.start-1,p.end),me:{rank:0,score:0}})};}};
  const imports={'module-manager.ts':{GET_MODULE:type=>type===1?module:theater},
    'base-module.ts':{ModuleLocalType:{LEGION:1,LEGION_THEATER:2}},
    'define-index.ts':{LegionService:{getBattlefieldInfo:p=>service.getBattlefieldInfo(p)},
      BattlefieldService:{getBattlefieldRoleBossDmgRank:p=>service.getBattlefieldRoleBossDmgRank(p)},
      ActivityService:{getBossBattleRank(){throw Error('wrong world boss endpoint');}}},'server-data.ts':{ROLE:role},
      'configs.ts':{TheaterMonsterCfg:{getById:id=>({type:id===8?8:id===9?9:1}),list:[]},
        TheaterMonsterType:{EIGHT:8,NINE:9}}};
  return {g:{System:{import:async uri=>{const name=uri.split('/').pop();assert(imports[name],'unexpected module '+name);return imports[name];}}},calls,module,theater,service,role,roster,imports};
}
(async()=>{
  let f=fixture();let out=await context.readLegionCrossBoss(f.g);
  assert.equal(out.ranks.length,123);assert.equal(out.members.length,2);assert.equal(out.me.id,'10');
  assert.equal(out.bfId,'bf-current');assert.equal(out.source,'legion-theater');assert.equal(out.selfDamage,5);
  assert.equal(f.calls.length,4);assert.equal(f.calls[0],'field');assert.equal(f.calls[2].start,101);assert.equal(f.calls[3],'roster');
  assert.equal(f.module.legionInfo.sentinel,true);
  f=fixture(500);out=await context.readLegionCrossBoss(f.g);assert.equal(out.ranks.length,500);assert.equal(out.stop,'limit');assert.equal(f.calls.length,7);
  f=fixture(0);out=await context.readLegionCrossBoss(f.g);assert.equal(out.ranks.length,0);assert.equal(out.members.length,2);
  f=fixture();f.module.legionId=0;await assert.rejects(()=>context.readLegionCrossBoss(f.g),/未加入/);assert.equal(f.calls.length,0);
  f=fixture();f.service.getBattlefieldRoleBossDmgRank=async()=>({code:123,error:'活动未开启'});
  f.imports['define-index.ts'].BattlefieldService.getLegionBattleLog=async()=>({code:0,getData:()=>({
    logList:[{roleId:10,monsterId:1,roundId:1,isWin:false}],totalCount:1})});
  out=await context.readLegionCrossBoss(f.g);
  assert.equal(out.stop,'unavailable');assert.equal(out.logs.length,1);assert.equal(out.logs[0].isWin,false);
  assert(out.notes.some(n=>/战场 bf-current.*活动未开启.*123/.test(n)));
  f=fixture();f.roster.memberNum=3;await assert.rejects(()=>context.readLegionCrossBoss(f.g),/不完整/);
  f=fixture();f.roster.id=43;await assert.rejects(()=>context.readLegionCrossBoss(f.g),/完整成员/);
  f=fixture();const request=f.service.getBattlefieldRoleBossDmgRank;f.service.getBattlefieldRoleBossDmgRank=async p=>{const r=await request(p);f.role.id=20;return r;};
  await assert.rejects(()=>context.readLegionCrossBoss(f.g),/发生变化/);assert.equal(f.calls.length,2);
  f=fixture(200);f.service.getBattlefieldRoleBossDmgRank=async()=>({code:0,getData:()=>({rankList:Array.from({length:100},(_,i)=>({roleId:1000+i,rank:i+1,score:1}))})});
  await assert.rejects(()=>context.readLegionCrossBoss(f.g),/分页重复/);
  f=fixture();f.service.getBattlefieldInfo=async()=>({code:0,getData:()=>({info:{bfId:''}})});await assert.rejects(()=>context.readLegionCrossBoss(f.g),/尚无可查询/);
  f=fixture();f.service.getBattlefieldInfo=async()=>({code:0,getData:()=>({info:{bfId:'bf-current'}})});out=await context.readLegionCrossBoss(f.g);assert.equal(out.selfDamage,null,'unloaded scene must not fabricate zero damage');
  f=fixture();f.theater.getRoleInfo=(bfId,id)=>{assert.equal(bfId,'bf-current');assert.equal(id,10);return {id:10,bossDmgMax:0};};
  out=await context.readLegionCrossBoss(f.g);assert.equal(out.selfDamage,0);
  f=fixture();const read=f.service.getBattlefieldRoleBossDmgRank;f.service.getBattlefieldRoleBossDmgRank=async p=>{const r=await read(p);f.theater.myBfId='bf-next';return r;};
  await assert.rejects(()=>context.readLegionCrossBoss(f.g),/战场发生变化/);
  f=fixture(0);
  f.imports['define-index.ts'].BattlefieldService.getBattlefieldRoleRank=async p=>{
    assert.equal(p.bfId,'bf-current');return {code:0,getData:()=>({rankList:[{roleId:10,rank:1,score:500}]})};};
  const all=Array.from({length:123},(_,i)=>({roleId:10,monsterId:i===0?8:1,roundId:i%2?3:1,
    targetRoleId:20,targetLegionId:99,isWin:false,wave:2,point:4,timeAt:i}));
  const pages=[];
  f.imports['define-index.ts'].BattlefieldService.getLegionBattleLog=async p=>{
    pages.push(p.start);return {code:0,getData:()=>({logList:all.slice(p.start-1,p.end),totalCount:123})};};
  out=await context.readLegionCrossBoss(f.g);
  assert.deepEqual(pages,[1,101]);assert.equal(out.logComplete,true);assert.equal(out.logs.length,123);
  assert.equal(out.logs[0].kind,'player');assert.equal(out.logs[1].kind,'monster');assert.equal(out.contributions[0].score,500);
  f.theater.myBfId='bf-current';f.theater.isBossStage=()=>true;
  f.theater.getBattleField=()=>({level:1,roles:new Map([[11,{bossDmgMax:44,bossBattleCnt:1}]])});
  Object.assign(f.imports['configs.ts'],{TheaterCfg:{getById:()=>({monster:1})},
    TheaterMonsterCfg:{getById:id=>({type:id===8?8:1}),list:[{group:1,type:9,stageId:101}]},
    FinalDayCfg:{getById:()=>({rankReward:14})},RankRewardCfg:{list:[{group:14,num:[1,1],reward:[{item:10035,num:15000}]}]}});
  out=await context.readLegionCrossBoss(f.g);assert.equal(out.bossOngoing,true);
  assert.equal(out.bossRewardRules[0].points,15000);assert.equal(out.memberBoss['11'].count,1);
  f.theater.isBossStage=()=>false;
  out=await context.readLegionCrossBoss(f.g);assert.equal(out.bossOngoing,false);
  assert.equal(out.bossRewardRules[0].points,15000,'Sunday estimate remains available after settlement');
  f.imports['define-index.ts'].BattlefieldService.getLegionBattleLog=async p=>({code:0,getData:()=>({logList:all.slice(0,100),totalCount:123})});
  out=await context.readLegionCrossBoss(f.g);assert.equal(out.logComplete,false);assert.equal(out.logs.length,100);
  f=fixture(0);
  const battles=[{roleId:10,monsterId:1,roundId:1,isWin:false},
    {roleId:11,monsterId:8,roundId:3,isWin:true},{roleId:11,monsterId:1,roundId:3}];
  f.imports['define-index.ts'].BattlefieldService.getLegionBattleLog=async()=>({code:0,getData:()=>({logList:battles,totalCount:3})});
  out=await context.readLegionCrossBoss(f.g);
  assert.equal(out.logComplete,true);assert.equal(out.logResultsComplete,false);
  assert.equal(out.logs[0].isWin,false);assert.equal(out.logs[1].isWin,true);assert.equal(out.logs[2].isWin,null);
  assert(out.notes.some(n=>n.includes('胜负')));
  battles[2].isWin=false;
  out=await context.readLegionCrossBoss(f.g);assert.equal(out.logResultsComplete,true);
  console.log('PASS correct battlefield endpoint, fresh bfId, pagination, cap, empty ranks, own roster, errors, incomplete roster, account/battlefield switch, duplicate pages and unloaded scene');
})().catch(e=>{console.error(e);process.exitCode=1;});
