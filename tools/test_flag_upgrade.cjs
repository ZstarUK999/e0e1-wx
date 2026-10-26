const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('package/plugin_manager/flag_upgrade_runtime.js','utf8');

function fixture(){
  const fixed=(id,code,amount)=>({id,randomType:'Fixed',content:[new Map([['', [{type:2,code,amount}] ]])]});
  const rewards=new Map([[1,fixed(1,10080,10)],[2,fixed(2,10080,20)],[3,fixed(3,10080,30)]]);
  const byList=list=>({list,getById:id=>list.find(r=>r.id===id)});
  const start=Date.parse('2026-09-29T00:00:00+08:00');
  const seasonCfg={id:3,name:'第三赛季',startTime:start,endTime:Date.parse('2026-12-06T23:59:59+08:00'),
    specialId:6066,shopId:5002,redeemShopId:5102,battleGroup:2};
  const stageRows=[{cfg:{id:81101,sort:1},star:2,seasonStageLevelInfoList:[1,2,3].map(n=>({
    stagePointId:n,cfg:{onceStageRewardId:n}}))}];
  const stage={seasonId:3,gdSeasonStage:{sweepFree:3,sweepBuy:3},getSeasonStageAreaList(){
    return [{cfg:{id:8101,name:'入山',unlockDay:0},seasonStageInfoList:stageRows}];}};
  const season={getCurrentSeasonBattlePassId:()=>6066,getSeasonBattleStageTimeList:()=>[
    {stage:2,startTime:Date.parse('2026-10-31T20:00:00+08:00')} ]};
  const bp={level:59,exp:10,normalRewardState:59,activeRewardState:59,bestActiveRewardState:59};
  const role={id:123456,name:'测试',globalSeason:{id:3},seasonGrowth:{flagLevel:99,flagSkillLv:new Map([[1,5]])},
    tasks:{workingTask:new Map([[1200001,{state:1,condition:{progress:3}}]]),finishTasks:[1200002]}};
  const cfg={SeasonCfg:byList([seasonCfg]),RewardCfg:{getById:id=>rewards.get(id)},
    SeasonConstantCfg:{config:{SeasonStageSweep:3,SeasonStageSweepCost:[200,400,600]}},
    ActivityCfg:byList([{id:6066,param:[[1200001,1200002],[]]}]),
    TaskCfg:byList([{id:1200001,taskDesc:'每日扫荡',taskType:4,TargetNum1:3,score:30,Condition:{id:81}},
      {id:1200002,taskDesc:'每日升级',taskType:4,TargetNum1:1,score:30,Condition:{id:82}}]),
    ConditionCfg:byList([{id:81,type:77},{id:82,type:78}]),
    ConditionType:{77:'SeasonStageSweep',78:'WarRestraintLevelUp'},
    MallConfig:byList([{id:500409,name:'展旗木',shopType:5102,limit:10,refresh:2,
      reward:fixed(4,10080,20),consume:[10055,600],conditions:new Map()},
      {id:500305,name:'战旗材料礼包',shopType:5002,limit:2,refresh:2,consume:[],
       reward:fixed(5,10080,80),rechargeId:'product_128',conditions:new Map([['seasonOpenDay',8]])}]),
    RechargeConfig:byList([{id:'product_128',amount:12800}]),
    SeasonBattleTimeCfg:byList([{id:21,group:2,battleType:1}]),SeasonBattleFieldType:{MINHE:9},
    SeasonWarRestraintLevelUpCfg:byList([{level:99,seasonId:3,cost:[],attr:[new Map([[200101,9900]])]}]),
    SeasonStageSweepCfg:byList([{id:29,group:3,needStar:84,rewardShow:['10080_6_0','202109_1_7']}]),
    SeasonWarRestraintCfg:byList([{id:1,seasonId:3,name:'火魂幡',unlockLevel:[0,10],nodeDesc:['a','b'],nodeTital:['战场','赛季'],costNum:[0,3],costItem:10081}]),
    SeasonAttrCfg:byList([{id:200101,note:'深渊攻击力',style:0}]),
    BattlePassLevelCfg:byList([{activityID:6066,level:59,exp:150,reward:[],payReward:[{item:10080,num:35}],payRewardBest:[{item:10080,num:70}]}])};
  const modules={'configs.ts':cfg,'server-data.ts':{ROLE:role},
    'module-manager.ts':{GET_MODULE:key=>key===1?season:stage},'base-module.ts':{ModuleLocalType:{SEASON:1,SEASON_STAGE:2}},
    'define-index.ts':{ESeasonBTimeStage:{battle:2}},'role-helper.ts':{roleHelper:{getItemCount:id=>id===10080?301:1000}},
    'shop-helper.ts':{shopHelper:{getMallBuyTimes:row=>row.id===500409?5:1}},
    'season-battle-pass-helper.ts':{seasonBattlePassHelper:{getBattlePassInfo:()=>bp,isMidActive:()=>true,isBestActive:()=>true}},
    'date-util.ts':{default:{serverTime:Date.parse('2026-10-26T23:30:00+08:00')}}};
  const g={System:{import:async n=>{const name=n.replace('chunks:///_virtual/','');assert.ok(name in modules,name);return modules[name];}}};
  const context={Map,Set,Date,Promise,console};vm.createContext(context);vm.runInContext(source,context);
  return {read:()=>context.readFlagUpgrade(g),role,cfg,stageRows,season,modules};
}

(async()=>{
  const f=fixture();const data=await f.read();
  assert.equal(data.roleId,'123456');assert.equal(data.flagLevel,99);assert.equal(data.resources[10080],301);
  assert.equal(data.stages[0].star,2);assert.equal(data.stages[0].rewards[2][10080],30);
  assert.equal(data.exchange.bought,5);assert.equal(data.gift.bought,1);assert.equal(data.gift.price,12800);
  assert.equal(data.gift.rewards[10080],80);assert.equal(data.gift.unlockAt,Date.parse('2026-10-06T00:00:00+08:00'));
  assert.deepEqual(Array.from(data.bp.active),[true,true,true]);assert.equal(data.bp.level,59);
  assert.equal(data.todaySweeps,6);assert.equal(data.tasks[0].metric,'sweeps');assert.equal(data.tasks[0].state,1);
  assert.equal(data.tasks[1].metric,'dailyUpgrade');assert.equal(data.tasks[1].state,2);
  assert.equal(data.flags[0].skillLevel,5);assert.equal(data.sweeps[0].rewards[10080],6);
  assert.equal(data.sweeps[0].rewards[202109],undefined); // probability display is not a guaranteed reward
  assert.deepEqual(JSON.parse(JSON.stringify(data.levels[0].attrs)),[{'200101':9900}]);
  f.stageRows[0].seasonStageLevelInfoList[0].cfg.onceStageRewardId=999;
  await assert.rejects(f.read(),/缺少固定奖励/);
  const missing=fixture();missing.modules['season-battle-pass-helper.ts'].seasonBattlePassHelper.getBattlePassInfo=()=>null;
  await assert.rejects(missing.read(),/战令尚未解锁/);
  const switched=fixture();switched.modules['role-helper.ts'].roleHelper.getItemCount=()=>{switched.role.id++;return 0;};
  await assert.rejects(switched.read(),/角色发生变化/);
  const mismatch=fixture();mismatch.modules['module-manager.ts'].GET_MODULE=key=>key===1?mismatch.season:{seasonId:2};
  await assert.rejects(mismatch.read(),/赛季不一致/);
  console.log('PASS flag snapshot: linked configs, Map rewards/tasks, pass tracks, shops, Beijing clock, identity and missing data');
})().catch(e=>{console.error(e);process.exitCode=1;});
