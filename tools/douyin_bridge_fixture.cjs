// Headless fixture for the real filesystem bridge. Never loads a real game.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const manager={getBattles(){return[];},createBattle(){}};
const game={
  eval:undefined,Function:undefined,
  console:{log(){},error(){}},setTimeout,clearTimeout,setInterval,clearInterval,
  tt:{env:{USER_DATA_PATH:'ttfile://user'},getFileSystemManager(){return{
    readFileSync(p){return fs.readFileSync(path.join(config.user,p.replace('ttfile://user/','')),'utf8');},
    unlinkSync(p){fs.unlinkSync(path.join(config.user,p.replace('ttfile://user/','')));},
    writeFileSync(p,value){fs.writeFileSync(path.join(config.user,p.replace('ttfile://user/','')),value,'utf8');}
  };}},
  UIManager:{ins:{findOpen(){return true;}}},ROLE:{id:123,legion:{legionId:42},season:{seasonId:1,hisWarMap:new Map()}},CommonUICfgId:{MainUI:1},
  System:{import:async name=>{
    const legion={id:42,name:'测试阴司',fightPower:400000000,members:new Map([[12000100,{id:12000100,name:'玩家',job:1}]])};
    if(name.includes('define-index'))return {LegionService:{getLegionSeasonInfo:Object.assign(()=>{},{kind:'history'}),getSeasonBfLegionRank:()=>{},getSeasonBfRoleRank:()=>{}},
      GoodFriendService:{search:async({targetId})=>({code:0,getData:()=>({info:{id:targetId,name:'玩家',fightPower:500,legionId:42,legionName:'测试阴司',sId:540,sName:'540服'}})})}};
    if(name.includes('configs'))return {SeasonBattleTimeCfg:{getById:()=>({name:'血月初赛',battleType:1})}};
    if(name.includes('service-manager'))return {SERVICE:async fn=>({err:null,resp:fn.kind==='history'?
      {legionSeason:{seasonId:1,bTimeInfos:new Map([[101,{warId:'fixture-war'}]])}}:{rank:[]}})};
    if(name.includes('module-manager'))return {GET_MODULE:()=>({sendGetLegionPreview:async()=>legion,sendSearchLegion:async()=>({resp:{legionData:legion}})})};
    if(name.includes('base-module'))return {ModuleLocalType:{LEGION:1}};
    return name.includes('battle-manager')?{BattleManager:{ins:manager}}:{};
  }}
};
const source=fs.readFileSync(config.bridge,'utf8').replace('__BRIDGE_TOKEN__',JSON.stringify(config.token))
  .replace('__BRIDGE_BUILD__',JSON.stringify(config.build));
vm.runInContext(source,vm.createContext(game));

if(config.largeReply)game.damageCurveDebug=()=>({text:'中文😀'.repeat(100000)});
