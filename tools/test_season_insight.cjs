const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('package/plugin_manager/season_insight_runtime.js','utf8');
function fixture(){
  const calls=[],replays=[];
  const own={warId:'war-a',rank:2,score:200};
  const season={seasonId:10,bTimeInfos:new Map([[101,own]])};
  const role={id:100001,legion:{legionId:42},season:{seasonId:10,hisWarMap:new Map([
    [101,{warId:'war-a',legionId:42}],[99,{warId:'old-own',legionId:42}],
    [98,{warId:'foreign',legionId:99}],[102,{warId:'styx',legionId:42}]])}};
  const report={battleId:8001,roleInfo:{roleId:100001,energy:80},tarRoleInfo:{roleId:100002,energy:60},
    rolePreview:{id:100001,name:'甲',fightPower:123456789},tarRolePreview:{id:100002,name:'乙',fightPower:90000000},
    time:1792840000000,buildingId:7,winRoleId:100002,statistic:new Map([[1,200]])};
  const replies={getLegionSeasonInfo:{legionSeason:season},getSeasonBfLegionRank:{rank:[{id:42,name:'本阴司',rank:2}]},
    getSeasonBfRoleRank:{rank:[{id:100001,name:'甲',rank:1}]},getSeasonBattleReportDetail:{battleReports:[report],total:1},
    getLegionPreview:{legion:{id:99,memberNum:56,members:new Map([[100002,{name:'其他阴司成员'}]])}},
    getSeasonBfRoleResult:{result:[{id:100001,rolePreview:{id:100001,name:'甲'},score:20,killRoleNum:3,killGuardNum:4,dieNum:2},
      {id:100002,name:'乙',score:100,killRoleNum:0,killGuardNum:10,dieNum:0}]}};
  const service=Object.fromEntries(Object.keys(replies).map(k=>[k,function(){}]));
  const module={async replaySeasonBattleReport(...args){replays.push(args);if(module.fail)throw Error('expired');}};
  const defs={LegionService:service,EMSeasonBattleReportType:{all:0,role:1,guard:2},SeasonBattleFieldType:{MINHE:9}};
  const mods={'define-index.ts':defs,'configs.ts':{SeasonBattleTimeCfg:{getById:id=>({name:'战场'+id,battleType:id===102?9:1})},
    SeasonConstantCfg:{config:{ScorePer:[10,1,1]}},
    SeasonBuildingCfg:{getById:()=>({buildingName:'黄泉城'})}},
    'service-manager.ts':{async SERVICE(fn,args){const name=Object.keys(service).find(k=>service[k]===fn);calls.push({name,args});return {err:null,resp:replies[name]};}}};
  const context={Map,Set,Date,Promise};vm.createContext(context);vm.runInContext(source,context);
  const g={ROLE:role,seasonModule:module,System:{import:async n=>mods[n.replace('chunks:///_virtual/','')]}};
  return {g,own,season,role,report,calls,replays,module,replies,call:(op,args)=>context.seasonInsight(g,op,args)};
}
(async()=>{
  const f=fixture();const history=await f.call('history');
  assert.deepEqual(Array.from(history.rows,r=>r.warId),['war-a','old-own']);
  assert.equal(history.account,'100001:42');
  const roster=await f.call('legion_roster',{warId:'war-a',legionId:99});
  assert.equal(roster.memberNum,56);assert.equal(roster.members.length,1);assert.equal(roster.members[0].id,'100002');
  await assert.rejects(f.call('legion_roster',{warId:'war-a',legionId:98}),/ID不匹配/);
  const ranks=await f.call('ranks',{warId:'war-a'});assert.equal(ranks.roles[0].name,'甲');
  assert.deepEqual(Array.from(ranks.scoreRule),[10,1,1]);
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls.at(-1))),{name:'getSeasonBfRoleRank',args:{bTimeId:101}});
  await assert.rejects(f.call('ranks',{warId:'old-own'}),/当前排名/);
  const stats=await f.call('statistics',{warId:'war-a'});
  assert.equal(stats.rows[0].id,'100002');assert.equal(stats.rows[1].dieNum,2);
  assert.equal(stats.rows[1].killGuardNum,4);assert.equal(stats.warId,'war-a');
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls.find(x=>x.name==='getSeasonBfRoleResult').args)),{bTimeId:101});
  await assert.rejects(f.call('statistics',{warId:'old-own'}),/当前战绩/);
  delete f.replies.getSeasonBfRoleResult.result[0].dieNum;
  assert.equal((await f.call('statistics',{warId:'war-a'})).rows[1].dieNum,null);
  f.replies.getSeasonBfRoleResult.result[0].dieNum=-1;
  await assert.rejects(f.call('statistics',{warId:'war-a'}),/字段无效/);
  f.replies.getSeasonBfRoleResult.result[0].dieNum=2;
  await assert.rejects(f.call('reports',{warId:'foreign',roleId:100001}),/本阴司/);
  const reports=await f.call('reports',{warId:'war-a',roleId:100001,start:50});
  assert.equal(reports.rows[0].place,'黄泉城');assert.equal(reports.rows[0].roleInfo.energy,80);
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls.at(-1).args)),{warId:'war-a',roleId:100001,start:50,end:64,filter:0});
  await f.call('reports',{warId:'war-a',roleId:100001,start:0,reportFilter:'players'});
  assert.equal(f.calls.at(-1).args.filter,1);
  const guard=await f.call('guard_count',{warId:'war-a',roleId:100001});
  assert.equal(guard.total,1);
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls.at(-1).args)),{warId:'war-a',roleId:100001,start:0,end:14,filter:2});
  await assert.rejects(f.call('reports',{warId:'war-a',roleId:100001,reportFilter:'invalid'}),/筛选/);
  const replay=await f.call('replay',{warId:'war-a',roleId:100001,battleId:8001});
  for(let i=0;i<10;i++)await Promise.resolve();
  assert.equal(f.replays.length,1);assert.equal(f.replays[0][0],f.report);assert.equal(f.replays[0][1],100001);
  assert.equal((await f.call('replay_status')).token,replay.token);
  assert.equal((await f.call('replay_status')).status,'returned');
  f.module.fail=true;await f.call('replay',{warId:'war-a',roleId:100001,battleId:8001});
  for(let i=0;i<10;i++)await Promise.resolve();assert.equal((await f.call('replay_status')).status,'failed');
  f.report.tarRoleInfo.roleId=999;await assert.rejects(f.call('replay',{warId:'war-a',roleId:100001,battleId:8001}),/守卫/);
  f.role.legion.legionId=43;await assert.rejects(f.call('reports',{warId:'war-a',roleId:100001}),/本阴司/);
  console.log('PASS history membership, old rank identity, raw report paging, exact native replay, errors and account switch');
})().catch(e=>{console.error(e);process.exitCode=1;});
