const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/desire_report/template.py'),'utf8');
let script=source.slice(source.indexOf('<script>')+8,source.indexOf('</script>',source.indexOf('<script>')));
const records=[{batch:1,kind:1,quality:1,ok:false,ts:'2026-10-21'},{batch:1,kind:1,quality:1,ok:true,ts:'2026-10-21'},{batch:2,kind:2,quality:2,ok:false,ts:'2026-10-22'}];
const payload={records,batches:[{batch:1},{batch:2}],kinds:[{id:1,name:'A'},{id:2,name:'B'}],qualities:[{id:1,name:'Q1'},{id:2,name:'Q2'}]};
class Element{constructor(id){this.id=id;this.children=[];this.options=this.children;this.handlers={};this.value='';this.style={};}set innerHTML(v){this.children.length=0;}appendChild(e){this.children.push(e);}addEventListener(e,f){this.handlers[e]=f;}click(){if(this.handlers.click)this.handlers.click();}}
const nodes={};const get=id=>nodes[id]||(nodes[id]=new Element(id));get('payload').textContent=JSON.stringify(payload);
const tables={},hist=[];
script=script.replace('  init();',`  renderTable=function(host,rows){tables[host.id]=JSON.parse(JSON.stringify(rows));}; drawHistogram=function(rows){hist.push(Array.from(rows,r=>r.batch));}; init();`);
vm.runInNewContext(script,{document:{getElementById:get,createElement:()=>new Element()},tables,hist});
assert.equal(tables['table-total'][0].n,3);
get('date-from').value='2026-10-21';get('date-to').value='2026-10-22';get('date-apply').click();
get('batch').options[0].selected=true;get('batch').handlers.change();
assert.equal(tables['table-total'][0].n,2);assert.equal(tables['table-kind'].length,1);assert.equal(tables['table-quality'].length,1);assert.equal(tables['table-date'].length,1);assert.equal(JSON.stringify(hist.at(-1)),'[1,1]');
get('p-input').handlers.input();assert.equal(JSON.stringify(hist.at(-1)),'[1,1]');
get('batch').options[0].selected=false;get('batch').handlers.change();assert.equal(tables['table-total'][0].n,3);
console.log('PASS batch selection scopes overview, kind, quality, dates, histogram and theory input; clear restores all');

get('batch').options[0].selected=true;get('batch').handlers.change();
get('attempt-limit').value='1';get('attempt-limit').handlers.input();
assert.equal(tables['table-total'][0].n,1);assert.equal(tables['table-total'][0].ok,0);assert.equal(JSON.stringify(hist.at(-1)),'[1]');assert.equal(tables['table-date'][0].n,1);
get('batch').options[0].selected=false;get('batch').options[1].selected=true;get('batch').handlers.change();assert.equal(tables['table-total'][0].n,1);assert.equal(JSON.stringify(hist.at(-1)),'[2]');
get('attempt-limit').value='999';get('attempt-limit').handlers.input();assert.equal(tables['table-total'][0].n,1);
get('attempt-limit').value='';get('attempt-limit').handlers.input();get('batch').options[1].selected=false;get('batch').handlers.change();assert.equal(tables['table-total'][0].n,3);
console.log('PASS first N applies after batch filter, updates all views, larger limit and empty reset');
