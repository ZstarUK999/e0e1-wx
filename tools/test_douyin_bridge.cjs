// The sandbox disables BOTH dynamic execution entry points.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const scripts=`{
  resident:function(id){globalThis.__e0e1PluginRuntime={id,pending:false,async dispatch(op,args){
    if(op==='count'){globalThis.executed=(globalThis.executed||0)+1;return {status:'ok',value:42};}
    return {status:'ok',value:true};}};return {resident_id:id};},
  damageStop:async function(){return JSON.stringify({ok:true,enabled:false});},
  damageEnable:async function(){await Promise.resolve();globalThis.damageEnabled=true;return JSON.stringify({ok:true,enabled:true});},
  treasure:async function(){return true;},season:async function(){return true;}
}`;
const source=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/douyin_bridge.js'),'utf8')
  .replace('__BRIDGE_TOKEN__','"fixture-token"').replace('__BRIDGE_BUILD__','"fixture-build"')
  .replace('__BRIDGE_STATIC_SCRIPTS__',scripts);
const files=new Map(),timers=new Map();
const base='ttfile://user/e0e1-plugin-';
let next=0,sequence=0;
const context=vm.createContext({eval:undefined,Function:undefined,
  tt:{env:{USER_DATA_PATH:'ttfile://user'},getFileSystemManager(){return{
    readFileSync(p){if(!files.has(p))throw Error('missing');return files.get(p);},writeFileSync(p,v){files.set(p,v);}
  };}},UIManager:{ins:{findOpen(){return true;}}},ROLE:{},System:{},CommonUICfgId:{MainUI:1},
  setInterval(fn,ms){const id=++next;timers.set(id,{fn,ms});return id;},clearInterval(id){timers.delete(id);}
});
async function tick(){for(const timer of [...timers.values()])if(timer.ms===100)timer.fn();for(let i=0;i<40;i++)await Promise.resolve();}
function state(){return JSON.parse(files.get(base+'state.json'));}
function response(){return JSON.parse(files.get(base+'response.json'));}
function command(id,action,args={},extra={}){files.set(base+'command.json',JSON.stringify({
  token:'fixture-token',runtime:state().runtime,id,sequence:++sequence,action,args,deadline:Date.now()+5000,...extra}));}
(async()=>{
  vm.runInContext(source,context);
  assert.equal(vm.runInContext('typeof eval',context),'undefined');
  assert.equal(vm.runInContext('typeof Function',context),'undefined');
  assert.equal(state().protocol,'static-v1');
  assert.equal(state().player_id,'');
  function pulse(){for(const timer of [...timers.values()])if(timer.ms===500)timer.fn();}
  context.ROLE={id:456,heroId:789};pulse();assert.equal(state().player_id,'456');
  context.ROLE={heroId:789};pulse();assert.equal(state().player_id,'789');
  context.ROLE={};pulse();assert.equal(state().player_id,'');
  command('install','install',{id:'resident'});await tick();assert.equal(response().value.resident_id,'resident');
  command('one','call',{id:'resident',op:'count'});await tick();
  assert.equal(response().value.value,42);assert.equal(context.executed,1);
  await tick();assert.equal(context.executed,1,'same command never executes twice');
  command('bad','call',{id:'resident',op:'count'},{token:'wrong'});await tick();assert.equal(context.executed,1);
  command('expired','call',{id:'resident',op:'count'},{deadline:0});await tick();assert.equal(context.executed,1);assert.equal(response().ok,false);
  command('wrong-session','call',{id:'other',op:'count'});await tick();assert.equal(context.executed,1);assert.equal(response().value.status,'uncertain');
  command('async','damage-inject');await tick();assert.equal(response().value.enabled,true);assert.equal(context.damageEnabled,true);
  command('dynamic','ping',{}, {expression:'1+1'});await tick();assert.equal(response().ok,false);
  command('unknown','unknown');await tick();assert.equal(response().ok,false);
  command('still-works','ping');await tick();assert.equal(response().value,2);
  context.__e0e1DouyinBridge.stop();assert.equal(timers.size,0);
  console.log('PASS: eval/Function disabled; static resident dispatch, async script enable, identity/replay/expiry checks, dynamic-source rejection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
