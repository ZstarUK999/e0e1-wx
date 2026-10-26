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
let next=0,sequence=0,responseLimit=Infinity;
const hides=new Set(),shows=new Set(),screen=[];
let pausedGame=true,pausedDirector=true,resumeCount=0;
const cocos={game:{isPaused:()=>pausedGame,resume(){pausedGame=false;resumeCount++;},pause(){pausedGame=true;}},
 director:{isPaused:()=>pausedDirector,resume(){pausedDirector=false;resumeCount++;},pause(){pausedDirector=true;}}};
const context=vm.createContext({eval:undefined,Function:undefined,
  tt:{env:{USER_DATA_PATH:'ttfile://user'},
 onHide(fn){hides.add(fn);},onShow(fn){shows.add(fn);},offHide(fn){hides.delete(fn);},offShow(fn){shows.delete(fn);},
 setKeepScreenOn(args){screen.push(args.keepScreenOn);if(args.success)args.success();},getFileSystemManager(){return{
    readFileSync(p){if(!files.has(p))throw Error('missing');return files.get(p);},unlinkSync(p){files.delete(p);},writeFileSync(p,v){if(p===base+'response.json' && Buffer.byteLength(v)>responseLimit)throw Error('user dir saved file size limit exceeded');files.set(p,v);}
  };}},UIManager:{ins:{findOpen(){return true;}}},ROLE:{},System:{async import(){return cocos;}},CommonUICfgId:{MainUI:1},
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
  // Simulate a nearly full platform directory and an old oversized receipt.
  responseLimit=8000;
  const large='中文😀'.repeat(30000);
  context.damageCurveJson=()=>large;
  command('large','damage-snapshot');await tick();
  let joined='',count=0;
  while(true){
    const part=response();assert.equal(part.chunked,true);assert.equal(part.index,count++);
    joined+=part.data;
    files.set(base+'response-ack.json',JSON.stringify({token:'wrong',runtime:state().runtime,id:'large',index:part.index}));
    await tick();assert.equal(response().index,part.index,'wrong token cannot advance');
    files.set(base+'response-ack.json',JSON.stringify({token:'fixture-token',runtime:state().runtime,id:'large',index:part.index}));
    await tick();if(part.final)break;
  }
  assert.equal(JSON.parse(joined).value,large);assert.ok(count>1);
  assert.equal(files.has(base+'response.json'),false,'ack releases platform file');
  assert.equal(context.executed,1,'transfer never replays game operations');
  responseLimit=Infinity;
  context.damageCurveJson=cursor=>({cursor});
  command('damage-delta','damage-snapshot',{cursor:{stream:7,includeCatalog:false,self:{instanceId:1,events:10,hits:3}}});await tick();
  assert.deepEqual(JSON.parse(JSON.stringify(response().value.cursor)),{stream:7,includeCatalog:false,self:{instanceId:1,events:10,hits:3}});
  context.tt.setKeepScreenOn({keepScreenOn:false});
  files.set(base+'lease.json',JSON.stringify({token:'fixture-token',runtime:state().runtime,resident:'resident',at:Date.now()}));
  pulse();for(let i=0;i<12;i++)await Promise.resolve();
  assert.equal(state().keep_alive.active,true);assert.equal(resumeCount,0,'foreground pause is preserved');
  for(const fn of hides)fn();pulse();assert.equal(resumeCount,2);assert.equal(pausedGame,false);assert.equal(pausedDirector,false);
  assert.equal(context.executed,1,'background protection never replays game actions');
  files.set(base+'lease.json',JSON.stringify({token:'fixture-token',runtime:state().runtime,resident:'resident',at:Date.now()-20000}));
  pulse();assert.equal(state().keep_alive.active,false);assert.equal(pausedGame,true);assert.equal(pausedDirector,true);
  assert.equal(screen.at(-1),false,'restore the observed native screen setting');
  files.set(base+'lease.json',JSON.stringify({token:'wrong',runtime:state().runtime,resident:'resident',at:Date.now()}));pulse();assert.equal(resumeCount,2);
  assert.equal(hides.size,1);assert.equal(shows.size,1);
  // Independent exit mailbox must still be handled while a command is hung.
  let marksStopped=0,overlayStopped=0;
  context.e0e1Season={stop(){marksStopped++;return {ok:true};}};
  context.treasureMapOverlayOff=()=>{overlayStopped++;};
  context.__e0e1PluginRuntime.dispatch=()=>new Promise(()=>{});
  command('hung','call',{id:'resident',op:'count'});await tick();assert.equal(state().busy,true);
  // Overlay control is independent of the hung command queue as well.
  let overlayUpdates=0,automationDestroyed=0;
  context.__e0e1AutomationOverlay={
    update(payload){overlayUpdates++;return Promise.resolve(payload);},
    snapshot(){return {run_id:'run',active:true,stop_requested:true};},
    destroy(){automationDestroyed++;}
  };
  for(const patch of [{token:'other'},{runtime:'old'},{resident:'someone-else'}]){
    files.set(base+'automation.json',JSON.stringify({token:'fixture-token',runtime:state().runtime,resident:'resident',at:Date.now(),payload:{active:true},...patch}));pulse();
    assert.equal(overlayUpdates,0);
  }
  files.set(base+'automation.json',JSON.stringify({token:'fixture-token',runtime:state().runtime,resident:'resident',at:Date.now(),payload:{active:true}}));pulse();
  await Promise.resolve(); // Overlay updates also pass through the lazy loader's promise.
  assert.equal(overlayUpdates,1);assert.equal(state().automation.stop_requested,true);
  for(const patch of [{token:'other'},{runtime:'old'},{resident:'someone-else'}]){
    files.set(base+'shutdown.json',JSON.stringify({token:'fixture-token',runtime:state().runtime,resident:'resident',...patch}));pulse();assert.equal(marksStopped,0);
  }
  files.set(base+'shutdown.json',JSON.stringify({token:'fixture-token',runtime:state().runtime,resident:'resident'}));pulse();
  for(let i=0;i<30;i++)await Promise.resolve();
  assert.equal(context.__e0e1PluginRuntime.stopped,true);assert.equal(automationDestroyed,1);assert.equal(marksStopped,1);assert.equal(overlayStopped,1);
  assert.equal(JSON.parse(files.get(base+'persistent.json')).damage,false);
  pulse();assert.equal(marksStopped,1,'exit cleanup is idempotent');assert.equal(context.executed,1,'unknown action not replayed');
  console.log('PASS: instance-bound exit signal stops background features even while command queue is blocked, without replaying actions.');
  context.__e0e1DouyinBridge.stop();assert.equal(timers.size,0);assert.equal(hides.size,0);assert.equal(shows.size,0);
  console.log('PASS: Douyin background keepalive requires fresh matching lease, preserves foreground pause, restores on expiry and never replays actions.');
  // Test both actual API outcomes; mocks do not establish real device support.
  for (const writable of [true,false]) {
    files.clear();
    files.set(base+'storage-probe-request.json',JSON.stringify({token:'fixture-token',id:'probe',at:Date.now()}));
    context.tt.getFileSystemManager=()=>({
      readFileSync(p){if(!files.has(p))throw Error('missing');return files.get(p);},
      writeFileSync(p,v){if(p.startsWith('ttfile://temp/')&&!writable)throw Error('permission denied');files.set(p,v);},
      unlinkSync(p){files.delete(p);}
    });
    context.__e0e1DouyinBridge=null;
    vm.runInContext(source,context);
    const result=JSON.parse(files.get(base+'storage-probe-result.json'));
    assert.equal(result.write,writable);assert.equal(result.read,writable);assert.equal(result.removed,writable);
    assert.equal([...files.keys()].some(p=>p.startsWith('ttfile://temp/')),false);
    context.__e0e1DouyinBridge.stop();
  }
  console.log('PASS: eval/Function disabled; static resident dispatch, async script enable, identity/replay/expiry checks, dynamic-source rejection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
