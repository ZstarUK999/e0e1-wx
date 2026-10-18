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
  UIManager:{ins:{findOpen(){return true;}}},ROLE:{id:123},CommonUICfgId:{MainUI:1},
  System:{import:async name=>name.includes('battle-manager')?{BattleManager:{ins:manager}}:{}}
};
const source=fs.readFileSync(config.bridge,'utf8').replace('__BRIDGE_TOKEN__',JSON.stringify(config.token))
  .replace('__BRIDGE_BUILD__',JSON.stringify(config.build));
vm.runInContext(source,vm.createContext(game));

if(config.largeReply)game.damageCurveDebug=()=>({text:'中文😀'.repeat(100000)});
