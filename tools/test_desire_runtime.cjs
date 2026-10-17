// 三尸合成的正常UI适配测试，不运行微信。
const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs'), path=require('node:path');

const QUALITY={1:'白',2:'蓝',3:'紫',4:'橙',5:'红'};
// cfgId → (type, quality)；type 1..6 是 DesireType，quality 1..8
const ITEMS={101:{type:1,quality:1},102:{type:4,quality:1},201:{type:1,quality:2},401:{type:1,quality:4}};
// ComposeCfg：quality 是目标品质，材料品质 = quality - 1
const COMPOSE=[{id:1,num:2,quality:2,ratio:3000,returned:1},{id:2,num:2,quality:3,ratio:2500,returned:1},
  {id:3,num:2,quality:5,ratio:3000,returned:1},{id:9,num:5,quality:2,ratio:10000,returned:4}];

function fixture(options={}){
  const events=[],logs=[];
  const cfg=Object.fromEntries(['DesireUI','CommonConfirm','Congrats'].map(id=>[id,{id}]));
  const defs={DesireService:{composeGem:()=>{}}};
  const cc={Toggle:'Toggle',Button:'Button'};

  const bag=new Map();
  // 两个白色贪心、一个白色贪凡、一个锁定、一个已镶嵌、一个堆叠(同一 uuid num=3)
  bag.set('u1',{id:'u1',cfgId:101,num:1,locked:false,planInfo:new Map()});
  bag.set('u2',{id:'u2',cfgId:101,num:1,locked:false,planInfo:new Map()});
  bag.set('u3',{id:'u3',cfgId:102,num:1,locked:false,planInfo:new Map()});
  bag.set('u4',{id:'u4',cfgId:101,num:1,locked:true,planInfo:new Map()});
  bag.set('u5',{id:'u5',cfgId:101,num:1,locked:false,planInfo:new Map([[0,101]])});
  bag.set('u6',{id:'u6',cfgId:201,num:3,locked:false,planInfo:new Map()});
  if (options.extra) options.extra(bag);

  const ROLE={desire:{bag,bagId:7,composeCnt:5}};
  const configs={ItemCfg:{getById:id=>({quality:(ITEMS[id]||{}).quality})},
    DesireCfg:{getById:id=>({type:(ITEMS[id]||{}).type})},
    ComposeCfg:{list:COMPOSE}};
  const module={
    putInGems:[0,0,0,0,0], putInGemsUUIDs:[],
    putInGem(item){const i=this.putInGems.indexOf(0);if(i<0)throw Error('合成槽位已满');this.putInGems[i]=item.cfgId;this.putInGemsUUIDs[i]=item.uuid;},
    getPutInGems(){return this.putInGems.slice();},
    clearPutInGems(){this.putInGems=[0,0,0,0,0];},
  };
  const button=(name,fn)=>({name,node:{active:true,activeInHierarchy:true},run:fn});
  // 与 onComposeClick 同判据：放入的任一三尸品质 >= 4 就先弹确认框，点确认后才真正合成。
  const needsConfirm=()=>module.getPutInGems().filter(v=>v>0).some(id=>(ITEMS[id]||{}).quality>=4);
  const onCompose=name=>button(name,()=>{events.push(name);if(needsConfirm()){confirmOpen=true;return;}module.clearPutInGems();});
  const composePage={hasComposeAll:false,node:{activeInHierarchy:true},
    view:{btn_compose:onCompose('compose'),btn_compose2:onCompose('compose2')}};
  const toggles=[{isChecked:true},{isChecked:false},{isChecked:false},{isChecked:false}];
  const bagView={updatebag(){events.push('updatebag');},
    btn_switch_group:{children:[{getComponentsInChildren:()=>toggles}],getComponentsInChildren:()=>toggles}};
  const screen={module,curSelectedIndex:0,pages:[{},composePage],view:{bag:bagView}};
  const windows=new Map([['DesireUI',screen]]);
  let confirmOpen=false;
  const confirm={view:{btn_confirm:button('confirm',()=>{events.push('confirm');confirmOpen=false;module.clearPutInGems();}),
    btn_cancel:button('cancel',()=>{confirmOpen=false;}),btn_close:button('close',()=>{confirmOpen=false;})}};
  let rewardsDismissed=0;

  let resp=options.resp===undefined?{result:true,items:[{data:{i:201,n:1}}]}:options.resp;
  const ui={findOpen:c=>c===cfg.DesireUI?windows.get('DesireUI'):(c===cfg.CommonConfirm&&confirmOpen?confirm:null)};
  const h={
    configuration:()=>({cfg,data:configs,defs,cc,Button:'Button'}),
    ui:()=>ui,
    open:async c=>{events.push('open:'+c.id);if(c===cfg.DesireUI)return screen;throw Error('未知页面');},
    switchTab:async(s,i)=>{events.push('switchTab:'+i);s.curSelectedIndex=i;return s.pages[i];},
    click:async b=>{assert.ok(b&&b.run,'UI按钮存在');events.push(b.name||'click');await b.run();},
    wait:async predicate=>{const value=predicate();assert.ok(value,'UI状态未达成');return value;},
    bounded:async promise=>await promise,
    uiClass:async()=>({}),
    observe:async(expected,action,verify,waitMs)=>{
      assert.ok(expected.includes(defs.DesireService.composeGem),'必须监听 composeGem');
      assert.ok(waitMs>=20000,'合成请求会延迟发出，观察窗口不能太短');
      await action();
      assert.ok(verify(),'合成后槽位应被清空或奖励页已弹出');
      return resp;
    },
    dismissRewards:async()=>{rewardsDismissed++;},
    home:async()=>{events.push('home');},
    log:message=>logs.push(String(message)),
  };
  const g={ROLE,System:{import:async name=>{
    if(name==='chunks:///_virtual/configs.ts')return configs;
    if(name==='chunks:///_virtual/types-common.ts')return {DesireType:{1:'TANHEART',4:'TANORDINARY'}};
    if(name==='chunks:///_virtual/role-helper.ts')return {roleHelper:{getRareName:q=>QUALITY[q]}};
    if(name==='chunks:///_virtual/module-manager.ts')return {GET_MODULE:()=>module,ModuleLocalType:{DEASIRE:11}};
    return {};
  }}};
  const sandbox={setTimeout,clearTimeout};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../package/plugin_manager/desire_runtime.js'),'utf8'),sandbox);
  return {api:sandbox.createDesireRuntime(g,h),events,logs,module,toggles,bag,cfg,ui,
    setConfirm:()=>{confirmOpen=true;},isConfirmOpen:()=>confirmOpen,
    closePage:()=>{windows.delete('DesireUI');},
    rewardsDismissed:()=>rewardsDismissed,setResp:r=>{resp=r;},
    useCompose2:()=>{composePage.hasComposeAll=true;}};
}

test('bag stats exclude locked and embedded, count stacks by num',async()=>{
  const f=fixture();
  const stats=await f.api.dispatch('desire_bag_stats');
  assert.equal(stats.confirmed,true);
  const row=(type,quality)=>stats.groups.find(g=>g.type===type&&g.quality===quality);
  assert.equal(row(1,1).count,2,'两个未锁定的白色贪心');
  assert.equal(row(4,1).count,1);
  assert.equal(row(1,2).count,3,'堆叠按 num 累加');
  assert.equal(row(1,2).distinct,1);
  assert.equal(row(1,2).pairs,1);
  assert.ok(!stats.groups.some(g=>g.quality===3),'配置表里没有目标品质4的二合一');
  assert.equal(JSON.stringify(stats.rates.map(r=>r.quality)),'[1,2,4]');
  assert.equal(stats.qualityNames[1],'白');
  assert.equal(stats.typeCodes[1],'TANHEART');
});

test('compose open switches to the compose tab and sets the kind filter',async()=>{
  const f=fixture();
  // 过滤器下标 0=全部 1=贪 2=嗔 3=痴，所以 kind=2(嗔) 应点亮第 2 个
  const out=await f.api.dispatch('desire_compose_open',{kind:2});
  assert.equal(out.confirmed,true);
  assert.ok(f.events.includes('switchTab:1'));
  assert.equal(JSON.stringify(f.toggles.map(t=>t.isChecked)),'[false,false,true,false]');
  assert.ok(f.events.includes('updatebag'));
});

test('low quality compose fills two slots and never opens the confirm dialog',async()=>{
  const f=fixture();
  const out=await f.api.dispatch('desire_compose_once',{type:1,quality:1});
  assert.equal(out.confirmed,true);
  assert.equal(out.success,true);
  assert.equal(JSON.stringify(out.itemIds),'[101,101]');
  assert.equal(out.sameUuid,false);
  assert.ok(f.events.includes('compose'));
  assert.ok(!f.events.includes('confirm'),'白色不该弹确认框');
  assert.equal(f.module.getPutInGems().filter(v=>v>0).length,0,'合成后槽位已清空');
  assert.equal(f.rewardsDismissed(),1);
});

test('orange and above opens the confirm dialog and closes it',async()=>{
  const f=fixture({extra:bag=>{bag.set('o1',{id:'o1',cfgId:401,num:1,locked:false,planInfo:new Map()});
    bag.set('o2',{id:'o2',cfgId:401,num:1,locked:false,planInfo:new Map()});}});
  f.useCompose2();
  const out=await f.api.dispatch('desire_compose_once',{type:1,quality:4});
  assert.equal(out.confirmed,true);
  assert.ok(f.events.includes('confirm'),'橙色必须先确认');
  assert.equal(f.isConfirmOpen(),false,'确认框必须关掉，否则后续操作全被拒');
  assert.ok(f.events.includes('compose2'),'hasComposeAll 时点的是 btn_compose2');
});

test('failed compose still reports a definite receipt',async()=>{
  const f=fixture({resp:{result:false,items:[]}});
  const out=await f.api.dispatch('desire_compose_once',{type:1,quality:1});
  assert.equal(out.confirmed,true);
  assert.equal(out.success,false);
});

test('not enough materials is rejected and never touches the slots',async()=>{
  const f=fixture();
  await assert.rejects(f.api.dispatch('desire_compose_once',{type:2,quality:1}),/没有可用于合成的两件三尸/);
  assert.equal(f.module.getPutInGems().filter(v=>v>0).length,0);
  assert.ok(!f.events.includes('compose'));
});

test('single stack with num>=2 can be reused, and is marked',async()=>{
  const f=fixture();
  const out=await f.api.dispatch('desire_compose_once',{type:1,quality:2});
  assert.equal(out.confirmed,true);
  assert.equal(out.sameUuid,true,'只有一堆叠时复用同一 uuid，需要标记出来');
  assert.equal(JSON.stringify(out.itemIds),'[201,201]');
});

test('compose never re-navigates: a closed page is reported instead of going home',async()=>{
  const f=fixture();
  await f.api.dispatch('desire_compose_open',{kind:1});
  f.closePage();
  await assert.rejects(f.api.dispatch('desire_compose_once',{type:1,quality:1}),/三尸合成页未打开/);
  assert.ok(!f.events.includes('home'),'批次内不能为了打开页面而先回主界面');
});
