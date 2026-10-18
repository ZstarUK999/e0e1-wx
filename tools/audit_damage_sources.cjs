const fs=require('fs'),vm=require('vm'),path=require('path');
if(!process.argv[2]){console.error('Usage: node tools/audit_damage_sources.cjs <decoded-config.json> [output.json]');process.exit(2);}
const output=process.argv[3] || 'damage-source-audit.json';
const cfgRaw=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
function rows(v){if(!v||typeof v!=='object')return [];if('id' in v)return [v];return Object.values(v).flatMap(rows);}
const cfg={};for(const [k,v]of Object.entries(cfgRaw)){const list=rows(v),map=new Map(list.map(r=>[r.id,r]));cfg[k]={list,getById:id=>map.get(Number(id))};}
for(const r of cfg.DesireCfg.list)r.itemId=cfg.ItemCfg.getById(r.c_item_itemId);
const src=fs.readFileSync(path.join(__dirname,'js/damage_curve_probe.js'),'utf8');
(async()=>{const api=await vm.runInNewContext('(async()=>{'+src+';return {set(c){E0E1_CFG=c;},classify:e0e1Classify,buff:e0e1BuffOrigins,meta:e0e1AttrMeta};})()',{console:{log(){}},Map,Date,Promise,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},__e0e1RegisterRuntimeToggle(){}});api.set(cfg);
const cats={},missingBooks=[],nonBookSkillLinks=[];for(const row of cfg.SkillCfg.list){const c=api.classify(row.id);cats[c.cat]=(cats[c.cat]||0)+1;if(c.cat==='book'&&!cfg.SkillBookCfg.getById(c.bookId))missingBooks.push({id:row.id,name:row.name,sft:row.skillFunctionType,book:row.bookId,source:row.sourceBookId});if(c.bookId&&c.cat!=='book')nonBookSkillLinks.push({id:row.id,name:row.name,cat:c.cat,book:c.bookId});}
const result={counts:Object.fromEntries(Object.entries(cfg).map(([k,v])=>[k,v.list.length])),cats,missingBooks,nonBookSkillLinks};result.buffSources={};for(const buff of cfg.BuffCfg.list)result.buffSources[buff.id]=api.buff(buff.id);result.buffResolved=Object.values(result.buffSources).filter(a=>a.length).length;console.log('buff coverage',result.buffResolved,'/',cfg.BuffCfg.list.length,'402083',JSON.stringify(result.buffSources[402083]));fs.writeFileSync(output,JSON.stringify(result,null,2));console.log(JSON.stringify({cats,missingBooks:missingBooks.length,examples:missingBooks.slice(0,8),nonBookSkillLinks:nonBookSkillLinks.slice(0,8)}));})();
