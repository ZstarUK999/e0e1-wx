const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test'),path=require('node:path');
function fixture(){
 const messages=[],hooks=[];
 const context={Process:{platform:'windows',arch:'x64',id:123,findModuleByName:()=>null},
  send:p=>messages.push(p),console:{log(){},error(){}},Interceptor:{attach:(address,callbacks)=>hooks.push(callbacks)}};
 let source=fs.readFileSync(path.join(__dirname,'hook.js'),'utf8');
 source=source.replace(/main\(\);\s*$/,'');
 vm.runInNewContext(source+'\nglobalThis.api={scene:winRewriteScene,url:winWriteWebSocketUrl,install:winPatchLoadStart,main};',context);
 return {api:context.api,messages,hooks,events:()=>messages.filter(p=>p && p.type==='e0e1-hook-diagnostic')};
}
test('scene diagnostics distinguish accepted launches and skipped whitelist entries',()=>{
 const f=fixture(),writes=[];
 assert.equal(f.api.scene({readInt:()=>1005,writeInt:n=>writes.push(n)}),true);
 assert.equal(f.api.scene({readInt:()=>99999,writeInt:n=>writes.push(n)}),false);
 assert.deepEqual(writes,[1101]);
 assert.deepEqual(f.events().map(e=>[e.event,e.accepted]),[['scene',true],['scene-rewritten',undefined],['scene',false]]);
 assert.equal(f.events().at(-1).level,'warning');
});
for(const long of [false,true])test('websocket write is reported after writing '+(long?'heap':'inline')+' string',()=>{
 const f=fixture(),writes=[];
 const buffer={writeUtf8String:s=>writes.push(s)};
 f.api.url({writeUtf8String:buffer.writeUtf8String,readPointer:()=>buffer,
  add:n=>({readS8:()=>long?-1:0,writeU64:()=>{},writeU8:()=>{}})});
 assert.deepEqual(writes,['ws://localhost:9421']);
 assert.equal(f.events()[0].event,'websocket-written');
 assert.equal(f.events()[0].url,'ws://localhost:9421');
});
test('load entry and pointer failure are both logged without changing exception handling',()=>{
 const f=fixture();
 f.api.install({add:()=>({})},{LoadStartHookOffset:'0x10',SceneOffsets:[1,2]});
 assert.equal(f.events()[0].event,'load-hook-installed');
 f.hooks[0].onEnter.call({context:{rdx:1,rcx:{add(){throw Error('bad pointer');}}}});
 assert.deepEqual(f.events().slice(1).map(e=>e.event),['load-enter','load-error']);
 assert.match(f.events().at(-1).message,/bad pointer/);
});
test('missing module is an explicit install error instead of a silent loaded script',()=>{
 const f=fixture();f.api.main();
 assert.equal(f.events().at(-1).event,'install-error');
 assert.equal(f.events().at(-1).level,'error');
});
