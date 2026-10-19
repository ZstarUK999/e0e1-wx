const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/douyin_bridge.js'),'utf8')
.replace('__BRIDGE_TOKEN__','"t"').replace('__BRIDGE_BUILD__','"b"').replace('__BRIDGE_STATIC_SCRIPTS__',`{
 resident:async function(id){globalThis.__e0e1PluginRuntime={id,stopped:false,pending:false,async dispatch(op){if(op==='stop')this.stopped=true;return {status:'ok',value:op};}};return {resident_id:id};},
 damageStop:async function(){return {ok:true};}}`);
const files=new Map(),timers=new Map(),prefix='ttfile://user/e0e1-plugin-';let timerId=0,sequence=0;
const context=vm.createContext({tt:{env:{USER_DATA_PATH:'ttfile://user'},getFileSystemManager:()=>({
readFileSync(p){if(!files.has(p))throw Error('missing');return files.get(p);},writeFileSync(p,s){files.set(p,s);},unlinkSync(p){files.delete(p);},readdirSync(){return [];}})},
UIManager:{ins:{findOpen:()=>true}},CommonUICfgId:{MainUI:1},ROLE:{},System:{import:async()=>({})},
setInterval(fn,ms){const id=++timerId;timers.set(id,{fn,ms});return id;},clearInterval(id){timers.delete(id);}});
function state(){return JSON.parse(files.get(prefix+'state.json'));}
async function flush(){for(let i=0;i<50;i++)await Promise.resolve();}
async function pulse(){for(const {fn,ms} of timers.values())if(ms===500)fn();await flush();}
async function command(id,action,args={}){
files.set(prefix+'command.json',JSON.stringify({token:'t',runtime:state().runtime,id,sequence:++sequence,action,args,deadline:Date.now()+30000}));
for(const {fn,ms} of timers.values())if(ms===100)fn();await flush();return JSON.parse(files.get(prefix+'response.json'));}
(async()=>{
vm.runInContext(source,context);
assert.equal((await command('mount','install',{id:'old'})).value.resident_id,'old');
files.set(prefix+'shutdown.json',JSON.stringify({token:'t',runtime:state().runtime,resident:'old'}));await pulse();
assert.equal(state().phase,'stopped');assert.equal(state().reusable,true);
assert.equal((await command('cleanup','call',{id:'old',op:'stop'})).ok,true,'stop remains executable during shutdown');
context.__e0e1EnergyGuard={pending:true};await pulse();assert.equal(state().reusable,false);
assert.equal((await command('reject','install',{id:'new'})).ok,false);
context.__e0e1EnergyGuard.pending=false;await pulse();assert.equal(state().reusable,true);
assert.equal((await command('takeover','install',{id:'new'})).value.resident_id,'new');
await pulse();assert.equal(state().phase,'running');assert.equal(state().resident,'new');
assert.equal((await command('works','call',{id:'new',op:'inspect'})).value.value,'inspect');
context.__e0e1DouyinBridge.stop();assert.equal(timers.size,0);
console.log('PASS: stopped instance handover, reject pending operations, cleanup acknowledgements and stale shutdown isolation');
})().catch(e=>{console.error(e);process.exitCode=1;});
