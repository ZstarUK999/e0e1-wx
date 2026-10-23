const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync(__dirname+'/../package/plugin_manager/legion_runtime.js','utf8'),ctx);
(async()=>{
 let response={code:0,getData:()=>({info:{id:12000100,name:'玩家',fightPower:5,legionId:42,legionName:'阴司',sId:540,sName:'540服',lOnlineTime:1792691916767,online:false}})};
 const service={search:async args=>{assert.equal(args.targetId,12000100);return response;}};
 const g={System:{import:async()=>({GoodFriendService:service})}};
 assert.equal((await ctx.scanLegionPlayer(g,'12000100')).legionId,42);
 assert.equal((await ctx.scanLegionPlayer(g,'12000100')).lastOnlineTime,1792691916767);
 assert.equal((await ctx.scanLegionPlayer(g,'12000100')).online,false);
 response={code:0,getData:()=>({info:null})};assert.equal(await ctx.scanLegionPlayer(g,12000100),null);
 response={code:1,error:'玩家不存在'};assert.equal(await ctx.scanLegionPlayer(g,12000100),null);
  response={code:330015,error:'未找到对方数据'};assert.equal(await ctx.scanLegionPlayer(g,12000100),null);
 for(const error of ['请求太频繁','服务器错误','登录过期']){
   response={code:9,error};await assert.rejects(()=>ctx.scanLegionPlayer(g,12000100),new RegExp(error));
 }
 response={code:0,getData:()=>({info:{id:12000101}})};
 await assert.rejects(()=>ctx.scanLegionPlayer(g,12000100),/不匹配/);
 await assert.rejects(()=>ctx.scanLegionPlayer(g,1),/8位/);
  let active=0,maximum=0;
  service.search=async({targetId})=>{
    active++;maximum=Math.max(active,maximum);
    await new Promise(r=>setTimeout(r,5));active--;
    if(targetId===12000101)return {code:9999,error:'服务器限流'};
    return {code:0,getData:()=>({info:{id:targetId,name:'玩家',fightPower:5,legionId:42,legionName:'阴司',sId:540,sName:'540服'}})};
  };
  const batch=await ctx.scanLegionPlayers(g,Array.from({length:10},(_,i)=>12000100+i));
  assert.equal(maximum,10);assert.match(batch[1].error,/服务器限流.*9999/);
  assert.equal(batch[9].value.id,'12000109');
  await assert.rejects(()=>ctx.scanLegionPlayers(g,Array.from({length:11},(_,i)=>12000100+i)),/1至10/);
 console.log('PASS public player search, missing vs retry errors, identity and ID bounds');
})().catch(e=>{console.error(e);process.exitCode=1;});
