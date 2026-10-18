const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const app=fs.readFileSync(path.join(__dirname,'../server/web/app.js'),'utf8');
class Element{constructor(){this.children=[];this.events={};this.checked=false;}append(...nodes){this.children.push(...nodes);}replaceChildren(){this.children=[];}addEventListener(name,fn){this.events[name]=fn;}setAttribute(k,v){this[k]=v;}reset(){}}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const rows=[],downloads=[],messages=[];
const api={players:{list:async()=>rows,create:async p=>rows.push({...p,enabled:true}),downloadPackage:async ids=>downloads.push(ids.slice())}};
const context={api,cell:text=>{const el=new Element();el.textContent=text;return el;},document:{getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>get('players-body').children.map(tr=>tr.children[0].children[0])},toast:(...a)=>messages.push(a),FormData:class{constructor(form){this.data=form.data;}get(k){return this.data[k]||'';}},confirm:()=>true};
vm.runInNewContext(app.slice(app.indexOf('const selectedPlayers ='),app.indexOf('// ── 版本发布')),context);
(async()=>{
 await context.refreshPlayers();assert(get('download-selected').disabled);
 async function add(id){await get('player-form').events.submit({preventDefault(){},target:{data:{player_id:id},reset(){}}});}
 await add('1001');await add('1002');assert.equal(downloads.length,0,'adding only selects, never auto-downloads');
 assert.equal(get('players-body').children.length,2);assert(!get('download-selected').disabled);
 await get('download-selected').events.click();assert.deepEqual(Array.from(downloads[0]),['1001','1002']);
 rows[1].enabled=false;await context.refreshPlayers();await get('download-selected').events.click();assert.deepEqual(Array.from(downloads[1]),['1001']);
 const all=get('select-all-players');all.events.change({target:{checked:false}});assert(get('download-selected').disabled);
 all.events.change({target:{checked:true}});assert(!get('download-selected').disabled);
 api.players.downloadPackage=async()=>{throw Error('没有生效版本');};await get('download-selected').events.click();assert(messages.some(row=>row[0]==='没有生效版本'&&row[1]));assert(!get('download-selected').disabled);
 console.log('PASS add-and-select workflow, combined download, disabled-account pruning, select-all and failed-download recovery');
 const calls=[],revoked=[];
 const source=fs.readFileSync(path.join(__dirname,'../server/web/api.js'),'utf8').replaceAll('export ','');
 const ctx={localStorage:{getItem:()=> 'jwt'},fetch:async(url,options)=>{calls.push({url,options});return {ok:true,blob:async()=>({})};},document:{createElement:()=>({click(){}})},URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL:url=>revoked.push(url)},setTimeout:fn=>fn(),Headers};
 vm.runInNewContext(source+';globalThis.playersApi=players;',ctx);
 await ctx.playersApi.downloadPackage(['1001','1002']);assert.equal(calls[0].url,'/api/players/package');assert.equal(calls[0].options.method,'POST');assert.deepEqual(JSON.parse(calls[0].options.body),{player_ids:['1001','1002']});assert.equal(revoked.length,1);
 await ctx.playersApi.downloadPackage('1001');assert.equal(calls[1].options.method,'GET');
 await ctx.downloadClientCertificates();assert.equal(calls.at(-1).url,'/api/certificates/client.zip');assert.equal(calls.at(-1).options.headers.get('Authorization'),'Bearer jwt');assert.equal(revoked.length,3);
 console.log('PASS authenticated binary certificate download and object URL cleanup');
 console.log('PASS selected IDs sent as authenticated POST JSON, legacy single-player GET retained and Blob URLs released');
})().catch(e=>{console.error(e);process.exitCode=1;});
