// Historical reads use the same LegionService methods as the game rank/report UIs.
async function seasonInsight(g, op, args) {
  args=args||{};
  const chunk=n=>g.System.import('chunks:///_virtual/'+n);
  const defs=await chunk('define-index.ts'), configs=await chunk('configs.ts');
  const manager=await chunk('service-manager.ts');
  const m=g.seasonModule || (await chunk('module-manager.ts')).GET_MODULE((await chunk('base-module.ts')).ModuleLocalType.SEASON);
  const isMap=x=>x && typeof x.get==='function' && typeof x.entries==='function';
  const plain=x=>JSON.parse(JSON.stringify(x,(k,v)=>isMap(v)?Object.fromEntries(v.entries()):v));
  const entries=x=>isMap(x)?[...x.entries()]:Object.entries(x||{});
  const state=g.__e0e1SeasonInsight || (g.__e0e1SeasonInsight={wars:new Map(),reports:new Map(),replay:null});
  const legionId=Number(g.ROLE.legion && g.ROLE.legion.legionId)||0;
  const account=String(g.ROLE.id)+':'+String(legionId);
  if(state.account!==account){state.account=account;state.wars.clear();state.reports.clear();}
  async function request(name,params){
    if(typeof defs.LegionService[name]!=='function')throw Error('游戏接口不可用：'+name);
    const r=await manager.SERVICE(defs.LegionService[name],params,false);
    if(String(g.ROLE.id)+':'+String(Number(g.ROLE.legion && g.ROLE.legion.legionId)||0)!==account)
      throw Error('查询期间角色或阴司发生变化，请重新刷新战场列表');
    if(!r || r.err)throw Error(r && r.err && r.err.error || '读取血月数据失败：'+name);
    return r.resp;
  }
  function battlefield(args){
    const war=state.wars.get(String(args.warId));
    if(!war)throw Error('请先刷新本阴司战场列表');
    return war;
  }
  if(op==='history'){
    if(!legionId)throw Error('当前角色未加入阴司');
    const response=await request('getLegionSeasonInfo',{}), season=response.legionSeason;
    const rows=new Map();
    function add(bTimeId,info,seasonId){
      if(!info || !info.warId || info.legionId && Number(info.legionId)!==legionId)return;
      const cfg=configs.SeasonBattleTimeCfg.getById(Number(bTimeId));
      if(!cfg)return;
      // MINHE is the separate Styx team battlefield.
      if(defs.SeasonBattleFieldType && cfg.battleType===defs.SeasonBattleFieldType.MINHE)return;
      const timeCfg=configs.SeasonTimeCfg && configs.SeasonTimeCfg.getByBattleType(cfg.battleType);
      const row={warId:String(info.warId),bTimeId:Number(bTimeId),seasonId:Number(seasonId)||0,
        name:timeCfg && (timeCfg.battleTypeName || timeCfg.name) || cfg.name || '血月战场 '+bTimeId,
        week:cfg.startWeekDay,weekDay:cfg.weekDay,rank:info.rank,score:info.score,
        signUpTime:info.signUpTime,legionId:legionId};
      rows.set(row.warId,row);state.wars.set(row.warId,row);
    }
    for(const [id,info] of entries(g.ROLE.season && g.ROLE.season.hisWarMap))
      add(id,info,g.ROLE.season.seasonId);
    for(const [id,info] of entries(season && season.bTimeInfos))add(id,info,season.seasonId);
    return plain({account,legionId,rows:[...rows.values()].sort((a,b)=>b.bTimeId-a.bTimeId),
      note:'游戏当前保留的本阴司战场记录；已查询的排名和战报另存本地快照。'});
  }
  if(op==='legion_roster'){
    battlefield(args);
    const id=Number(args.legionId);
    if(!Number.isSafeInteger(id)||id<=0)throw Error('阴司ID无效');
    const response=await request('getLegionPreview',{legionId:id});
    const info=response && response.legion;
    if(!info || Number(info.id)!==id)throw Error('阴司预览返回ID不匹配');
    return plain({legionId:String(id),memberNum:info.memberNum,members:entries(info.members).map(([key,m])=>({
      id:String(m.id||key),name:m.name,sName:m.sName,legionId:id,legionName:info.name,
      fightPower:m.fightPower,membershipSource:'当前阴司预览'}))});
  }
  if(op==='statistics'){
    const war=battlefield(args);
    async function verify(){
      const latest=await request('getLegionSeasonInfo',{});
      const info=entries(latest.legionSeason && latest.legionSeason.bTimeInfos).find(([id])=>Number(id)===war.bTimeId);
      if(!info || String(info[1].warId)!==war.warId)
        throw Error('该战场已不在服务端当前战绩记录中，无法拉取统计');
    }
    await verify();
    const result=await request('getSeasonBfRoleResult',{bTimeId:war.bTimeId});
    await verify();
    if(!result || !Array.isArray(result.result))throw Error('血月战绩返回结构异常');
    const seen=new Set();
    const rows=result.result.map(row=>{
      const preview=row.rolePreview || {},id=Number(preview.id || row.id);
      if(!Number.isSafeInteger(id)||id<=0||seen.has(id))throw Error('血月战绩成员ID重复或无效');
      seen.add(id);
      const out={id:String(id),name:String(preview.name || row.name || ''),
        sName:String(preview.sName || row.sName || '' )};
      for(const key of ['killRoleNum','killGuardNum','score','dieNum']){
        const value=row[key];
        if(value===undefined || value===null){out[key]=null;continue;}
        if(!Number.isFinite(value)||value<0 || key!=='score'&&!Number.isInteger(value))
          throw Error('血月战绩字段无效：'+key);
        out[key]=value;
      }
      return out;
    });
    rows.sort((a,b)=>(b.score===null?-1:b.score)-(a.score===null?-1:a.score)||Number(a.id)-Number(b.id));
    return plain({account,legionId,warId:war.warId,bTimeId:war.bTimeId,name:war.name,
      rows,fetchedAt:new Date().toISOString(),note:'所选战场本阴司战绩名单；攻城次数对应游戏 killGuardNum，死亡次数直接使用服务端 dieNum，缺失字段显示 —。'});
  }
  if(op==='ranks'){
    const war=battlefield(args);
    // bTimeId endpoints are scoped by the server to the legion's current
    // retained record. Verify warId before using them for a historical row.
    const latest=await request('getLegionSeasonInfo',{});
    const info=entries(latest.legionSeason && latest.legionSeason.bTimeInfos).find(([id])=>Number(id)===war.bTimeId);
    if(!info || String(info[1].warId)!==war.warId)throw Error('该战场已不在服务端当前排名记录中，可查看本地快照');
    const legions=await request('getSeasonBfLegionRank',{bTimeId:war.bTimeId});
    const roles=await request('getSeasonBfRoleRank',{bTimeId:war.bTimeId});
    const scorePer=configs.SeasonConstantCfg && configs.SeasonConstantCfg.config && configs.SeasonConstantCfg.config.ScorePer;
    const scoreRule=Array.isArray(scorePer) && scorePer.length===3 && scorePer.every(n=>Number.isFinite(n)&&n>=0)?scorePer:undefined;
    return plain({warId:war.warId,legions:legions.rank||[],roles:roles.rank||[],scoreRule});
  }
  if(op==='guard_count'){
    const war=battlefield(args),roleId=Number(args.roleId);
    if(!Number.isSafeInteger(roleId)||roleId<=0)throw Error('玩家ID无效');
    // Use the game's bounded first page; end=0 can mean "all records".
    const result=await request('getSeasonBattleReportDetail',{warId:war.warId,roleId,start:0,end:14,
      filter:defs.EMSeasonBattleReportType.guard});
    if(!result || !Number.isSafeInteger(result.total)||result.total<0)throw Error('攻城战报未返回有效总次数');
    return {warId:war.warId,roleId,total:result.total};
  }
  if(op==='reports'){
    const war=battlefield(args),roleId=Number(args.roleId),start=Number(args.start)||0;
    if(!Number.isSafeInteger(roleId)||roleId<=0||!Number.isSafeInteger(start)||start<0)throw Error('玩家或分页参数无效');
    const reportFilter=args.reportFilter || 'all';
    if(!['all','players'].includes(reportFilter))throw Error('战报筛选参数无效');
    const result=await request('getSeasonBattleReportDetail',{warId:war.warId,roleId,start,end:start+14,
      filter:reportFilter==='players'?defs.EMSeasonBattleReportType.role:defs.EMSeasonBattleReportType.all});
    const reports=result.battleReports||[];
    for(const report of reports)state.reports.set(war.warId+':'+roleId+':'+report.battleId,report);
    return plain({rows:reports.map(report=>{
      const building=configs.SeasonBuildingCfg.getById(report.buildingId);
      return {...report,place:building && building.buildingName || String(report.buildingId||'—')};
    }),total:result.total||0});
  }
  if(op==='replay'){
    battlefield(args);
    const ui=g.UIManager && g.UIManager.ins;
    if(ui && Object.values(ui.viewParams||{}).some(v=>(v.showing||v.loading) && v.ui &&
        (v.ui.battleWorld || v.ui.battleWorldOther)))throw Error('当前正在战斗，请结束后再播放战报');
    if(state.replay && state.replay.status==='opening')throw Error('上一条回放请求仍在处理');
    const report=state.reports.get(String(args.warId)+':'+Number(args.roleId)+':'+args.battleId) || args.report;
    if(!report || !report.battleId || String(report.battleId)!==String(args.battleId) ||
      ![report.roleInfo && report.roleInfo.roleId,report.tarRoleInfo && report.tarRoleInfo.roleId].some(id=>String(id)===String(args.roleId)))
      throw Error('请重新读取该玩家战报后再播放');
    if((report.roleInfo && report.roleInfo.roleId<100000) || (report.tarRoleInfo && report.tarRoleInfo.roleId<100000))
      throw Error('守卫战报不支持PVP回放');
    const token=String(Date.now())+':'+String(report.battleId);
    const replay={token,battleId:report.battleId,status:'opening',error:''};state.replay=replay;
    // Native replay can outlive an RPC timeout; dispatch once and observe it.
    Promise.resolve().then(()=>m.replaySeasonBattleReport(report,Number(args.roleId))).then(
      ()=>{replay.status='returned';},e=>{replay.status='failed';replay.error=String(e && e.message || e);});
    return {token,battleId:report.battleId};
  }
  if(op==='replay_status')return state.replay?plain(state.replay):null;
  throw Error('未知血月数据操作：'+op);
}
