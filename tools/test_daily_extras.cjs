const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../package/daily_tasks/daily_runtime.js'),'utf8');
function fixture(options={}){
  let now=28800001,freeSlot=options.freeSlots??1,complete=0,completedCount=1,queueUnlocked=!!options.queueUnlocked,hatchFull=false;const calls=[],windows=new Map(),ROLE={recruit:{items:new Map([[1,{lastFreeTime:0}]])},pet:{bornList:[]}};
  const cfg={Draw:{id:'draw'},PetUI:{id:'pet'},DrawReward:{id:'reward'},DrawSpecialBook:{id:'special'},UINewPet:{id:'newpet'},Congrats:{id:'congrats'}};
  const Button=class{},Egg=class{},Slot=class{},counts=new Map([[400001,3],[400004,2],[400005,1]]);
  const table=[{id:400001,quality:2,sort:2,type:18,param:[1]},{id:400004,quality:5,sort:5,type:18,param:[4]},{id:400005,quality:6,sort:6,type:18,param:[5]}];
  const data={ItemType:{PET_ITEM:18},ItemCfg:{getById:id=>table.find(x=>x.id===id)},PetIncubateCfg:{getById:id=>id>0?{time:30}:null},UnlockCfg:{getById:()=>({condition:'queue'})},ConstantCfg:{config:{DrawAdCd:480,PetIncubateSlotBornListNum:options.queuePerSlot??2}}};
  const defs={RoleService:{recruit:()=>{}},PetService:{bornPet:()=>{},getBornPet:()=>{},getBornPetAll:()=>{}}};
  const button=(name,run)=>({name,run});
  const reward=(which)=>{let attempts=0;const s={isFinish:true,view:{btn_close:button('close',()=>{if(++attempts<=(options.ignoredCloses||0))return;windows.delete(which);if(which===cfg.UINewPet && options.rareBatch)reward(cfg.Congrats);})}};windows.set(which,s);};
  const draw={drawTypeInfos:[{cfgId:2,eType:2},{cfgId:1,eType:1}],curSelectPage:0,inDrawing:false,view:{node_pages:[0,1].map(i=>({getComponent:()=>button('tab',()=>draw.curSelectPage=i)}))}};
  draw.view.button_drawOnce=button('paid',()=>{throw Error('paid summon forbidden');});
  draw.view.button_drawAd=button('free',()=>{ROLE.recruit.items.get(1).lastFreeTime=now;if(!options.specialBooks){reward(cfg.DrawReward);return;}
    let remaining=options.specialBooks;
    const special={inAni:false,drawCardId:remaining,allDrawCardIds:Array(remaining).fill(1),view:{}};
    let missed=!!options.missSpecialClose;
    special.view.btn_close=button('special-close',()=>{
      if(missed){missed=false;return;}
      if(--remaining>0){special.drawCardId=remaining;special.allDrawCardIds.pop();}
      else{windows.delete(cfg.DrawSpecialBook);reward(cfg.DrawReward);}
    });windows.set(cfg.DrawSpecialBook,special);
  });
  const slots=[1,2,3,4].map(index=>({index,inClaim:false,btn_claim:button('claim',()=>{complete=0;reward(cfg.UINewPet);})}));
  const page={curEggs:table.map(x=>x.id),node:{getComponentsInChildren:()=>slots},unlockReceiveAll:true,
    btn_recive_all:button('claim-all',()=>{complete=0;reward(options.rareBatch?cfg.UINewPet:cfg.Congrats);})};
  page.list_eggs={};
  const pet={curPage:0,view:{node_page_hatch:page,node_pageList:[0,1,2,3].map(i=>({getComponent:()=>button('pet-tab',()=>pet.curPage=i)}))}};
  const queueCapacity=(options.unlockedSlots??4)*(options.queuePerSlot??2);
  const helper={checkPetHatchCompleteListSlotExist:i=>[i===complete?completedCount:0,1],getFreePetHatchSlot:()=>freeSlot,getMinSecondsUntilPetHatchFinish:()=>30,
    getUnlockedPetHatchSlotCount:()=>options.unlockedSlots??4,getPetHatchQueueNum:()=>ROLE.pet.bornList.length,
    checkPetHatchFull:()=>hatchFull,checkPetHatchQueueFull:()=>ROLE.pet.bornList.length>=queueCapacity};
  const imports={'date-util.ts':{default:{get serverTime(){return now;}}},'ui-pet.ts':{PetPageType:{Hatch:3}},'pet-helper.ts':{petHelper:helper},
    'common-unlock-button.ts':{CommonUnlockFunctionType:{PET_HATCH_QUEUE:42}},'role-helper.ts':{roleHelper:{getItemCount:id=>counts.get(id)||0,checkCondition:()=>queueUnlocked}}};
  const h={configuration:()=>({cfg,data,defs,Button}),ui:()=>({findOpen:k=>windows.get(k),find:k=>windows.get(k)}),
    open:async k=>{const s=k===cfg.Draw?draw:pet;windows.set(k,s);return s;},click:async b=>{calls.push(b.name);b.run();},
    wait:async(f,msg)=>{const v=f();if(!v)throw Error(msg);return v;},observe:async(f,action,verify)=>{calls.push(f[0]===defs.RoleService.recruit?'recruit':'pet');await action();assert(verify());return {baseItems:[{}],items:[{}]};},
    uiClass:async(name)=>name==='pet-egg-item.ts'?Egg:Slot,closeControl:s=>s.view.btn_close,dismissRewards:async()=>{calls.push('blank-dismiss');windows.delete(cfg.Congrats);},
    listNode:async(list,index)=>({getComponent:()=>({eggId:page.curEggs[index],btnHatch:button('hatch:'+page.curEggs[index],()=>{
      assert(!windows.has(cfg.Congrats),'must dismiss results before adding another contract');
      const id=page.curEggs[index];counts.set(id,counts.get(id)-1);
      if(freeSlot>0)freeSlot--;else {assert(queueUnlocked && ROLE.pet.bornList.length<queueCapacity && !hatchFull);ROLE.pet.bornList.push(id);}
    })})})};
  const ctx={};vm.runInNewContext(source+';this.create=createDailyRuntime;',ctx);
  return {api:ctx.create({ROLE,System:{import:async n=>imports[n.split('/').pop()]}},h),calls,counts,draw,queue:ROLE.pet.bornList,
    time:v=>now=v,full:()=>freeSlot=0,completed:(v,count=1)=>{complete=v;completedCount=count;},hatchFull:()=>hatchFull=true};
}
test('free summon reads 480-minute server cooldown and clicks only free button',async()=>{
  const f=fixture();const info=await f.api.dispatch('free_summon_state',{});assert.equal(info.remaining_seconds,0);assert.equal(info.cooldown_seconds,28800);
  const result=await f.api.dispatch('free_summon',{});assert(result.confirmed);assert(f.calls.includes('free'));assert(!f.calls.includes('paid'));
  assert.equal((await f.api.dispatch('free_summon_state',{})).remaining_seconds,28801);
  await assert.rejects(f.api.dispatch('free_summon',{}),/冷却/);assert.equal(f.calls.filter(x=>x==='free').length,1);
});
test('pet selection is quality ordered, rejects other items and full slots, uses normal hatch/claim controls',async()=>{
  const f=fixture(),ids=[400001,400004,400005];
  assert.equal((await f.api.dispatch('pet_hatch_state',{item_ids:ids})).item_id,400005);
  await assert.rejects(f.api.dispatch('pet_hatch_start',{item_id:10004}),/无效/);
  await f.api.dispatch('pet_hatch_start',{item_id:400005});assert.equal(f.counts.get(400005),0);
  assert.equal((await f.api.dispatch('pet_hatch_state',{item_ids:ids})).item_id,400004);
  await assert.rejects(f.api.dispatch('pet_hatch_start',{item_id:400004}),/已满/);
  f.completed(2);await f.api.dispatch('pet_hatch_claim',{slot:2});assert(f.calls.includes('claim'));assert(f.calls.includes('close'));
  await assert.rejects(f.api.dispatch('pet_hatch_claim',{slot:2}),/未完成/);
});
test('unconfirmed free click is uncertain, even before the delayed ad request',async()=>{
  const f=fixture();f.draw.view.button_drawAd.run=()=>{};
  await assert.rejects(f.api.dispatch('free_summon',{}),e=>e.status==='uncertain');
});
test('fills four active slots then all eight queue positions with quality priority',async()=>{
  const f=fixture({freeSlots:4,queueUnlocked:true}),ids=[400001,400004,400005];
  for(const id of ids)f.counts.set(id,10);
  const placed=[];
  for(let n=0;n<20;n++){
    const state=await f.api.dispatch('pet_hatch_state',{item_ids:ids});
    if(!state.can_place)break;
    placed.push(state.item_id);await f.api.dispatch('pet_hatch_start',{item_id:state.item_id});
  }
  assert.equal(placed.length,12);assert.equal(f.queue.length,8);
  assert.deepEqual(placed,[...Array(10).fill(400005),400004,400004]);
  const full=await f.api.dispatch('pet_hatch_state',{item_ids:ids});assert.equal(full.queue_capacity,8);assert.equal(full.can_place,false);
  await assert.rejects(f.api.dispatch('pet_hatch_start',{item_id:400004}),/队列已满/);
});
test('respects a smaller unlocked queue and native furnace-full restriction',async()=>{
  const f=fixture({freeSlots:0,queueUnlocked:true,unlockedSlots:2});f.counts.set(400001,10);
  for(let n=0;n<4;n++)await f.api.dispatch('pet_hatch_start',{item_id:400001});
  assert.equal((await f.api.dispatch('pet_hatch_state',{item_ids:[400001]})).can_place,false);
  const g=fixture({freeSlots:0,queueUnlocked:true});g.hatchFull();
  assert.equal((await g.api.dispatch('pet_hatch_state',{item_ids:[400001]})).can_place,false);
});
test('one-click claim dismisses the result before continuing to fill the queue',async()=>{
  const f=fixture({freeSlots:0,queueUnlocked:true});f.completed(1,3);
  await f.api.dispatch('pet_hatch_claim',{slot:1});
  assert(f.calls.includes('claim-all'));assert(!f.calls.includes('claim'));assert(f.calls.includes('blank-dismiss'));
  await f.api.dispatch('pet_hatch_start',{item_id:400005});assert.equal(f.queue.length,1);
  assert(f.calls.indexOf('blank-dismiss')<f.calls.indexOf('hatch:400005'));
});
test('one-click rare-pet presentation closes before the reward popup and next queue entry',async()=>{
  const f=fixture({freeSlots:0,queueUnlocked:true,rareBatch:true});f.completed(1,3);
  await f.api.dispatch('pet_hatch_claim',{slot:1});
  assert(f.calls.indexOf('close')<f.calls.indexOf('blank-dismiss'));
  await f.api.dispatch('pet_hatch_start',{item_id:400005});assert.equal(f.queue.length,1);
});

for(const op of ['pet_hatch_claim','free_summon']) {
  test(op+' retries a missed reward close without replaying the action',async()=>{
    const f=fixture({ignoredCloses:1});f.completed(2);
    const result=await f.api.dispatch(op,{slot:2});
    assert(result.confirmed);
    assert.equal(f.calls.filter(x=>x==='close').length,2);
    assert.equal(f.calls.filter(x=>x===(op==='pet_hatch_claim'?'claim':'free')).length,1);
  });
  test(op+' stops after three failed closes without replaying the action',async()=>{
    const f=fixture({ignoredCloses:10});f.completed(2);
    await assert.rejects(f.api.dispatch(op,{slot:2}),/已尝试3次/);
    assert.equal(f.calls.filter(x=>x==='close').length,3);
    assert.equal(f.calls.filter(x=>x===(op==='pet_hatch_claim'?'claim':'free')).length,1);
  });
}

for(const count of [1,3])test('free summon handles '+count+' special book presentations before rewards',async()=>{
  const f=fixture({specialBooks:count,missSpecialClose:true});
  const result=await f.api.dispatch('free_summon',{});
  assert(result.confirmed);
  assert.equal(f.calls.filter(x=>x==='free').length,1);
  assert.equal(f.calls.filter(x=>x==='special-close').length,count+1);
  assert.equal(f.calls.filter(x=>x==='close').length,1);
  assert(f.calls.lastIndexOf('special-close')<f.calls.indexOf('close'));
});
