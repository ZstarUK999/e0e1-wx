const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.env.AUCTION_SOURCE || require('path').join(__dirname,'../package/plugin_manager/auction_runtime.js'),'utf8');
async function setup(){
 let now=10000,wall=10000,open=true,interval=null,lists=0,buy=[],responses=[],listResponse={err:null,resp:{itemList:[]}};
 const preview=[{id:1000000,cfgId:7,finalTime:11000,result:-1,type:2},{id:1000001,cfgId:8,finalTime:11000,result:-1,type:2}];
 const l={_isRealAuctionData:false,auctionList:preview,isServerAuctionLimitReached:()=>false,updateAuctionList(){}};
 Object.defineProperty(l,'_auctionList',{set(v){l.auctionList=v;}});
 const mods={'base-module.ts':{ModuleLocalType:{LEGION:1}},'module-manager.ts':{GET_MODULE:()=>l},'define-index.ts':{AuctionService:{getAuctionList:'list',finalPrice:'buy'}},'configs.ts':{AuctionCfg:{getById:id=>({name:'物品'+id,finalPrize:99})}},'date-util.ts':{default:{get serverTime(){return now;}}},'service-manager.ts':{ServiceManager:{ins:{service:(method,payload)=>{
  if(method==='list'){lists++;return Promise.resolve(listResponse);}
  buy.push({wall,...payload});return responses.length?responses.shift()():Promise.resolve({err:{error:'尚未开拍'}});
 }}}},'ui-manager.ts':{UIManager:{ins:{find:()=>open?{ui:{node:{isValid:true}}}:null}}},'ui-common-cfg.ts':{CommonUICfgId:{LegionAuctionUI:1}},'server-data.ts':{ROLE:{id:9,legion:{legionId:4}}}};
 const g={System:{import:async n=>mods[n.split('/').pop()]},setInterval:f=>(interval=f,1),clearInterval:()=>{interval=null;}};
 const ctx={Date:{now:()=>wall}};vm.createContext(ctx);vm.runInContext(source,ctx);const api=await ctx.createAuctionAssistant(g);
 const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
 return {api,buy,l,get lists(){return lists;},get now(){return now;},setList(items){listResponse={err:null,resp:{itemList:items}};},queue(f){responses.push(f);},async at(t){wall=now=t;if(interval)interval();await flush();},close(){open=false;},flush};
}
const real=[{id:501,cfgId:7,activeTime:11000,finalTime:99999,result:0,type:2},{id:502,cfgId:8,activeTime:11000,finalTime:99999,result:0,type:2}];
(async()=>{
 let s=await setup();s.api.arm(['7:0','8:0']);await s.at(10499);assert.equal(s.lists,0);await s.at(10500);assert.equal(s.lists,1);await s.at(10550);assert.equal(s.lists,1);await s.at(10600);assert.equal(s.lists,2);assert.equal(s.buy.length,0,'never buy preview IDs');
 s.setList(real);await s.at(10700);assert.equal(s.buy.length,2);await s.at(10749);assert.equal(s.buy.length,2);await s.at(10750);assert.equal(s.buy.length,4);await s.at(10800);assert.equal(s.buy.length,6);await s.at(10900);assert.equal(s.lists,3,'no list refresh after real list');assert.equal(s.buy.length,6);assert.equal(s.api.status().running,false);for(const kind of ['arm','list-send','list-reply','matched','buy-send','buy-reply','complete'])assert.ok(s.api.status().audit.some(e=>e.kind===kind),'audit '+kind);assert.deepEqual(s.buy.map(x=>x.id),[501,502,501,502,501,502]);
 s=await setup();s.queue(()=>Promise.resolve({err:{error:'竞拍已结束'}}));s.setList(real);s.api.arm(['7:0']);await s.at(10500);await s.at(10600);assert.equal(s.buy.length,1);assert.match(s.api.status().jobs[0].status,/竞拍已结束/);
 s=await setup();s.queue(()=>Promise.resolve({err:null,resp:{}}));s.setList(real);s.api.arm(['7:0']);await s.at(10500);await s.at(10600);assert.equal(s.buy.length,1);assert.equal(s.api.status().jobs[0].status,'购买成功');
 s=await setup();s.api.arm(['7:0']);s.close();await s.at(10500);assert.equal(s.lists,0);assert.equal(s.buy.length,0);assert.equal(s.api.status().running,false);
 s=await setup();s.api.arm(['7:0']);await s.at(16000);assert.equal(s.lists,0,'heartbeat expiry stops');
 s=await setup();s.api.arm(['7:0']);for(let t=10500;t<=14500;t+=100){s.api.status();await s.at(t);}assert.equal(s.api.status().running,true,'no three-second timeout');s.api.stop();await s.at(14600);assert.equal(s.buy.length,0);
 s=await setup();s.setList(real.map(a=>({...a,activeTime:999000})));s.api.arm(['7:0']);await s.at(10500);assert.equal(s.buy.length,1,'preview/activeTime difference must not block buying');assert.equal(s.api.status().jobs[0].sent,1);assert.ok(s.api.status().audit.some(e=>e.kind==='buy-send'));assert.ok(s.api.status().audit.some(e=>e.kind==='buy-reply'));
 console.log('PASS 500ms boundary, 100ms list refresh, no preview purchase, fixed real IDs, 50ms x3, multiple selections, success/ended early stop, close/disconnect/manual stop, no 3s limit');
})().catch(e=>{console.error(e);process.exitCode=1;});
