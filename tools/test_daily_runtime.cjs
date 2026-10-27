// 日常正常UI适配测试，不运行微信。
const test=require('node:test'), assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
 const events=[],cfg=Object.fromEntries(['MineUI','MineListUI','MineOtherUI','ChatUI','ChatRecruitUI','ArenaUI','ArenaChallengeUI','MineBattleUI','MinePveBattleResultUI','ArenaBattleResultUI'].map(id=>[id,{id}]));
 const constants={MineCfg:{config:{MineExploreNum:3,MineGoodNum:4}},ArtifactMineCfg:{config:{ArtifactExploreNum:2,ArtifactGoodNum:5}}};
 const defs={MineService:{},MagicService:{},ArenaService:{}};
 for(const key of ['MineService','MagicService'])for(const name of ['recDigReward','startDig','getNeighbors','legionHelp','startRob'])defs[key][name]=()=>{};
 defs.ArenaService.getArenaOpponent=()=>{};defs.ArenaService.arenaChallenge=()=>{};
 const types={unlock_finish:1,unlock_filling:2,unlock_idle:3,unlock_work:4};
 const ROLE={mine:{battleNumDay:1,helpNumDay:2},artifactMine:{battleNumDay:0,helpNumDay:0},legion:{legionId:1},arena:{dayBattleNum:2,dayRefreshNum:0}};
 const windows=new Map(),views=new Map(); const button=(name,fn)=>({name,run:fn});
 const makeItems=kind=>[1,3].map(state=>{const item={state};item.node={getComponent:Type=>Type==='MineItem'?item:button('cell:'+kind,()=>{const next=item.state===types.unlock_idle?types.unlock_work:types.unlock_idle;for(const entry of pages[kind].items)entry.state=next;})};return item;});
 const pages={};for(const kind of ['sanshi','artifact']){pages[kind]={node:{activeInHierarchy:true},items:[]};pages[kind].items=makeItems(kind);pages[kind].mine_content={node_items:{children:pages[kind].items.map(i=>i.node)}};}
 const logs=[];
 const list={_curSelect:0,_dataList:[{id:10,siteNum:16,name:'甲',sName:'561服',legionName:'无',fightPower:1000},
  {id:11,siteNum:0,name:'乙',sName:'561服',legionName:'阴司A',fightPower:2000}],view:{}};
 list.view.list_record={getItemByListId:i=>({getComponent:()=>({_data:list._dataList[i],btn_goto:button('goto:'+list._dataList[i].id,()=>{other._targetId=list._dataList[i].id;other._loadedTargetId=other._targetId;windows.delete(cfg.MineListUI);windows.delete(cfg.MineUI);windows.set(cfg.MineOtherUI,{_openMineType:root._mineType,view:{mine_other_sanshi:other,mine_other_magic_artifact:other,btn_list:button('target-list',()=>{list._curSelect=0;list._dataList=list._dataList.slice();windows.set(cfg.MineListUI,list);})}});})})})};
 list.view.btnTabGroup={children:[0,1].map(index=>({getComponent:()=>button('list-tab:'+index,()=>{list._curSelect=index;other._sameLegion=index===1;list._dataList=list._dataList.slice();})}))};
 let refreshIndex=0,refreshProvider=null;
 list.view.btn_refresh=button('list-refresh',()=>{refreshIndex++;list._dataList=refreshProvider?refreshProvider(refreshIndex):[list._dataList[0]];});
 const other={_sameLegion:false,btn_help:button('help',()=>{if(other._sameLegion)(root._mineType===0?ROLE.mine:ROLE.artifactMine).helpNumDay++;else{windows.set(cfg.MineBattleUI,battle);}})};
 for(const kind of ['sanshi','artifact']){pages[kind].btn_other=button('open-list:'+kind,()=>{windows.set(cfg.MineListUI,list);});pages[kind].btn_recruit=button('open-recruit',()=>{windows.set(cfg.ChatUI,chat);windows.set(cfg.ChatRecruitUI,recruit);});}
 const root={_mineType:0,view:{mine_sanshi:pages.sanshi,mine_magic_artifact:pages.artifact}};
 root.view.btn_sanshi=button('kind:sanshi',()=>root._mineType=0);root.view.btn_magic_artifact=button('kind:artifact',()=>root._mineType=1);
 const chat={view:{btn_close:button('close-chat',()=>windows.delete(cfg.ChatUI))}};
 const recruitItem={lbl_status:{string:'发布招募'},btn_recruit:button('publish',()=>windows.delete(cfg.ChatRecruitUI))};
 const recruit={view:{list:{getItemByListId:()=>({getComponent:()=>recruitItem})},btn_close:button('close-recruit',()=>windows.delete(cfg.ChatRecruitUI))}};
 const arena={opponents:[{id:10,rankId:1},{id:11,rankId:2}],robotList:[],inSyncIng:false,view:{label_refreshTime:{string:'5/5'}}};
 arena.view.btn_refresh=button('arena-refresh',()=>{ROLE.arena.dayRefreshNum++;arena.view.label_refreshTime.string='4/5';});
 const confirm={view:{btn_challenge:button('confirm-challenge',()=>{ROLE.arena.dayBattleNum--;windows.set(cfg.MineBattleUI,battle);})}};
 arena.view.list_items={getItemByListId:index=>({getComponent:()=>({roleInfo:arena.opponents[index],btn_challenge:button('target-challenge',()=>windows.set(cfg.ArenaChallengeUI,confirm))})})};
 let blankResult=false,blankTaps=0;
 const result=(which)=>{const screen=blankResult?{view:{},node:{activeInHierarchy:true,emit(type){
   if(type==='touch-end'){blankTaps++;windows.delete(which);}
 }}}:{view:{btn_close:button('close-result',()=>{windows.delete(which);if(which===cfg.MinePveBattleResultUI){windows.delete(cfg.MineOtherUI);windows.set(cfg.MineUI,root);}})}};views.set(which,{ui:screen,params:[{result:1}]});return screen;};
 const battle={view:{btn_skip:{node:{activeInHierarchy:true},interactable:true,run:()=>{events.push('official-skip');windows.delete(cfg.MineBattleUI);windows.set(cfg.ArenaBattleResultUI,result(cfg.ArenaBattleResultUI));windows.set(cfg.MinePveBattleResultUI,result(cfg.MinePveBattleResultUI));}}}};
 const ui={findOpen:c=>windows.get(c),find:c=>views.get(c)||{ui:windows.get(c)}};
 const h={configuration:()=>({cfg,data:constants,defs,cc:{Button:'Button'},Button:'Button'}),ui:()=>ui,
  open:async c=>{events.push('open:'+c.id);if(c===cfg.MineUI){windows.set(cfg.MineUI,root);return root;}if(c===cfg.ArenaUI)return arena;throw Error('未知页面');},
  click:async b=>{assert.ok(b&&b.run,'UI按钮存在');events.push(b.name||'skip');await b.run();},
  uiClass:async(module,name)=>name,listNode:async(list,i)=>list.getItemByListId(i),
  wait:async predicate=>{const value=predicate();assert.ok(value,'正常UI响应未完成');return value;},bounded:async promise=>await promise,
  observe:async(expected,action,verify)=>{assert.ok(expected.every(fn=>typeof fn==='function'));await action();assert.ok(verify());return {items:[]};},
  dismissRewards:async()=>{},home:async()=>{},log:message=>logs.push(String(message))};
 const g={ROLE,System:{import:async()=>({MineItemState:types})}};
 const sandbox={setTimeout,clearTimeout};vm.runInNewContext(fs.readFileSync(process.env.DAILY_RUNTIME_SOURCE || path.join(__dirname,'../package/daily_tasks/daily_runtime.js'),'utf8'),sandbox);
 return {api:sandbox.createDailyRuntime(g,h),events,ROLE,cfg,windows,views,h,recruitItem,other,pages,logs,
  setRefreshList:fn=>{refreshProvider=fn;},refreshCount:()=>refreshIndex,
  useBlankResult:()=>{blankResult=true;},blankTaps:()=>blankTaps,
  setInitialList:fn=>{list._dataList=fn();},list,root};
}
test('independent tomb counts and normal collect/start UI',async()=>{const f=fixture();let a=await f.api.dispatch('tomb_state',{kind:'sanshi'});assert.equal(a.raid_remaining,2);assert.equal(a.fill_remaining,2);let b=await f.api.dispatch('tomb_state',{kind:'artifact'});assert.equal(b.raid_remaining,2);assert.equal(b.fill_remaining,5);assert.equal((await f.api.dispatch('tomb_collect',{kind:'sanshi'})).confirmed,true);assert.equal((await f.api.dispatch('tomb_start',{kind:'sanshi'})).confirmed,true);assert.ok(f.events.includes('cell:sanshi'));});
test('recruit UI publish then exit channel, cooldown never publishes',async()=>{const f=fixture();assert.equal((await f.api.dispatch('tomb_recruit',{kind:'sanshi'})).confirmed,true);assert.ok(f.events.indexOf('publish')<f.events.indexOf('close-chat'));f.recruitItem.lbl_status.string='招募冷却中';await assert.rejects(f.api.dispatch('tomb_recruit',{kind:'sanshi'}),/冷却/);assert.equal(f.events.filter(e=>e==='publish').length,1);});
test('fill list selects correct tab and no site count restriction',async()=>{const f=fixture();f.setRefreshList(()=>[{id:10,siteNum:16},{id:11,siteNum:0}]);const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'fill',refresh:true});assert.equal(scan.targets[1].site_num,0);assert.equal(scan.targets[1].can_fill,true);assert.equal((await f.api.dispatch('tomb_fill',{kind:'sanshi',id:11})).confirmed,true);assert.ok(f.events.includes('goto:11'));});

test('targets carry public player fields shown by the list',async()=>{const f=fixture();const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:false});assert.deepEqual(JSON.parse(JSON.stringify(scan.targets[0])),{id:10,site_num:16,can_fill:false,name:'甲',server:'561服',legion:'无',fight_power:1000});assert.equal(scan.refresh_count,0);});

test('scan refreshes at least five times and stops when no new player appears',async()=>{const f=fixture();const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:true});assert.equal(f.refreshCount(),5);assert.equal(scan.refresh_count,5);assert.equal(scan.new_players,1);assert.deepEqual(scan.targets.map(t=>t.id),[10]);assert.ok(f.logs.some(line=>line.includes('刷新第5次')));assert.ok(f.logs.some(line=>line.includes('甲')&&line.includes('16')));});

test('scan stops as soon as a target reaches the threshold so it stays clickable',async()=>{
  const f=fixture();
  // 初始列表不达标；第1次刷出3棺，第2次刷出20棺（达标），应立即停止。
  f.setInitialList(()=>[{id:900,siteNum:5}]);
  f.setRefreshList(index=>index===1?[{id:201,siteNum:3}]:[{id:200+index,siteNum:20}]);
  const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:true,minimum:16});
  assert.equal(scan.refresh_count,2,'刷到达标目标就该停');
  assert.equal(scan.reached_minimum,true);
  assert.equal(scan.targets[0].site_num,20);
  assert.ok(f.logs.some(line=>line.includes('停止刷新')),f.logs.join('|'));
});

test('scan does not refresh at all when the current list already has a qualifying target',async()=>{
  const f=fixture();
  const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:true,minimum:16});
  assert.equal(scan.refresh_count,0);
  assert.equal(scan.reached_minimum,true);
  assert.ok(f.logs.some(line=>line.includes('无需刷新')));
});

test('fill scan refreshes only once so it cannot exceed the task timeout',async()=>{const f=fixture();f.setRefreshList(index=>[{id:100+index,siteNum:20}]);const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'fill',refresh:true});assert.equal(scan.refresh_count,1);assert.equal(f.refreshCount(),1);});

test('scan keeps refreshing until the tenth try when new players keep coming',async()=>{const f=fixture();f.setRefreshList(index=>[{id:100+index,siteNum:20}]);const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:true});assert.equal(f.refreshCount(),10);assert.equal(scan.refresh_count,10);assert.equal(scan.new_players,10);});
test('tomb state exposes ready time and server clock for timers',async()=>{
  const f=fixture();
  const state=await f.api.dispatch('tomb_state',{kind:'sanshi'});
  assert.equal(typeof state.server_now,'number');
  assert.ok('next_ready_at' in state,'需要暴露下次到期时间');
  assert.ok('cross_day_at' in state,'需要暴露跨日时刻');
  // 给墓设置到期时间后应能读到（秒）
  f.ROLE.mine.siteTime=new Map([[1,(state.server_now+3600)*1000]]);
  const timed=await f.api.dispatch('tomb_state',{kind:'sanshi'});
  assert.ok(Math.abs(timed.next_ready_at-(state.server_now+3600))<2,'应返回最近到期时间(秒)');
});

test('arena refresh and challenge use official skip and close result',async()=>{const f=fixture();assert.equal((await f.api.dispatch('arena_state',{})).tickets,2);assert.equal((await f.api.dispatch('arena_refresh',{})).refresh_remaining,4);const result=await f.api.dispatch('arena_challenge',{id:10});assert.equal(result.win,true);assert.ok(f.events.includes('target-challenge'));assert.ok(f.events.includes('confirm-challenge'));assert.ok(f.events.includes('official-skip'));assert.ok(f.events.includes('close-result'));});
test('arena battle is skipped, waits for result and leaves the result page by blank tap',async()=>{
  const f=fixture();
  f.useBlankResult();  // 结算页没有关闭按钮，只能像手动那样点空白处退出
  const result=await f.api.dispatch('arena_challenge',{id:10});
  assert.equal(result.win,true);
  assert.ok(f.events.includes('official-skip'),'进入战斗后应点官方跳过');
  assert.equal(f.blankTaps(),1,'结算页应通过点击空白处退出');
  assert.equal(f.windows.has(f.cfg.ArenaBattleResultUI),false);
  assert.equal(f.windows.has(f.cfg.MineBattleUI),false);
});

test('challenge allows a long wait for the battle transition',async()=>{
  const f=fixture();
  const waits=[];
  const original=f.h.observe;
  f.h.observe=async(expected,action,verify,waitMs)=>{waits.push(waitMs);return await original(expected,action,verify,waitMs);};
  await f.api.dispatch('arena_challenge',{id:10});
  assert.ok(waits.includes(30000),'战斗转场需要比普通请求更长的等待：'+waits.join(','));
});

test('battle screen is resolved from BattleUICfgId even when CommonUICfgId lacks it',async()=>{
  const f=fixture();
  // 真实游戏：战斗界面 id 只在 BattleUICfgId，CommonUICfgId 里查不到。
  f.cfg.MineBattleUI={id:'NotARealBattleUI'};
  const battleId={id:'MineBattleUI'};
  f.h.battleCfg=async()=>({MineBattleUI:battleId});
  const screen={view:{btn_close:{node:{activeInHierarchy:true},interactable:true,run(){f.windows.delete(f.cfg.ArenaBattleResultUI);}}}};
  f.windows.set(battleId,{view:{btn_skip:{node:{activeInHierarchy:true},interactable:true,run(){
    f.events.push('official-skip');
    f.windows.delete(battleId);
    f.views.set(f.cfg.ArenaBattleResultUI,{ui:screen,params:[{result:1}]});
    f.windows.set(f.cfg.ArenaBattleResultUI,screen);
  }}}});
  const result=await f.api.dispatch('arena_challenge',{id:10});
  assert.equal(result.win,true);
  assert.ok(f.events.includes('official-skip'));
});

test('no challenge ticket never opens confirmation',async()=>{const f=fixture();f.ROLE.arena.dayBattleNum=0;await assert.rejects(f.api.dispatch('arena_challenge',{id:10}),/次数/);assert.ok(!f.events.includes('target-challenge'));});


test('count reads do not navigate away from a target page',async()=>{
 const f=fixture();f.h.open=async()=>{throw Error('counts must not navigate');};
 const state=await f.api.dispatch('tomb_state',{kind:'sanshi',counts_only:true});
 assert.equal(state.fill_remaining,2);assert.equal(state.raid_remaining,2);
 assert.equal(f.events.length,0);
});

test('repeated fills reuse the loaded target even after the native UI closes its list',async()=>{
 const f=fixture();f.setRefreshList(()=>[{id:11,siteNum:0}]);
 await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'fill',refresh:true});
 await f.api.dispatch('tomb_fill',{kind:'sanshi',id:11});
 assert.equal(f.windows.has(f.cfg.MineListUI),false);
 await f.api.dispatch('tomb_state',{kind:'sanshi',counts_only:true});
 await f.api.dispatch('tomb_fill',{kind:'sanshi',id:11});
 assert.equal(f.ROLE.mine.helpNumDay,4);
 assert.equal(f.events.filter(e=>e==='goto:11').length,1);
 assert.equal(f.events.filter(e=>e==='open:MineUI').length,1);
});

test('next scan uses target list button instead of reopening own mine',async()=>{
 const f=fixture();f.setRefreshList(()=>[{id:11,siteNum:0}]);
 await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'fill',refresh:true});
 await f.api.dispatch('tomb_fill',{kind:'sanshi',id:11});
 await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'fill',refresh:true});
 assert.ok(f.events.includes('target-list'));
 assert.equal(f.events.filter(e=>e==='open:MineUI').length,1);
});

test('excluded raid targets do not prematurely stop refreshing',async()=>{
 const f=fixture();f.setRefreshList(()=>[{id:12,siteNum:20}]);
 const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:true,minimum:16,exclude_ids:[10]});
 assert.equal(scan.refresh_count,1);assert.equal(scan.targets[0].id,12);
});

test('target identity and loaded state must agree before clicking help',async()=>{
 const f=fixture();await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'fill',refresh:false});
 await f.api.dispatch('tomb_fill',{kind:'sanshi',id:11});
 f.other._loadedTargetId=999;
 await assert.rejects(f.api.dispatch('tomb_fill',{kind:'sanshi',id:11}));
 assert.equal(f.events.filter(e=>e==='help').length,1);
});

test('raid waits for the official return before the next scan',async()=>{
 const f=fixture();await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:false});
 const receipt=await f.api.dispatch('tomb_raid',{kind:'sanshi',id:10});
 assert.equal(receipt.win,true);assert.ok(f.windows.has(f.cfg.MineUI));
});


async function pollingWait(predicate,message){
 const until=Date.now()+1000;
 while(Date.now()<until){const value=predicate();if(value)return value;await new Promise(r=>setTimeout(r,5));}
 throw Error(message||'test UI did not settle');
}

test('fill waits for target reload and the busy flag before another click',async()=>{
 const f=fixture();f.setRefreshList(()=>[{id:11,siteNum:0}]);
 await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'fill',refresh:true});
 await f.api.dispatch('tomb_fill',{kind:'sanshi',id:11});
 f.h.wait=pollingWait;
 f.other._helpBusy=true;f.other._loadedTargetId=0;f.other.btn_help.interactable=false;
 let ready=false;
 setTimeout(()=>{ready=true;f.other._helpBusy=false;f.other._loadedTargetId=11;f.other.btn_help.interactable=true;},30);
 const click=f.h.click;f.h.click=async button=>{if(button===f.other.btn_help)assert.ok(ready,'must wait for target reload');return click(button);};
 await f.api.dispatch('tomb_fill',{kind:'sanshi',id:11});
 assert.equal(f.ROLE.mine.helpNumDay,4);
});

test('fill-tab transition waits for its asynchronous list response',async()=>{
 const f=fixture();f.h.wait=pollingWait;
 const originalObserve=f.h.observe;
 f.h.observe=async(expected,action,verify,ms)=>{await action();await pollingWait(verify,'list data still pending');return {items:[]};};
 f.list.view.btnTabGroup.children[1].getComponent=()=>({run(){
   f.list._curSelect=1;setTimeout(()=>{f.list._dataList=[{id:88,siteNum:0}];},30);
 }});
 const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'fill',refresh:false});
 assert.equal(scan.targets[0].id,88);
});


for(const kind of ['sanshi','artifact'])test(kind+' consecutive fill actions use independent counters',async()=>{
 const f=fixture();f.setRefreshList(()=>[{id:11,siteNum:0}]);
 await f.api.dispatch('tomb_targets',{kind,mode:'fill',refresh:true});
 const own=kind==='sanshi'?f.ROLE.mine:f.ROLE.artifactMine;
 const before=own.helpNumDay;
 await f.api.dispatch('tomb_fill',{kind,id:11});
 await f.api.dispatch('tomb_fill',{kind,id:11});
 assert.equal(own.helpNumDay,before+2);
 assert.equal(f.events.filter(e=>e==='goto:11').length,1);
});

test('raid waits through an asynchronous official return to the mine',async()=>{
 const f=fixture();f.h.wait=pollingWait;
 await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:false});
 const click=f.h.click;let returned=false;
 f.h.click=async button=>{
   await click(button);
   if(button.name==='close-result'){
     f.windows.delete(f.cfg.MineUI);
     setTimeout(()=>{returned=true;f.windows.set(f.cfg.MineUI,f.root);},30);
   }
 };
 await f.api.dispatch('tomb_raid',{kind:'sanshi',id:10});
 assert.ok(returned,'must wait before reporting completion to the batch');
});


test('retry scan keeps looking for the preferred player instead of stopping at another eligible target',async()=>{
 const f=fixture();f.setRefreshList(index=>index===1?[{id:12,siteNum:20}]:[{id:13,siteNum:20}]);
 const scan=await f.api.dispatch('tomb_targets',{kind:'sanshi',mode:'raid',refresh:true,minimum:16,preferred_id:13});
 assert.equal(scan.refresh_count,2);assert.equal(scan.targets[0].id,13);
});


test('two fills then server refusal switches player through native next button without recreating target UI',async()=>{
 const f=fixture();f.setInitialList(()=>[{id:11,siteNum:0},{id:12,siteNum:0}]);
 await f.api.dispatch('tomb_targets',{kind:'artifact',mode:'fill',refresh:false});
 await f.api.dispatch('tomb_fill',{kind:'artifact',id:11});await f.api.dispatch('tomb_fill',{kind:'artifact',id:11});
 const root=f.windows.get(f.cfg.MineOtherUI);root._mineType=1;root._openMineType=1;root.targetIds=[11,12];root.targetIndex=0;
 const help=f.other.btn_help.run;f.other.btn_help.run=()=>{throw Object.assign(new Error('暂无可填土墓藏'),{status:'rejected'});};
 await assert.rejects(f.api.dispatch('tomb_fill',{kind:'artifact',id:11}),/暂无可填土墓藏/);f.other.btn_help.run=help;
 root.view.btn_next={name:'native-next',run:async()=>{await new Promise(r=>setTimeout(r,10));root.targetIndex=1;f.other._targetId=12;f.other._loadedTargetId=12;}};
 await f.api.dispatch('tomb_fill',{kind:'artifact',id:12});
 assert.equal(f.ROLE.artifactMine.helpNumDay,3);assert(f.events.includes('native-next'));assert(!f.events.includes('goto:12'));
});

test('nonadjacent target fully exits old page and ignores a released transitional component',async()=>{
 const f=fixture();f.setInitialList(()=>[{id:11,siteNum:0},{id:12,siteNum:0}]);
 await f.api.dispatch('tomb_targets',{kind:'artifact',mode:'fill',refresh:false});await f.api.dispatch('tomb_fill',{kind:'artifact',id:11});
 const old=f.windows.get(f.cfg.MineOtherUI);
 f.h.home=async()=>{f.events.push('safe-home');old.view=null;f.windows.delete(f.cfg.MineOtherUI);};
 const baseClick=f.h.click;
 f.h.click=async button=>{
   if(button.name==='goto:12'){
     await baseClick(button);const fresh=f.windows.get(f.cfg.MineOtherUI);
     f.windows.set(f.cfg.MineOtherUI,old);
     setTimeout(()=>f.windows.set(f.cfg.MineOtherUI,fresh),10);return;
   }
   return await baseClick(button);
 };
 f.h.wait=async predicate=>{for(let i=0;i<30;i++){const v=predicate();if(v)return v;await new Promise(r=>setTimeout(r,3));}throw Error('wait failed');};
 await f.api.dispatch('tomb_fill',{kind:'artifact',id:12});
 assert(f.events.includes('safe-home'));assert.equal(f.ROLE.artifactMine.helpNumDay,2);
 assert.notEqual(f.windows.get(f.cfg.MineOtherUI),old);
});


test('a released MineOtherUI during PageTurning is observed without dereferencing its null view',async()=>{
 const f=fixture();f.cfg.PageTurning={id:'PageTurning'};
 await f.api.dispatch('tomb_targets',{kind:'artifact',mode:'fill',refresh:false});
 const baseClick=f.h.click;
 f.h.click=async button=>{
   if(button.name==='goto:11'){
     await baseClick(button);const fresh=f.windows.get(f.cfg.MineOtherUI);
     f.windows.set(f.cfg.MineOtherUI,{view:null});f.windows.set(f.cfg.PageTurning,{});
     setTimeout(()=>f.windows.set(f.cfg.MineOtherUI,fresh),8);
     setTimeout(()=>f.windows.delete(f.cfg.PageTurning),15);return;
   }
   if(button===f.other.btn_help)assert(!f.windows.has(f.cfg.PageTurning),'do not fill during the native transition');
   return await baseClick(button);
 };
 f.h.wait=async predicate=>{for(let i=0;i<30;i++){const v=predicate();if(v)return v;await new Promise(r=>setTimeout(r,3));}throw Error('wait failed');};
 await f.api.dispatch('tomb_fill',{kind:'artifact',id:11});assert.equal(f.ROLE.artifactMine.helpNumDay,1);
});

test('arena retries result dismissal without repeating the challenge',async()=>{
  const f=fixture(),click=f.h.click;let closes=0;
  f.h.click=async b=>{if(b.name==='close-result' && ++closes===1)return;return click(b);};
  const result=await f.api.dispatch('arena_challenge',{id:10});
  assert(result.confirmed);assert.equal(closes,2);
  assert.equal(f.events.filter(x=>x==='confirm-challenge').length,1);assert.equal(f.ROLE.arena.dayBattleNum,1);
});
