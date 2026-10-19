const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/douyin_bridge.js'),'utf8')
.replace('__BRIDGE_TOKEN__','"token"').replace('__BRIDGE_BUILD__','"build"').replace('__BRIDGE_STATIC_SCRIPTS__','{resident:async()=>({resident_id:"test"})}');
async function test(video,reserve=false){
 const files=new Map(),timers=[],root='ttfile://user',prefix=root+'/e0e1-plugin-',cache=root+'/gamecaches/';
 const entries=new Map(),quota=2*1024*1024;
 const indexed=cache+'resources/keep.bin'; files.set(indexed,'z'.repeat(100000));entries.set('https://game/keep.bin',{url:indexed,lastTime:1});
 const orphan=cache+'old.bin';files.set(orphan,'o'.repeat(49000));
 const movie=cache+'movie.mp4';if(video){files.set(movie,'m'.repeat(200000));entries.set('https://game/movie.mp4',{url:movie,lastTime:1});}
 let deleted=[];
 function used(){return [...files.values()].reduce((n,s)=>n+Buffer.byteLength(s),0);}
 const manager={cacheQueue:{},cachedFiles:{forEach(fn){entries.forEach((v,k)=>fn(v,k));}},removeCache(key){deleted.push(key);entries.delete(key);files.set(cache+'cacheList.json',JSON.stringify([...entries]));}};
 const api={readFileSync(p){if(!files.has(p))throw Error('missing');return files.get(p);},
 writeFileSync(p,s){if(used()-Buffer.byteLength(files.get(p)||'')+Buffer.byteLength(s)>quota)throw Error('user dir saved file size limit exceeded');files.set(p,s);},
 unlinkSync(p){if(!files.delete(p))throw Error('missing');},
 statSync(p){const isFile=files.has(p);return{stats:{isFile:()=>isFile,isDirectory:()=>!isFile,size:isFile?Buffer.byteLength(files.get(p)):0,lastModifiedTime:Date.now()-120000}};},
 readdirSync(p){return [...new Set([...files.keys()].filter(k=>k.startsWith(p+'/')).map(k=>k.slice(p.length+1).split('/')[0]))];}};
 if(!reserve)files.set(prefix+'storage-stress-request.json',JSON.stringify({token:'token',id:'stress',at:Date.now()}));
 else {
   files.set(prefix+'reserve-old-session.bin','r'.repeat(100));
   files.set(cache+'indexed-padding.bin','p'.repeat(quota-used()-1500));
   entries.set('https://game/padding.bin',{url:cache+'indexed-padding.bin',lastTime:1});
 }
 const context=vm.createContext({tt:{env:{USER_DATA_PATH:root},getFileSystemManager:()=>api},UIManager:{},System:{import:async()=>({assetManager:{cacheManager:manager}})},ROLE:{},
 setInterval(fn,ms){timers.push({fn,ms});return timers.length;},clearInterval(){},setTimeout(fn){setImmediate(fn);}});
 vm.runInContext(source,context);
 if(reserve){
   const state=()=>JSON.parse(files.get(prefix+'state.json'));
   const command=(id,seq,action)=>files.set(prefix+'command.json',JSON.stringify({token:'token',runtime:state().runtime,id,sequence:seq,action,args:{id:'test'},deadline:Date.now()+30000}));
   async function tick(){timers.find(t=>t.ms===100).fn();for(let i=0;i<60;i++)await Promise.resolve();}
   command('install',1,'install');await tick();
   assert.equal(state().storage_reserve.bytes,32768);
   assert.equal(files.has(prefix+'reserve-old-session.bin'),false);
   assert.equal(deleted.length,1,'mount cleans video when reserve allocation fails');
   files.set(cache+'new-padding.bin','p'.repeat(quota-used()-1000));
   entries.set('https://game/new-padding.bin',{url:cache+'new-padding.bin',lastTime:1});
   context.damageCurveDebug=()=>('x'.repeat(8192));
   command('report',2,'damage-debug');await tick();
   assert.equal(JSON.parse(files.get(prefix+'response.json')).value.length,8192);
   assert.equal(state().storage_reserve.released,1);
   assert.equal(state().storage_reserve.bytes,0);
   assert.equal(deleted.length,1,'release reserve before deleting further game caches');
   assert.equal(files.has(orphan),true);
   context.__e0e1DouyinBridge.stop();
   assert.equal([...files.keys()].some(k=>/e0e1-plugin-reserve-/.test(k)),false);
   return;
 }
 timers.find(t=>t.ms===250).fn();
 for(let i=0;i<2000&&!files.has(prefix+'storage-stress-result.json');i++)await new Promise(r=>setImmediate(r));
 const report=JSON.parse(files.get(prefix+'storage-stress-result.json'));
 assert.equal(report.quota_reached,true);assert.equal(report.recovered,true);assert.equal(report.check_written,true);assert.equal(report.remaining_files.length,0);
 assert.equal([...files.keys()].some(k=>k.includes('e0e1-storage-stress-')),false);
 assert.equal(files.has(indexed),true);
 if(video){assert.deepEqual(deleted,['https://game/movie.mp4']);assert.equal(files.has(orphan),true,'video first; do not delete orphan unnecessarily');}
 else {assert.equal(files.has(orphan),false);assert.equal(report.reclaimed_bytes,49000);}
}
(async()=>{await test(true);await test(false);await test(true,true);console.log('PASS: quota saturation, video priority, 49KB orphan recovery, indexed data preservation and filler cleanup');})().catch(e=>{console.error(e);process.exitCode=1;});
