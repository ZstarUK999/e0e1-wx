// A point-in-time read of the same synchronized state/configs used by native UIs.
// No claims, purchases, upgrades, battles or task completions are dispatched.
async function readFlagUpgrade(g) {
  const chunk=n=>g.System.import('chunks:///_virtual/'+n);
  const [cfg, {ROLE}, {GET_MODULE}, {ModuleLocalType}, defs, {roleHelper},
    {shopHelper}, {seasonBattlePassHelper:bpHelper}, {default:clock}]=await Promise.all([
      chunk('configs.ts'),chunk('server-data.ts'),chunk('module-manager.ts'),
      chunk('base-module.ts'),chunk('define-index.ts'),chunk('role-helper.ts'),
      chunk('shop-helper.ts'),chunk('season-battle-pass-helper.ts'),chunk('date-util.ts')]);
  if(!ROLE || !ROLE.id)throw Error('当前角色尚未就绪');
  const roleId=String(ROLE.id), season=GET_MODULE(ModuleLocalType.SEASON);
  const stage=GET_MODULE(ModuleLocalType.SEASON_STAGE);
  const seasonCfg=cfg.SeasonCfg.getById(ROLE.globalSeason && ROLE.globalSeason.id);
  if(!seasonCfg || !season || !stage || !ROLE.seasonGrowth || !ROLE.tasks)
    throw Error('当前赛季或战旗数据未就绪');
  if(stage.seasonId!==seasonCfg.id)throw Error('深渊与战旗赛季不一致，请进入赛季界面后重试');
  const mapGet=(m,k)=>m && (typeof m.get==='function'?m.get(k):m[k]);
  const plain=x=>JSON.parse(JSON.stringify(x,(_,v)=>v && typeof v.entries==='function' &&
    typeof v.get==='function'?Object.fromEntries(v.entries()):v));
  const list=n=>cfg[n] && cfg[n].list || [];
  const rewards=id=>{
    const row=typeof id==='object'?id:cfg.RewardCfg.getById(id);
    if(!row || row.randomType!=='Fixed')throw Error('缺少固定奖励配置：'+id);
    const result={};
    function visit(x){
      if(!x || typeof x!=='object')return;
      if(x.code!==undefined && x.amount!==undefined){
        if(x.type!==2)throw Error('奖励包含未支持的道具类型：'+id);
        result[x.code]=(result[x.code]||0)+Number(x.amount);return;
      }
      if(typeof x.values==='function')for(const v of x.values())visit(v);
      else for(const v of Object.values(x))visit(v);
    }
    visit(row.content);return result;
  };
  const now=Number(clock.serverTime);
  if(!Number.isFinite(now) || now<=0)throw Error('未读到游戏服务器时间');
  const dayMs=86400000;
  const stages=[];
  for(const area of stage.getSeasonStageAreaList())for(const row of area.seasonStageInfoList){
    stages.push({id:row.cfg.id,areaId:area.cfg.id,area:area.cfg.name,sort:row.cfg.sort,
      star:row.star,unlockAt:seasonCfg.startTime+(area.cfg.unlockDay||0)*dayMs,
      rewards:row.seasonStageLevelInfoList.map(l=>{
        const point=l.cfg;
        if(!point || !point.onceStageRewardId)throw Error('缺少深渊首通配置：'+l.stagePointId);
        return rewards(point.onceStageRewardId);
      })});
  }
  const activityId=season.getCurrentSeasonBattlePassId();
  const activity=cfg.ActivityCfg.getById(activityId);
  const bp=bpHelper.getBattlePassInfo(activityId);
  if(!activity || !bp)throw Error('血月战令尚未解锁或数据未同步');
  const taskIds=[...new Set((activity.param||[]).flat())];
  for(let i=0;i<taskIds.length;i++){
    const next=cfg.TaskCfg.getById(taskIds[i])?.afterTask;
    if(next && !taskIds.includes(next))taskIds.push(next);
  }
  const finished=new Set(ROLE.tasks.finishTasks||[]);
  const tasks=taskIds.map(id=>{
    const c=cfg.TaskCfg.getById(id), working=mapGet(ROLE.tasks.workingTask,id);
    if(!c)throw Error('缺少战令任务配置：'+id);
    const condition=cfg.ConditionCfg.getById(c.c_item_Condition || c.Condition && c.Condition.id);
    if(!condition)throw Error('缺少任务条件配置：'+id);
    const names={SeasonStageSweep:'sweeps',WarRestraintLevelUp:'dailyUpgrade',
      WarRestraintLevelUpAcc:'flagLevel',SeasonStageComplete:'stars',ActivityXueYueJoin:'battles',
      ActivityXueYueRun:'march',ActivityXueYueRebirth:'revive',ActivityXueYueNum:'points',
      ActivityXueYueItemRebirth:'reviveItem',RechargeAcc:'recharge',Recharge:'recharge'};
    const metric=names[cfg.ConditionType[condition.type]] || 'other';
    return {id,name:c.taskDesc,kind:c.taskType===4?'daily':c.taskType===22?'weekly':'season',metric,
      condition:condition.type,target:c.TargetNum1,score:c.score,
      state:finished.has(id)?2:working?working.state:0,
      progress:working && working.condition && working.condition.progress || 0};
  });
  function shop(row){
    if(!row)return null;
    return {id:row.id,name:row.name,limit:row.limit,bought:shopHelper.getMallBuyTimes(row),
      refresh:row.refresh,rewards:rewards(row.reward || row.c_item_reward),consume:plain(row.consume),
      price:row.rechargeId && cfg.RechargeConfig.getById(row.rechargeId)?.amount || 0,
      unlockAt:seasonCfg.startTime+Math.max(0,Number(mapGet(row.conditions,'seasonOpenDay')||1)-1)*dayMs};
  }
  const goods=list('MallConfig');
  const exchange=goods.find(r=>r.shopType===seasonCfg.redeemShopId && r.name==='展旗木');
  const gift=goods.find(r=>r.shopType===seasonCfg.shopId && r.name==='战旗材料礼包');
  const battles=[];
  for(const b of list('SeasonBattleTimeCfg').filter(r=>r.group===seasonCfg.battleGroup)){
    if(b.battleType===cfg.SeasonBattleFieldType.MINHE)continue;
    const times=season.getSeasonBattleStageTimeList(b.id);
    const battle=times.find(t=>t.stage===defs.ESeasonBTimeStage.battle);
    if(battle && battle.startTime>=seasonCfg.startTime && battle.startTime<=seasonCfg.endTime)
      battles.push(battle.startTime);
  }
  const resources={};
  for(const id of [10003,10004,10055,10079,10080,10081])resources[id]=roleHelper.getItemCount(id);
  const levels=list('SeasonWarRestraintLevelUpCfg').filter(r=>r.seasonId===seasonCfg.id);
  if(!levels.length || !stages.length)throw Error('本赛季战旗或深渊配置为空');
  if(roleId!==String(ROLE.id))throw Error('读取期间角色发生变化，请重新拉取');
  return plain({roleId,name:ROLE.name||'',asOf:now,season:{id:seasonCfg.id,name:seasonCfg.name,
    start:seasonCfg.startTime,end:seasonCfg.endTime,shopEnd:seasonCfg.shopEndTime},
    flagLevel:ROLE.seasonGrowth.flagLevel,resources,stages,
    todaySweeps:stage.gdSeasonStage.sweepFree+stage.gdSeasonStage.sweepBuy,
    tickets:stage.gdSeasonStage.ticket,
    challenge:cfg.SeasonConstantCfg.config.SeasonStageChallenge,
    freeSweeps:cfg.SeasonConstantCfg.config.SeasonStageSweep,
    paidSweepCosts:cfg.SeasonConstantCfg.config.SeasonStageSweepCost,
    sweeps:list('SeasonStageSweepCfg').filter(r=>r.group===seasonCfg.id).map(r=>({stars:r.needStar,
      rewards:Object.fromEntries(r.rewardShow.map(x=>String(x).split('_')).filter(x=>Number(x[2])===0)
        .map(x=>[x[0],Number(x[1])]))})),
    levels:levels.map(r=>({level:r.level,cost:r.cost,attrs:r.attr})),
    flags:list('SeasonWarRestraintCfg').filter(r=>r.seasonId===seasonCfg.id).map(r=>({id:r.id,name:r.name,
      unlockLevel:r.unlockLevel,nodeDesc:r.nodeDesc,nodeTitle:r.nodeTital,
      skillLevel:mapGet(ROLE.seasonGrowth.flagSkillLv,r.id)||0,costNum:r.costNum,costItem:r.costItem})),
    attributes:list('SeasonAttrCfg').map(r=>({id:r.id,name:r.note,style:r.style})),
    bp:{id:activityId,level:bp.level,exp:bp.exp,
      active:[true,bpHelper.isMidActive(activityId),bpHelper.isBestActive(activityId)],
      claimed:[bp.normalRewardState,bp.activeRewardState,bp.bestActiveRewardState],
      levels:list('BattlePassLevelCfg').filter(r=>r.activityID===activityId).map(r=>({level:r.level,
        exp:r.exp,rewards:[r.reward,r.payReward,r.payRewardBest]}))},
    tasks,exchange:shop(exchange),gift:shop(gift),battles:[...new Set(battles)].sort((a,b)=>a-b)});
}
