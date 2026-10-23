const fs=require('fs'),path=require('path'),vm=require('vm'),test=require('node:test'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../package/daily_tasks/daily_runtime.js'),'utf8');
function fixture(pets){
 const calls=[],bag=new Map(pets.map(p=>[p.id,{lock:0,quality:2,mergerCount:0,...p}]));let requests=0,onSelect=null;
 const ROLE={pet:{bag,fightId:0,formation:{plan:new Map()}}},cfg={PetUI:{},UIPetQualityUp:{},CommonConfirm:{}};
 const windows=new Map(),defs={PetService:{petMerge:()=>{}}},button=(name,run)=>({name,run});
 const helper={checkPetInFormation:()=>-1,getQualityUpCanUsePets:id=>[...bag.values()].filter(p=>p.id!==id && p.quality===bag.get(id).quality && p.lock===0 && p.id!==ROLE.pet.fightId).map(p=>p.id)};
 const screen={curPage:0,curSelectId:0,petList:[...bag.values()],view:{list_pet:{}}};
 const page={curSelectPetId:0,curUseInfos:[],curUseIndex:0,canUseInfos:[],node_unSelect:{active:true},node_selectRoot:{active:false},list_selectItem:{}};
 screen.view.node_page_qualityUp=page;
 screen.view.node_pageList=[0,1].map(i=>({getComponent:()=>button('page:'+i,()=>screen.curPage=i)}));
 const open=()=>{page.node_selectRoot.active=true;page.canUseInfos=helper.getQualityUpCanUsePets(page.curSelectPetId).map(id=>({id,type:'pet'}));};
 page.btn_openSelect=button('materials',open);page.btn_openSelect2=button('materials',open);
 page.btn_closeSelect2=button('close-materials',()=>page.node_selectRoot.active=false);
 const execute=()=>{
   const a=bag.get(page.curSelectPetId),b=bag.get(page.curUseInfos[0].id);requests++;bag.delete(b.id);a.mergerCount+=b.mergerCount+1;
   if(a.mergerCount>=(a.quality===2?8:10)){
     a.quality++;a.mergerCount=0;
     windows.set(cfg.UIPetQualityUp,{view:{btn_Close:button('close-promotion',()=>windows.delete(cfg.UIPetQualityUp))}});
   }
   page.curUseInfos=[];page.node_unSelect.active=true;screen.petList=[...bag.values()];
 };
 page.btn_qualityUp=button('merge',()=>{
   const a=bag.get(page.curSelectPetId),b=bag.get(page.curUseInfos[0].id);
   if(a.mergerCount+b.mergerCount>(a.quality===2?8:10))windows.set(cfg.CommonConfirm,{view:{label_desc:{string:'燃魂灯亮度将会溢出！'},btn_confirm:button('confirm-overflow',()=>{windows.delete(cfg.CommonConfirm);execute();})}});
   else execute();
 });
 const imports={'pet-helper.ts':{petHelper:helper},'ui-pet.ts':{PetPageType:{QualityUp:1}}};
 const h={configuration:()=>({cfg,defs,Button:class{},data:{PetQualityCfg:{getById:q=>({minNum:q===2?8:10})}}}),
   open:async()=>screen,ui:()=>({findOpen:id=>windows.get(id),find:id=>windows.get(id)}),
   wait:async(f,msg)=>{const v=f();if(!v)throw Error(msg);return v;},
   click:async b=>{if(windows.has(cfg.UIPetQualityUp) && b.name!=='close-promotion')throw Error('promotion blocks next action');calls.push(b.name);b.run();},
   listNode:async(list,index)=>list===screen.view.list_pet?button('target:'+screen.petList[index].id,()=>{screen.curSelectId=page.curSelectPetId=screen.petList[index].id;page.curUseInfos=[];if(onSelect)onSelect();}):
     button('material:'+page.canUseInfos[index].id,()=>page.curUseInfos[0]=page.canUseInfos[index]),
   observe:async(expected,action,verify)=>{assert.equal(expected[0],defs.PetService.petMerge);const before=requests;await action();assert.equal(requests,before+1);assert(verify());return {items:[]};},
   closeControl:s=>s.view.btn_Close,dismissRewards:async()=>calls.push('dismiss-rewards')};
 const context={};vm.runInNewContext(source+';this.create=createDailyRuntime;',context);
 return {api:context.create({ROLE,System:{import:async n=>imports[n.split('/').pop()]}},h),bag,ROLE,calls,requests:()=>requests,onSelect:f=>onSelect=f};
}
const pair=(target_id,material_id,quality=2,target_progress=0,material_progress=0)=>({target_id,material_id,quality,target_progress,material_progress});
test('state excludes locked, active and saved formation pets and all higher realms',async()=>{
 const f=fixture([{id:1},{id:2,lock:1},{id:3},{id:4},{id:5,quality:5}]);f.ROLE.pet.fightId=3;
 f.ROLE.pet.formation.plan.set(9,new Map([[1,4]]));
 const state=await f.api.dispatch('pet_fodder_state',{});assert.deepEqual(Array.from(state.pets).filter(p=>p.eligible).map(p=>p.id),[1]);
 assert.equal(f.requests(),0);assert.equal(f.calls.length,0);
});
test('native target/material selection merges zeroes without item materials',async()=>{
 const f=fixture([{id:1},{id:2}]),result=await f.api.dispatch('pet_fodder_merge',pair(1,2));
 assert(result.confirmed && !result.advanced);assert.equal(f.bag.get(1).mergerCount,1);assert(!f.bag.has(2));
 assert.deepEqual(f.calls,['page:1','target:1','materials','material:2','close-materials','merge','dismiss-rewards']);
});
test('failed three-plus-three follows with a three and closes promotion before continuing',async()=>{
 const f=fixture([{id:1,quality:3,mergerCount:3},{id:2,quality:3,mergerCount:3},{id:3,quality:3,mergerCount:3}]);
 assert.equal((await f.api.dispatch('pet_fodder_merge',pair(1,2,3,3,3))).advanced,false);
 const next=await f.api.dispatch('pet_fodder_merge',pair(1,3,3,7,3));assert(next.advanced);assert.equal(f.bag.get(1).quality,4);
 assert(f.calls.indexOf('close-promotion')<f.calls.lastIndexOf('dismiss-rewards'));
});
test('animal-realm overflow uses only the native expected confirmation',async()=>{
 const f=fixture([{id:1,mergerCount:7},{id:2,mergerCount:3}]);
 assert((await f.api.dispatch('pet_fodder_merge',pair(1,2,2,7,3))).advanced);assert(f.calls.includes('confirm-overflow'));
});
test('stale progress, protected pets, mismatched realms and selection-time changes never merge',async()=>{
 for(const pets of [[{id:1,mergerCount:1},{id:2}],[{id:1},{id:2,lock:1}],[{id:1},{id:2,quality:3}],[{id:1,quality:5},{id:2,quality:5}]]){
   const f=fixture(pets);await assert.rejects(f.api.dispatch('pet_fodder_merge',pair(1,2)));assert.equal(f.requests(),0);
 }
 const f=fixture([{id:1},{id:2}]);f.onSelect(()=>f.bag.get(1).lock=1);
 await assert.rejects(f.api.dispatch('pet_fodder_merge',pair(1,2)));assert.equal(f.requests(),0);
});
