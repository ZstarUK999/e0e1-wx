// 本地假游戏测试：只调用待测运行脚本，不连接微信。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const sourcePath = path.join(__dirname, '../package/daily_tasks/sweep_runtime.js');
function fixture() {
  assert.ok(fs.existsSync(sourcePath), '缺少扫荡正常UI运行脚本');
  const cfg = Object.fromEntries(['MainUI','GameMethod','Hangup','DesireUI','MagicArtifactUI','PetUI','Congrats','HeroLevelUp'].map(n=>[n, {id:n}]));
  const role = {id:123, level:10, energy:{energyValue:90}, hangUp:{sweepNum:0}, adCallBack:new Map(),
    desire:{planOnUsed:0,plan:new Map([[0,new Map([[1,100]])],[1,new Map([[1,101]])]])},
    magic:{onUseMagic:201,onUsePlan:1,plan:new Map([[1,{entry:[1]}],[2,{entry:[2]}]])},
    pet:{fightId:10,bag:new Map([[10,{cfgId:10,level:3,quality:2}],[11,{cfgId:11,level:2,quality:2}]]),formation:{planOnUsed:1,plan:new Map([[1,new Map([[1,11],[2,0],[3,0]])]])}},
    hero:{attribute:{attributes:new Map([[42,0]])}}};
  const requests=[];
  const roleService={sweepHangUp:()=>{}};
  const petService={petFight:()=>{}};
  const define={RoleService:roleService,PetService:petService,SystemService:{adCallBack:()=>{}}};
  const manager={async service(fn,params){ requests.push({fn,params}); return {err:null,resp:{items:[]}}; }};
  function score(){role.hero.attribute.attributes.set(42, role.desire.planOnUsed*100+role.magic.onUsePlan*10+(role.pet.fightId===11?1:0));}
  const desire={async switchPlan(i){await manager.service(desireFn,{planIdx:i});role.desire.planOnUsed=i;score();}};
  const desireFn=()=>{};
  const magic={isUnlock:true,_pendingTemperEntryLocks:new Map(),_temperEntryLockSyncs:new Map(),
    getArtifactConfigs:()=>[{id:201},{id:202},{id:203}],isArtifactOpen:i=>i!==203,isArtifactActivated:i=>i===201||i===202,
    isTemperPlanUnlocked:i=>i===1||i===2,getSelectedArtifactId(){return this.selected||201;},setSelectedArtifactId(i){this.selected=i;},
    getTemperPlanDisplayStates:()=>[1,2,3].map(i=>({planId:i,unlocked:i<3})),
    async equipArtifact(i){await manager.service(artifactFn,{magicId:i});role.magic.onUseMagic=i;return true;},
    async switchTemperPlan(i){await manager.service(planFn,{planId:i});role.magic.onUsePlan=i;score();return true;}};
  const artifactFn=()=>{},planFn=()=>{};
  define.DesireService={switchPlan:desireFn};
  define.MagicService={useMagicWeapon:artifactFn,switchPlan:planFn};
  const helper={getMaxEnergy:()=>100,getHangUpCost:()=>[10,20,30][Math.min(role.hangUp.sweepNum,2)]};
  const shop={getCurLifeCardType:()=>1};
  let mode='success';
  const windows=new Map();
  const main={};windows.set(cfg.MainUI,main);
  const button=cb=>({interactable:true,enabledInHierarchy:true,node:{activeInHierarchy:true},clickCallback:cb,cbTarget:null});
  const desireUI={module:desire,pages:[{switch_btns:{getComponentsInChildren:()=>[0,1,2].map(i=>({...button(()=>desire.switchPlan(i)),isLock:i===2}))}}]};
  const magicUI={module:magic,pages:[],gotoPage(i){this.pages[i]=i===1?{async onEquip(){await magic.equipArtifact(magic.getSelectedArtifactId());}}:{async onPlanSelect(index){await magic.switchTemperPlan(index+1);}};}};
  const petUI={curSelectId:10,refreshSelect(){},view:{btn_inParty:button(async function(){const id=petUI.curSelectId;await manager.service(petService.petFight,{petId:id});const old=role.pet.fightId;const slots=role.pet.formation.plan.get(1);for(const [slot,pet]of slots){if(pet===id)slots.set(slot,old);}role.pet.fightId=id;score();})}};
  const hang={hangUpTime:0,refreshSaoDangButtonShow(){},view:{Icon_HangUpTime:[{},{}],button_saodang:button(()=>{}),btn_TiemChange:button(()=>{hang.hangUpTime=(hang.hangUpTime+1)%2;})},
    clickSweep(){const cost=helper.getHangUpCost()*[1,2][this.hangUpTime];manager.service(roleService.sweepHangUp,{times:[1,2][this.hangUpTime],adCallBack:false}).then(r=>{if(!r.err&&mode!=='no_sync'){role.energy.energyValue-=cost;role.hangUp.sweepNum++;}});}};
  const realService=manager.service;
  manager.service=async function(fn,params){if(fn===roleService.sweepHangUp){if(mode==='pending'){requests.push({fn,params});return new Promise(()=>{});}if(mode==='reject'){requests.push({fn,params});return {err:{code:1},resp:null};}}return await realService.call(this,fn,params);};
  const ui={findOpen:c=>windows.get(c)||null,find:c=>windows.has(c)?{ui:windows.get(c),showing:true}:null,
    get viewParams(){return Object.fromEntries([...windows].map(([c,u],i)=>[i,{cfg:c,ui:u,showing:true}]));},
    async openAwaitLoad(c){const instance=new Map([[cfg.DesireUI,desireUI],[cfg.MagicArtifactUI,magicUI],[cfg.PetUI,petUI],[cfg.Hangup,hang]]).get(c);assert.ok(instance,'不得打开未知/付费UI');windows.set(c,instance);instance.close=()=>windows.delete(c);return instance;}};
  const modules={'configs.ts':{BattleAttributeKey:{GOLD_UP:42},ConstantCfg:{config:{HangUpTimes:[1,2]}},LevelCfg:{getById:()=>({HangUpFreeTime:5,HangUpAdTime:0})},PetCfg:{getById:i=>({name:i===11?'双子僵尸':'其他'})}},
    'role-helper.ts':{roleHelper:helper},'shop-helper.ts':{shopHelper:shop,cardType:{UnActive:0}},'define-index.ts':define,
    'service-manager.ts':{ServiceManager:{ins:manager}},'button-plus.ts':{default:class Button{}},
    'magic-artifact-types.ts':{MagicArtifactPageType:{Temper:0,Artifact:1}}};
  const g={ROLE:role,UIManager:{ins:ui},CommonUICfgId:cfg,System:{import:async uri=>{const name=uri.split('/').pop();assert.ok(modules[name],name);return modules[name];}}};
  // 完整UI输入路径：运行脚本只能触发已绑定节点事件，不能直接赋选择字段。
  const inputs=[];
  class CocosButton {}
  class Label {}
  class RichText {}
  class DesireSwitch {}
  class HangButton {}
  class CommonUnlock {}
  class ArtifactListItem {}
  class PlanItem {}
  const uiNode=(label,cb)=>{const node={activeInHierarchy:true,children:[],emit(event,...args){
    if(event==='touch-end'){inputs.push(label);return typeof node.button.clickCallback==='function'?node.button.clickCallback(...args):cb(...args);}
  },getComponent(){return this.button;}};node.button={node,interactable:true};return node;};
  const inputButton=(label,cb)=>{const b=button(cb);b.node=uiNode(label,cb);b.node.button=b;return b;};
  const closeScreen=(label,c)=>inputButton(label,()=>{const s=windows.get(c);if(s&&s.close)return s.close();});
  main.view={button_pet:inputButton('open:PetUI',()=>ui.openAwaitLoad(cfg.PetUI)),
    btn_desire:{Button_btn:inputButton('open:DesireUI',()=>ui.openAwaitLoad(cfg.DesireUI))},
    button_attrUp:{Button_btn:inputButton('open:AttrUp',()=>ui.openAwaitLoad(cfg.AttrUp))}};
  cfg.AttrUp={id:'AttrUp'};
  const attr={magicArtifactItem:{getComponentInChildren:()=>({Button_btn:inputButton('open:MagicArtifactUI',()=>ui.openAwaitLoad(cfg.MagicArtifactUI))})},view:{}};
  const opener=ui.openAwaitLoad;
  ui.openAwaitLoad=async c=>{if(c===cfg.AttrUp){windows.set(c,attr);attr.close=()=>windows.delete(c);attr.view.btn_close=closeScreen('close:AttrUp',c);return attr;}return opener(c);};
  main.node={getComponentInChildren:()=>({btn_hang_up:{Button_btn:inputButton('open:Hangup',()=>ui.openAwaitLoad(cfg.Hangup))}})};
  desireUI.curSelectedIndex=0;
  desireUI.pages[0].switch_btns.getComponentsInChildren=type=>[0,1,2].map(i=>({...inputButton('sanshi:'+i,()=>desire.switchPlan(i)),isLock:i===2}));
  desireUI.view={btn_close:closeScreen('close:DesireUI',cfg.DesireUI),btnTabGroup:{children:[uiNode('desire-tab:0',()=>{desireUI.curSelectedIndex=0;})]}};
  magicUI.view={btn_close:closeScreen('close:MagicArtifactUI',cfg.MagicArtifactUI),btnTabGroup:{children:[0,1].map(i=>uiNode('magic-tab:'+i,()=>{magicUI.curSelectedIndex=i;magicUI.gotoPage(i);} ))}};
  const originalGoto=magicUI.gotoPage;
  magicUI.gotoPage=function(i){originalGoto.call(this,i);const p=this.pages[i];if(i===1){
    p.btnEquip=inputButton('equip-artifact',()=>p.onEquip());
    p.artifactSelector={listArtifacts:{getItemByListId(index){const id=[201,202,203][index];return {activeInHierarchy:true,getComponent:()=>({btnSelect:inputButton('artifact:'+id,()=>{magic.setSelectedArtifactId(id);})})};},scrollTo(){}}};
  }else{p.selectPlan={isShow:false,btnOpen:inputButton('open-plan-options',()=>{p.selectPlan.isShow=true;}),list_select_item:[1,2,3].map((id,index)=>({node:{activeInHierarchy:true,getComponent:()=>({btnSelect:inputButton('magic-plan:'+id,()=>{p.selectPlan.isShow=false;return p.onPlanSelect(index);})})}}))};}};
  petUI.petList=Array.from(role.pet.bag,([id,p])=>({id,...p}));
  petUI.view.btn_close=closeScreen('close:PetUI',cfg.PetUI);
  const petFightClick=petUI.view.btn_inParty.clickCallback;
  petUI.view.btn_inParty=inputButton('set-eye',()=>petFightClick());
  petUI.view.list_pet={getItemByListId(index){const pet=petUI.petList[index];if(!pet)return null;const node=uiNode('select-pet:'+pet.id,()=>{petUI.curSelectId=pet.id;});return node;},scrollTo(){}};
  hang.view.button_saodang=inputButton('sweep',()=>hang.clickSweep());
 hang.view.btn_TiemChange=inputButton('times',()=>{hang.hangUpTime=(hang.hangUpTime+1)%2;});
  hang.view.button_close=closeScreen('close:Hangup',cfg.Hangup);
  modules['cc']={Button:CocosButton,Label,RichText,Node:{EventType:{TOUCH_START:'touch-start',TOUCH_END:'touch-end'}}};
  modules['ui-desire-switch-btn.ts']={UIDesireSwitchBtn:DesireSwitch};
  modules['main_ui_hang_up_button.ts']={main_ui_hang_up_button:HangButton};
  modules['common-unlock-button.ts']={default:CommonUnlock};
  modules['attr-attr-up.ts']={AttrAttrUp:class AttrAttrUp{}};
  modules['magic-artifact-list-item.ts']={MagicArtifactListItem:ArtifactListItem};
  modules['magic-artifact-temper-plan-item.ts']={MagicArtifactTemperPlanItem:PlanItem};
  const sandbox={setTimeout,clearTimeout,Map,Promise,console};
  vm.runInNewContext(fs.readFileSync(sourcePath,'utf8'),sandbox);
  return {runtime:sandbox.createEnergyRuntime(g,{timeoutMs:50,pauseMs:1}),sandbox,g,role,requests,manager,roleService,petService,windows,cfg,inputs,petUI,uiNode,inputButton,setMode:v=>mode=v};
}

test('all mutations use registered UI node inputs and pet lookup is first',async()=>{
  const f=fixture();const original=(await f.runtime.dispatch('capture')).value;
  const found=await f.runtime.dispatch('catalog',{name:'双子僵尸'});assert.equal(found.status,'ok',JSON.stringify(found));
  assert.equal(f.inputs.find(v=>v.startsWith('open:')),'open:PetUI');
  assert.equal((await f.runtime.dispatch('eye',{eye:11})).status,'ok');
  assert.ok(f.inputs.includes('select-pet:11'));assert.ok(f.inputs.includes('set-eye'));
  const selected=await f.runtime.dispatch('select',{sanshi:1,artifact:202,plan:2});assert.equal(selected.status,'ok');
  for(const input of ['sanshi:1','open:AttrUp','open:MagicArtifactUI','magic-tab:1','artifact:202','equip-artifact','open-plan-options','magic-plan:2'])assert.ok(f.inputs.includes(input),input);
  assert.equal((await f.runtime.dispatch('sweep')).status,'ok');assert.ok(f.inputs.includes('sweep'));
  assert.equal((await f.runtime.dispatch('restore',{original})).status,'ok');
  const source=fs.readFileSync(sourcePath,'utf8');
  for(const forbidden of [/\.curSelectId\s*=(?!=)/,/\.setSelectedArtifactId\(/,/\.gotoPage\(/,/\.onEquip\(/,/\.onPlanSelect\(/,/\.clickSweep\(/,/\.openAwaitLoad\(/,/screen\.close\(/])assert.ok(!forbidden.test(source),String(forbidden));
});

test('missing pet name still stops in pet page and returns home',async()=>{
  const f=fixture();
  f.petUI.petList=f.petUI.petList.filter(p=>p.id!==11);
  const result=await f.runtime.dispatch('catalog',{name:'双子僵尸'});
  assert.equal(result.status,'unavailable');assert.match(result.message,/未找到/);
  assert.ok(f.inputs.includes('close:PetUI'));assert.equal(f.windows.size,1);
  assert.equal(f.requests.length,0);
});

test('same-name pets pick one at random and continue without leaving the pet page',async()=>{
  const f=fixture();
  f.petUI.petList.push({id:12,cfgId:11});f.role.pet.bag.set(12,{cfgId:11});
  const result=await f.runtime.dispatch('catalog',{name:'双子僵尸'});
  assert.equal(result.status,'ok',JSON.stringify(result));
  assert.ok([11,12].includes(result.value.eye));
  assert.ok(f.inputs.includes('open:MagicArtifactUI'),'同名不应中断后续流程');
  assert.equal(f.requests.length,0);
});

test('pet lookup uses visible skin name instead of missing raw cfg match',async()=>{
  const f=fixture();const configs=await f.g.System.import('chunks:///_virtual/configs.ts');
  configs.PetCfg.getById=id=>({name:'僵尸'});configs.PetSkinCfg={getById:id=>({name:'双子僵尸'})};
  f.petUI.petList.find(p=>p.id===11).skin=7;f.role.pet.bag.get(11).skin=7;
  const result=await f.runtime.dispatch('catalog',{name:'双子僵尸'});
  assert.equal(result.status,'ok');assert.equal(result.value.eye,11);
});

test('player information dumps the full snapshot for other players and marks hidden sections',async()=>{
  const f=fixture();f.cfg.Setting={id:'Setting'};
  const configs=await f.g.System.import('chunks:///_virtual/configs.ts');
  configs.SkillBookCfg={getById:()=>({name:'天书甲'})};
  configs.AttrCfg={getById:()=>({note:'技能暴击概率',style:2})};
  configs.DesireCfg={getById:()=>({name:'三尸甲',desc:'pvp增伤10%'})};
  configs.MagicArtifactBaseCfg={getById:()=>({name:'法器甲'})};
  const cc=await f.g.System.import('cc');
  const label=text=>({activeInHierarchy:true,children:[],getComponent:Type=>Type===cc.Label?{enabledInHierarchy:true,string:text}:null});
  const root={activeInHierarchy:true,children:[label('玩家A')],getComponent:()=>null};
  const snapshot={name:'玩家A',level:20,fightPower:100,previewHide:2,
    equipSkill:new Map([[1001,0]]),skillLevel:new Map([[1001,3]]),attribute:new Map([[42,66057]]),
    desirePlan:new Map([[1,2001]]),
    magic:{onUseMagic:201,plan:new Map([[1,{name:'方案1',entry:new Map([[1,{cfgId:301,value:500}]])}]])}};
  const page={isPersonal:false,node:root,info:snapshot};
  f.windows.set(f.cfg.Setting,{isValid:true,isSelf:false,view:{page_info:page},info:snapshot});
  const result=await f.runtime.dispatch('player_information');
  assert.equal(result.status,'ok');
  assert.match(result.value.subject,/全量快照/);
  assert.match(result.value.text,/玩家A/);
  assert.match(result.value.text,/── 天书 ──/);
  assert.match(result.value.text,/── 三尸 ──/);
  assert.match(result.value.text,/── 法器 ──/);
  assert.match(result.value.text,/对方设置了隐藏：三尸/);
  assert.equal(f.requests.length,0);assert.equal(f.inputs.length,0);
});

test('a click that never issues a request is unavailable and does not block later actions',async()=>{
  const f=fixture();const configs=await f.g.System.import('chunks:///_virtual/configs.ts');
  configs.ConstantCfg.config.HangUpRewardPeriod=60;f.role.hangUp.lastRewardTime=0;
  const importer=f.g.System.import;f.g.System.import=async name=>name.endsWith('date-util.ts')?{default:{serverTime:3600000}}:importer(name);
  const defs=await f.g.System.import('chunks:///_virtual/define-index.ts');defs.RoleService.getHangUpReward=()=>{};
  const hang=await f.g.UIManager.ins.openAwaitLoad(f.cfg.Hangup);
  hang.view.button_get_reward=f.inputButton('claim-nothing',()=>{});
  const result=await f.runtime.dispatch('reward_claim');
  assert.equal(result.status,'unavailable');
  assert.match(result.message,/未产生正常请求/);
  assert.equal(f.g.__e0e1EnergyGuard.uncertain,false);
  assert.equal((await f.runtime.dispatch('inspect')).status,'ok');
});

test('global ui delay slows every UI step without changing behaviour',async()=>{
  const f=fixture();
  f.g.__e0e1PluginRuntime={id:'delay-test',config:{ui:{delay_ms:20}},pending:false};
  const start=Date.now();
  const result=await f.runtime.dispatch('eye',{eye:11});
  assert.equal(result.status,'ok',JSON.stringify(result));
  assert.ok(Date.now()-start>=20,'未应用全局UI延时');
});

test('own player information renders translated snapshot sections',async()=>{
  const f=fixture();f.cfg.Setting={id:'Setting'};
  const configs=await f.g.System.import('chunks:///_virtual/configs.ts');
  configs.SkillBookCfg={getById:()=>({name:'天书甲'})};
  configs.AttrCfg={getById:()=>({note:'技能暴击概率',style:2})};
  configs.DesireCfg={getById:()=>({name:'三尸甲',desc:'pvp增伤10%'})};
  configs.MagicArtifactBaseCfg={getById:()=>({name:'法器甲'})};
  const snapshot={name:'本人甲',level:10,fightPower:100,sName:'561服',
    equipSkill:new Map([[1001,0]]),skillLevel:new Map([[1001,3]]),attribute:new Map([[42,66057]]),
    desirePlan:new Map([[1,2001]]),
    magic:{onUseMagic:201,plan:new Map([[1,{name:'方案1',entry:new Map([[1,{cfgId:301,value:500}]])}]])},
    unlockModuleIds:[1,2]};
  const node={activeInHierarchy:true,children:[],getComponent:()=>null};
  const page={isPersonal:true,node,info:snapshot};
  f.windows.set(f.cfg.Setting,{isValid:true,isSelf:true,view:{page_info:page},info:snapshot});
  const result=await f.runtime.dispatch('player_information');
  assert.equal(result.status,'ok');
  assert.equal(result.value.subject,'本人（完整信息）');
  assert.match(result.value.text,/本人甲/);
  assert.match(result.value.text,/── 天书 ──/);
  assert.match(result.value.text,/天书甲 Lv\.3/);
  assert.match(result.value.text,/── 三尸 ──/);
  assert.match(result.value.text,/技能暴击概率 660\.57%/);
  assert.match(result.value.text,/── 法器 ──/);
  assert.equal(f.requests.length,0);
});

test('optimize picks the gold plan from entry data and measures sanshi inside its page',async()=>{
  const f=fixture();
  const configs=await f.g.System.import('chunks:///_virtual/configs.ts');
  // 法器方案2词条带贪财(attrType 42)，方案1没有；三尸方案1实测贪财更高。
  configs.MagicArtifactEntryCfg={getById:id=>({des:id===23?'贪财':'法术暴伤',attrType:id===23?42:107})};
  f.g.ROLE.magic.plan.set(2,{name:'贪财方案',entry:[23]});
  f.magicModuleGetTemperPlans=()=>[
    {planId:1,customName:'法爆',entries:[{slot:1,entryId:8,value:800}]},
    {planId:2,customName:'贪财',entries:[{slot:1,entryId:23,value:680},{slot:2,entryId:23,value:560}]}];
  const magicUI=f.windows.get(f.cfg.MagicArtifactUI)||await f.g.UIManager.ins.openAwaitLoad(f.cfg.MagicArtifactUI);
  magicUI.module.getTemperPlans=f.magicModuleGetTemperPlans;
  const result=await f.runtime.dispatch('optimize');
  assert.equal(result.status,'ok',JSON.stringify(result));
  assert.equal(result.value.choice.plan,2,'应按词条数据选贪财方案');
  assert.equal(result.value.choice.sanshi,1,'应实测三尸方案');
  assert.equal(f.g.ROLE.magic.onUsePlan,2);
  assert.equal(f.g.ROLE.desire.planOnUsed,1);
  assert.ok(f.inputs.includes('magic-plan:2'));
  assert.equal(f.requests.length,2,'只切换三尸与法器各一次');
});

test('optimize prefers desire plan scores from item descriptions over live measurement',async()=>{
  const f=fixture();
  const configs=await f.g.System.import('chunks:///_virtual/configs.ts');
  // 三尸描述文本里带“贪财+X%”：按文本算分，不需要逐个切换实测。
  // 只有“贪财+X%”算加成；“每拥有8%贪财，获得2.25%增伤”是把贪财转成增伤，不能计入。
  configs.DesireCfg={getById:id=>({itemId:{name:'舍利'+(id%10),
    desc:id===11761?'贪财+8%':(id===11762?'每拥有8%贪财，获得2.25%增伤':'攻击力+320')}})};
  f.role.desire.bag=new Map([[100,{id:100,cfgId:11761}],[101,{id:101,cfgId:11762}]]);
  const result=await f.runtime.dispatch('optimize');
  assert.equal(result.status,'ok',JSON.stringify(result));
  assert.deepEqual(JSON.parse(JSON.stringify(result.value.desire_scores)).sort((a,b)=>a[0]-b[0]).map(([,v])=>v),[8,0]);
  assert.equal(result.value.choice.sanshi,0,'应选中带贪财词条的方案');
  assert.equal(f.g.ROLE.desire.planOnUsed,0);
  // 只切了一次三尸（选中方案），没有逐方案测量。
  assert.equal(f.requests.filter(r=>r.fn===f.g.__desireSwitch||false).length,0);
});

test('desire scoring ignores "per 8% gold" conversion text and keeps the current tied plan',async()=>{
  const f=fixture();
  const configs=await f.g.System.import('chunks:///_virtual/configs.ts');
  configs.DesireCfg={getById:id=>({itemId:{name:'贪尸舍利',
    desc:id===11761?'贪财+19.2%':(id===11762?'每拥有8%贪财，获得2.25%增伤':'攻击力+320')}})};
  f.role.desire.bag=new Map([[100,{id:100,cfgId:11761}],[101,{id:101,cfgId:11762}]]);
  // 方案0/1都装贪财三尸(19.2)，方案2只装“每拥有8%贪财”的转换三尸(应为0)。
  f.role.desire.plan.set(1,new Map([[1,100]]));
  f.role.desire.plan.set(2,new Map([[1,101]]));
  f.role.desire.planOnUsed=1;
  const result=await f.runtime.dispatch('optimize');
  assert.equal(result.status,'ok',JSON.stringify(result));
  const scores=JSON.parse(JSON.stringify(result.value.desire_scores));
  const scoreOf=plan=>(scores.find(([id])=>id===plan)||[])[1];
  assert.equal(scoreOf(1),19.2);
  assert.equal(scoreOf(2),0,'转换类文本不能算成贪财加成');
  assert.equal(result.value.choice.sanshi,1,'并列最高且当前已是方案1，不应切换');
  assert.equal(f.g.ROLE.desire.planOnUsed,1);
});

test('hourly reward uses normal UI claim and confirms authoritative reward timestamp',async()=>{
  const f=fixture();const configs=await f.g.System.import('chunks:///_virtual/configs.ts');
  configs.ConstantCfg.config.HangUpRewardPeriod=60;
  f.role.hangUp.lastRewardTime=0;
  const importer=f.g.System.import;f.g.System.import=async name=>name.endsWith('date-util.ts')?{default:{serverTime:3600000}}:importer(name);
  const defs=await f.g.System.import('chunks:///_virtual/define-index.ts');defs.RoleService.getHangUpReward=()=>{};
  const hang=await f.g.UIManager.ins.openAwaitLoad(f.cfg.Hangup);
  hang.view.button_get_reward=f.inputButton('claim-reward',()=>f.manager.service(defs.RoleService.getHangUpReward,{}).then(r=>{if(!r.err)f.role.hangUp.lastRewardTime=3600000;}));
  const info=await f.runtime.dispatch('reward_info');assert.equal(info.status,'ok');assert.equal(info.value.elapsed,3600);
  const claimed=await f.runtime.dispatch('reward_claim');assert.equal(claimed.status,'ok');assert.equal(claimed.value.claimed,true);
  assert.ok(f.inputs.includes('claim-reward'));assert.equal(f.requests.length,1);
});

test('UI callback Promise tail must finish before sweep receipt is reported',async()=>{
  const f=fixture();const hang=await f.g.UIManager.ins.openAwaitLoad(f.cfg.Hangup);
  const original=hang.view.button_saodang.clickCallback;let ended=false;
  hang.view.button_saodang.clickCallback=async()=>{original();await new Promise(resolve=>setTimeout(resolve,20));ended=true;};
  const result=await f.runtime.dispatch('sweep');assert.equal(result.status,'ok');assert.equal(ended,true);
});

test('inspect exposes energy recovery timestamps for timers',async()=>{
  const f=fixture();
  f.role.energy.lastRecoveryTime=1792008134083;
  const result=await f.runtime.dispatch('inspect');
  assert.equal(result.status,'ok',JSON.stringify(result));
  assert.equal(result.value.last_recovery,1792008134.083);
  assert.ok(Number.isFinite(result.value.server_now));
});

test('inspect/catalog are read-only and include only existing unlocked choices',async()=>{
  const f=fixture();
  const result=await f.runtime.dispatch('inspect');assert.equal(result.value.energy,90);assert.equal(result.value.safe,true);
  const catalog=await f.runtime.dispatch('catalog',{name:'双子僵尸'});
  assert.deepEqual(Array.from(catalog.value.sanshi),[0,1]);
  assert.equal(catalog.value.magic.length,4);assert.equal(catalog.value.eye,11);
  assert.equal(f.requests.length,0);
});

for(const field of ['eye','artifact','plan'])test(`unrestorable original ${field} stops catalog before spending or changing equipment`,async()=>{
  const f=fixture();
  if(field==='eye')f.role.pet.bag.delete(f.role.pet.fightId);
  if(field==='artifact')f.role.magic.onUseMagic=0;
  if(field==='plan')f.role.magic.plan.delete(f.role.magic.onUsePlan);
  const result=await f.runtime.dispatch('catalog',{name:'双子僵尸'});
  assert.equal(result.status,'unavailable');assert.equal(f.requests.length,0);
});

test('UI selection, twin eye and original slots restore with no cultivation exchange',async()=>{
  const f=fixture();const original=(await f.runtime.dispatch('capture')).value;
  assert.equal((await f.runtime.dispatch('eye',{eye:11})).status,'ok');
  const selected=await f.runtime.dispatch('select',{sanshi:1,artifact:202,plan:2});
  assert.equal(selected.status,'ok');assert.equal(selected.value,121);
  const restored=await f.runtime.dispatch('restore',{original});assert.equal(restored.status,'ok');
  assert.equal(JSON.stringify(restored.value),JSON.stringify(original));
  assert.ok(f.requests.some(r=>r.fn===f.petService.petFight));
  assert.ok(!f.requests.some(r=>r.params.source));
});

test('sweep clicks normal handler once, captures response and synchronised cost',async()=>{
  const f=fixture();const real=f.manager.service;
  // 体力90、单次8/10体力时自动选最大可用倍率（2倍=20），一次扫荡花掉更多体力。
  const quote=await f.runtime.dispatch('quote');assert.equal(quote.value.times,2);assert.equal(quote.value.cost,20);
  const result=await f.runtime.dispatch('sweep');assert.equal(result.status,'ok');assert.equal(result.value.energy,70);assert.equal(result.value.sweep_num,1);
  const requests=f.requests.filter(r=>r.fn===f.roleService.sweepHangUp);assert.equal(requests.length,1);assert.deepEqual(requests[0].params,{times:2,adCallBack:false});
  assert.equal(f.manager.service,real);
});

test('sweep multiplier follows remaining energy and the switch button state',async()=>{
  for(const [energy,times] of [[90,2],[25,2],[15,1],[5,null]]){
    const f=fixture();f.role.energy.energyValue=energy;
    const result=await f.runtime.dispatch('sweep');
    if(times===null){assert.equal(result.status,'rejected');continue;}
    assert.equal(result.status,'ok',JSON.stringify(result));
    assert.equal(result.value.times,times);
    assert.equal(result.value.energy,energy-10*times);
  }
});

test('unavailable multiplier button keeps the current single sweep',async()=>{
  const f=fixture();
  const hang=await f.g.UIManager.ins.openAwaitLoad(f.cfg.Hangup);
  hang.view.btn_TiemChange.node.activeInHierarchy=false;
  const quote=await f.runtime.dispatch('quote');
  assert.equal(quote.value.can_switch,false);assert.equal(quote.value.times,1);
  assert.equal((await f.runtime.dispatch('sweep')).value.times,1);
});

test('no strength or daily allowance never opens purchase or sends sweep',async()=>{
  const f=fixture();f.role.energy.energyValue=5;
  assert.equal((await f.runtime.dispatch('sweep')).status,'rejected');assert.equal(f.requests.length,0);
});

test('exhausted free and ad allowance never calls sweep or purchase',async()=>{
  const f=fixture();
  const modules=await f.g.System.import('chunks:///_virtual/configs.ts');
  modules.LevelCfg.getById=()=>({HangUpFreeTime:0,HangUpAdTime:0});
  const shop=await f.g.System.import('chunks:///_virtual/shop-helper.ts');shop.shopHelper.getCurLifeCardType=()=>0;
  const result=await f.runtime.dispatch('sweep');assert.equal(result.status,'rejected');assert.equal(f.requests.length,0);
});

for(const mode of ['pending','no_sync'])test(`unconfirmed ${mode} locks later mutations and removes response hook`,async()=>{
  const f=fixture();f.setMode(mode);const real=f.manager.service;
  const result=await f.runtime.dispatch('sweep');assert.equal(result.status,'uncertain');assert.equal(f.manager.service,real);
  assert.equal((await f.runtime.dispatch('eye',{eye:11})).status,'uncertain');
  assert.equal(f.requests.filter(r=>r.fn===f.roleService.sweepHangUp).length,1);
});

test('permanent-ad privilege still uses normal callback and consumes legitimate allowance',async()=>{
  const f=fixture();
  const modules=await f.g.System.import('chunks:///_virtual/configs.ts');
  modules.LevelCfg.getById=()=>({HangUpFreeTime:0,HangUpAdTime:2});
  const shop=await f.g.System.import('chunks:///_virtual/shop-helper.ts');shop.shopHelper.getCurLifeCardType=()=>0;
  const defines=await f.g.System.import('chunks:///_virtual/define-index.ts');
  const hang=await f.g.UIManager.ins.openAwaitLoad(f.cfg.Hangup);
  hang.clickSweep=function(){f.manager.service(defines.SystemService.adCallBack,{adId:8,useRetain:false}).then(r=>{if(!r.err){f.role.energy.energyValue-=10;f.role.adCallBack.set(8,(f.role.adCallBack.get(8)||0)+1);}});};
  const quote=await f.runtime.dispatch('quote');assert.equal(quote.value.allowed,true);
  const result=await f.runtime.dispatch('sweep');assert.equal(result.status,'ok');assert.equal(result.value.energy,80);
  assert.equal(result.value.completed_count,1);assert.equal(f.role.hangUp.sweepNum,0);
  assert.equal(f.requests.length,1);assert.deepEqual(f.requests[0].params,{adId:8,useRetain:false});
});

test('unknown sync result distinguishes completed callback from pending network',async()=>{
  const f=fixture();f.setMode('no_sync');
  const result=await f.runtime.dispatch('sweep');assert.equal(result.status,'uncertain');
  assert.equal(f.g.__e0e1EnergyGuard.pending,false);
  assert.equal(f.g.__e0e1EnergyGuard.action_pending,false);
  assert.equal(f.g.__e0e1EnergyGuard.uncertain,true);
});

test('server rejection stops attempt but is not reported as a successful sweep',async()=>{
  const f=fixture();f.setMode('reject');
  const result=await f.runtime.dispatch('sweep');assert.equal(result.status,'rejected');assert.equal(f.role.hangUp.sweepNum,0);
});

test('sweep waits for delayed reward load and close before returning',async()=>{
  const f=fixture();let fullyClosed=false;
  const ui=f.g.UIManager.ins;
  const views=[];
  const realFind=ui.find;
  ui.find=c=>c===f.cfg.Congrats && views.length?views[0]:realFind(c);
  const realService=f.manager.service;
  f.manager.service=async function(fn,params){
    const receipt=await realService.call(this,fn,params);
    if(fn===f.roleService.sweepHangUp){
      let opened,closed;
      const view={ui:null,waitAfterOpen:new Promise(r=>opened=r),waitAfterClose:new Promise(r=>closed=r)};
      views.push(view);
      setTimeout(()=>{const reward={closeSelf(){f.windows.delete(f.cfg.Congrats);setTimeout(()=>{fullyClosed=true;views.shift();closed();},5);}};reward.view={button_close:f.inputButton('close-reward',()=>reward.closeSelf())};view.ui=reward;f.windows.set(f.cfg.Congrats,reward);opened(reward);},5);
      receipt.resp.items=[{id:1,num:1}];
    }
    return receipt;
  };
  const result=await f.runtime.dispatch('sweep');assert.equal(result.status,'ok');assert.equal(fullyClosed,true);
});

test('inactive permanent GuideUI does not block main screen but active guide does',async()=>{
  const f=fixture();f.cfg.GuideUI={id:'GuideUI'};
  const root={active:false};f.windows.set(f.cfg.GuideUI,{view:{node_guideRoot:root}});
  let result=await f.runtime.dispatch('inspect');assert.equal(result.value.safe,true);
  root.active=true;
  result=await f.runtime.dispatch('inspect');assert.equal(result.value.safe,false);
  assert.ok(result.value.blockers.includes('GuideUI'));
  assert.equal((await f.runtime.dispatch('home')).status,'unavailable');
  assert.equal(f.requests.length,0);
});

test('home closes normal pages and waits for full close even if main is covered',async()=>{
  const f=fixture();const ui=f.g.UIManager.ins;
  f.cfg.Setting={id:'Setting'};
  let finished=false;
  const screen={close(){f.windows.delete(f.cfg.Setting);setTimeout(()=>{finished=true;resolve();},5);}};
  screen.view={btn_close:f.inputButton('close-setting',()=>screen.close())};
  let resolve;const view={cfg:f.cfg.Setting,ui:screen,showing:true,waitAfterClose:new Promise(r=>resolve=r)};
  f.windows.set(f.cfg.Setting,screen);
  const original=ui.find;
  ui.find=c=>c===f.cfg.Setting?view:original(c);
  const result=await f.runtime.dispatch('home');
  assert.equal(result.status,'ok');assert.equal(finished,true);
  assert.equal((await f.runtime.dispatch('inspect')).value.safe,true);
  assert.equal(f.requests.length,0);
});

test('home never closes a battle even if other closable pages exist',async()=>{
  const f=fixture();let closed=false;
  f.windows.set(f.cfg.PetUI,{close(){closed=true;f.windows.delete(f.cfg.PetUI);}});
  f.windows.set({id:'BattleUI'},{battleWorld:{},close(){throw new Error('不得强制关闭战斗');}});
  const result=await f.runtime.dispatch('home');assert.equal(result.status,'unavailable');assert.equal(closed,false);
});

test('home rechecks blocking state after normal page has loaded',async()=>{
  const f=fixture();const ui=f.g.UIManager.ins;
  const screen={};let closed=false;
  screen.close=()=>{closed=true;f.windows.delete(f.cfg.ArenaUI);};
  f.cfg.ArenaUI={id:'ArenaUI'};
  f.windows.set(f.cfg.ArenaUI,screen);
  const originalFind=ui.find;
  const view={cfg:f.cfg.ArenaUI,ui:screen,showing:true,waitAfterOpen:new Promise(resolve=>setTimeout(()=>{screen.battleWorld={};resolve(screen);},5))};
  ui.find=c=>c===f.cfg.ArenaUI?view:originalFind(c);
  const result=await f.runtime.dispatch('home');
  assert.equal(result.status,'unavailable');assert.equal(closed,false);
});

test('battle/foreign screen and pending temper edits prevent actions',async()=>{
  const f=fixture();f.windows.set({id:'BattleUI'},{});
  assert.equal((await f.runtime.dispatch('inspect')).value.safe,false);
  assert.equal((await f.runtime.dispatch('sweep')).status,'unavailable');assert.equal(f.requests.length,0);
});

test('desire ops are routed to the standalone desire runtime, never to the daily-task one',async()=>{
  const f=fixture();
  const seen=[];
  // 日常任务运行时对不认识的操作是 throw，路由顺序错了这里就会炸
  f.sandbox.createDesireRuntime=()=>({async dispatch(op,args){seen.push(op);return {confirmed:true};}});
  f.sandbox.createDailyRuntime=()=>({async dispatch(op,args){throw new Error('不该轮到日常任务运行时：'+op);}});
  const runtime=f.sandbox.createEnergyRuntime(f.g,{timeoutMs:50,pauseMs:1});
  const out=await runtime.dispatch('desire_bag_stats',{});
  assert.equal(out.status,'ok',out.message);
  assert.deepEqual(seen,['desire_bag_stats']);
});
