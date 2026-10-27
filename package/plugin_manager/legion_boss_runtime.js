// Read the cross-server boss leaderboard and the current character's own roster.
// A missing rank is not proof of non-participation: the server retains a top list.
async function readLegionCrossBoss(g) {
  const chunk=name=>g.System.import('chunks:///_virtual/'+name);
  const [{GET_MODULE}, {ModuleLocalType}, {LegionService,BattlefieldService}, {ROLE}]=await Promise.all([
    chunk('module-manager.ts'),chunk('base-module.ts'),
    chunk('define-index.ts'),chunk('server-data.ts')]);
  const module=GET_MODULE(ModuleLocalType.LEGION);
  const roleId=String(ROLE.id),legionId=String(module.legionId);
  if(!Number.isSafeInteger(Number(legionId)) || Number(legionId)<=0)throw Error('当前角色未加入阴司');
  // Legion Theater is the cross-server battlefield. ActivityService's global
  // world boss is a different event, even though both UIs call the enemy Boss.
  const theater=GET_MODULE(ModuleLocalType.LEGION_THEATER);
  const checkAccount=()=>{
    if(String(ROLE.id)!==roleId || String(module.legionId)!==legionId)
      throw Error('查询期间角色或阴司发生变化，请重新刷新');
  };
  const readReply=(reply,label)=>{
    checkAccount();
    if(!reply || reply.code!==0 || typeof reply.getData!=='function')
      throw Error(label+'：'+String(reply && reply.error || '未返回有效数据')+
        (reply && reply.code!==undefined?'（错误码 '+reply.code+'）':''));
    return reply.getData();
  };
  const field=readReply(await LegionService.getBattlefieldInfo({legionId:Number(legionId)}),'读取本阴司跨服战场失败');
  const fieldInfo=field && field.info;
  const bfId=fieldInfo && fieldInfo.bfId;
  if(typeof bfId!=='string' || !bfId.trim())throw Error('本阴司尚无可查询的跨服战场，请确认已报名及完成匹配');
  const initialBfId=theater && theater.myBfId;
  const check=()=>{
    checkAccount();
    if(theater && theater.myBfId && theater.myBfId!==initialBfId && theater.myBfId!==bfId)
      throw Error('查询期间战场发生变化，请重新刷新');
  };
  const packRank=row=>{
    const id=row && (row.roleId || row.info && row.info.id);
    if(!Number.isSafeInteger(Number(id)) || Number(id)<=0)throw Error('排名接口缺少有效玩家ID');
    if(!Number.isFinite(row.score) || row.score<0 || !Number.isInteger(row.rank) || row.rank<0)
      throw Error('排名接口返回无效排名或伤害');
    return {id:String(id),name:String(row.info && row.info.name || ''),
      sName:String(row.info && row.info.sName || ''),rank:row.rank,score:row.score};
  };
  const ranks=[],seen=new Set();let me=null,stop='limit';
  // Fetch contiguous ranges on demand, without scrolling or opening game UIs.
  for(let start=1;start<=500;){
    check();
    const end=Math.min(start+99,500),requested=end-start+1;
    const reply=await BattlefieldService.getBattlefieldRoleBossDmgRank({bfId,start,end});
    check();
    const data=readReply(reply,'读取跨服战场 Boss 排名失败（战场 '+bfId+'）');
    if(!data || !Array.isArray(data.rankList))throw Error('跨服战场 Boss 排名返回结构异常');
    if(data.me)me=packRank({...data.me,roleId});
    if(!data.rankList.length){stop='end';break;}
    for(const row of data.rankList){
      const packed=packRank(row);
      if(packed.rank<=0 || seen.has(packed.id))throw Error('排名分页重复或无效，请重新刷新');
      seen.add(packed.id);ranks.push(packed);
    }
    start+=data.rankList.length;
    if(ranks.length>500)throw Error('排名接口返回超出请求范围');
    if(data.rankList.length<requested){stop='end';break;}
  }
  check();
  const response=await module.sendGetLegionInfo(Number(legionId));
  check();
  const info=response && (response.legion || response);
  if(!info || String(info.id)!==legionId || !info.members || typeof info.members.forEach!=='function')
    throw Error('无法读取本阴司完整成员列表');
  const members=[],ids=new Set();
  info.members.forEach((m,key)=>{
    const id=String(m.id || key);
    if(!Number.isSafeInteger(Number(id)) || Number(id)<=0 || ids.has(id))throw Error('本阴司成员ID异常');
    ids.add(id);
    members.push({id,name:String(m.name || ''),sName:String(m.sName || ''),
      job:m.job,fightPower:m.fightPower});
  });
  if(!members.length || Number(info.memberNum)>members.length)throw Error('本阴司成员列表不完整，请重新刷新');
  // getMyRoleInfo() can return an empty default when the scene was never opened.
  // Only use an actual role from this battlefield, or the fresh server record.
  const own=theater && typeof theater.getRoleInfo==='function'?theater.getRoleInfo(bfId,Number(roleId)):null;
  const selfDamage=own && String(own.id)===roleId && Number.isFinite(own.bossDmgMax)?own.bossDmgMax:
    Number.isFinite(fieldInfo.bossDmgMax)?fieldInfo.bossDmgMax:null;
  const cfg=await chunk('configs.ts');
  const notes=[];
  async function readOptional(name,params){
    if(typeof BattlefieldService[name]!=='function'){notes.push('当前版本没有接口：'+name);return null;}
    try{
      const reply=await BattlefieldService[name](params);check();
      return readReply(reply,'读取'+name+'失败');
    }catch(e){check();notes.push(String(e.message||e));return null;}
  }
  const contributionReply=await readOptional('getBattlefieldRoleRank',{bfId});
  const contributions=contributionReply && Array.isArray(contributionReply.rankList)?
    contributionReply.rankList.map(packRank):null;
  if(contributionReply && !contributions)notes.push('贡献榜返回结构异常');
  const logs=[];let logTotal=null,logComplete=false,previousPage=null;
  // Native UI uses one-based inclusive log ranges. Preserve identical events:
  // two real attacks can share every field, so content is not an event ID.
  for(let start=1;start<=20000;start+=100){
    const page=await readOptional('getLegionBattleLog',{bfId,start,end:start+99});
    if(!page)break;
    if(!Array.isArray(page.logList)||!Number.isInteger(page.totalCount)||page.totalCount<0){
      notes.push('战场日志返回结构异常');break;
    }
    if(logTotal===null)logTotal=page.totalCount;
    else if(logTotal!==page.totalCount){notes.push('查询期间战场日志数量变化，请刷新后重试');break;}
    const signature=JSON.stringify(page.logList);
    if(page.logList.length && signature===previousPage){notes.push('日志分页重复，结果未标为完整');break;}
    previousPage=signature;
    for(const r of page.logList){
      const monster=cfg.TheaterMonsterCfg.getById(r.monsterId);
      logs.push({roleId:String(r.roleId),monsterId:r.monsterId,roundId:r.roundId,
        targetRoleId:String(r.targetRoleId||0),targetLegionId:String(r.targetLegionId||0),
        isWin:r.isWin,wave:r.wave,point:r.point,timeAt:r.timeAt,
        kind:monster?monster.type===cfg.TheaterMonsterType.EIGHT?'player':
          monster.type===cfg.TheaterMonsterType.NINE?'boss':'monster':'unknown'});
    }
    if(logs.length>=logTotal){logComplete=logs.length===logTotal;break;}
    if(page.logList.length<100){notes.push('日志提前结束，结果未标为完整');break;}
  }
  if(!logComplete)notes.push('日志统计仅覆盖已读取记录，不能把缺失记录视为零次');
  const currentField=theater && typeof theater.getBattleField==='function'?theater.getBattleField(bfId):null;
  const memberBoss={};
  if(currentField && currentField.roles && typeof currentField.roles.forEach==='function')
    currentField.roles.forEach((r,id)=>{
      if(ids.has(String(id)) && Number.isFinite(r.bossDmgMax))
        memberBoss[String(id)]={damage:r.bossDmgMax,count:r.bossBattleCnt};
    });
  // isBossStage is a native calendar/config check and works before scene entry.
  const bossOngoing=!!(typeof theater.isBossStage==='function' && theater.isBossStage());
  let bossRewardRules=[];
  if(bossOngoing){
    const theaterCfg=cfg.TheaterCfg.getById(currentField && currentField.level || info.bfLevel);
    const boss=theaterCfg && cfg.TheaterMonsterCfg.list.find(r=>r.group===theaterCfg.monster &&
      r.type===cfg.TheaterMonsterType.NINE);
    const final=boss && cfg.FinalDayCfg.getById(boss.stageId);
    if(final)bossRewardRules=cfg.RankRewardCfg.list.filter(r=>r.group===final.rankReward).map(r=>({
      from:r.num[0],to:r.num[1],points:r.reward.filter(x=>x.item===10035).reduce((n,x)=>n+x.num,0)}));
    else notes.push('未找到当前战场Boss排名积分配置，预估贡献留空');
  }
  const unknownLogs=logs.filter(r=>r.kind==='unknown').length;
  if(unknownLogs)notes.push(unknownLogs+'条日志的怪物类型配置缺失，未纳入进攻折算');
  check();
  return {roleId,legionId,legionName:String(info.name || ''),bfId,source:'legion-theater',
    bossName:'跨服战场 Boss',members,ranks,me,selfDamage,
    rankLimit:500,stop,contributions,logs,logTotal,logComplete,memberBoss,bossOngoing,
    bossRewardRules,notes,fetchedAt:new Date().toISOString()};
}
