// Offline regression coverage for the standalone player-info injection script.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
async function fixture(){
  const role={id:123,hero:{attribute:{attributes:new Map([[200101,99999],[200103,9900]])}}};
  const screen={isSelf:false,info:null};
  const game={ROLE:role,UIManager:{ins:{viewParams:{setting:{cfgId:'Setting',showing:true,ui:screen}}}}};
  const context={Map,Set,Promise,console:{log(){}},setTimeout:fn=>{fn();return 1;},clearTimeout(){},
    __e0e1RegisterRuntimeToggle(){},document:{querySelector:()=>({contentWindow:game})}};
  const source=fs.readFileSync(path.join(__dirname,'js/player_info_dump.js'),'utf8');
  const api=await vm.runInNewContext('(async()=>{'+source+'\nreturn {setCfg(c){e0e1CfgModule=c;},parse:e0e1ParseSeasonAttributes,text:e0e1DumpPlayerInfoText,dump:e0e1DumpPlayerInfo};})()',context);
  api.setCfg({});return {api,screen,role};
}
test('standalone dump reads target seasons without relying on normal AttrCfg',async()=>{
  const {api,screen}=await fixture();
  screen.info={id:777,attribute:new Map([[200101,10300],['200103',5000],[200105,3300],[200107,26500]])};
  const text=await api.text();
  for(const value of ['深渊攻击力 10300','赛季最终增伤 50%','致命一击率 33%','致命一击伤害 265%'])assert.ok(text.includes(value),value);
  assert.doesNotMatch(text,/99999|99%/);
  screen.info.attribute=new Map([[200103,0]]);
  assert.match(await api.text(),/赛季最终增伤 0%/);
  assert.match(await api.text(),/深渊攻击力：未下发/);
});
test('missing foreign snapshot never falls back to ROLE in text or full exports',async()=>{
  const {api}=await fixture();
  assert.equal(await api.text(),'目标玩家快照未下发');
  assert.equal(await api.dump(),null);
});
test('self dump uses hero attributes without mutating ROLE',async()=>{
  const {api,screen,role}=await fixture();screen.isSelf=true;
  assert.match(await api.text(),/深渊攻击力 99999/);
  assert.equal(role.attribute,undefined);assert.equal(role.previewHide,undefined);
});
