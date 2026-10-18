const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
async function load(file,tail){return vm.runInNewContext('(async()=>{'+fs.readFileSync(path.join(root,'tools/js',file),'utf8')+';'+tail+'})()',{console:{log(){}},Map,Date,Promise,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},__e0e1RegisterRuntimeToggle(){}});}
const table=rows=>({list:rows,getById:id=>rows.find(r=>r.id===Number(id))});
(async()=>{
 const cfg={SkillCfg:table([{id:402083,name:'三尸-痴-天书斗法—lv7',_passive:[402083]},{id:10,name:'普攻',skillFunctionType:1,bookId:100},{id:20,name:'天书',skillFunctionType:4,bookId:200},{id:20100402,name:'水幡',skillFunctionType:4}]),PassiveSkillCfg:table([{id:402083,_effects:['PLAYER_BUFF(402083)']}]),BuffCfg:table([{id:402083}]),DesireCfg:table([{id:6060726,skill:[402083],itemId:{name:'痴尸舍利'}}]),SkillBookCfg:table([{id:100,name:'主角普攻'},{id:200,name:'测试天书'}]),SeasonWarRestraintCfg:table([{id:4,name:'水敛幡',pveSkill:[20100402]}])};
 const api=await load('damage_curve_probe.js',`return {configure(c){E0E1_CFG=c;},label:e0e1BuffLabel,origins:e0e1BuffOrigins,parts:e0e1FactorParts,category:e0e1Classify,state:e0e1NewState,handler:e0e1MakeHandler,collect:e0e1CollectSide};`);api.configure(cfg);
 assert.equal(api.origins(402083)[0].origin,'三尸 · 痴尸舍利');
 const label=api.label({cfg:{id:402083},piles:4,skillContext:{shareData:{skillCfg:{id:10,name:'落雷普攻'}}}});
 assert.match(label,/配置来源：三尸 · 痴尸舍利/);assert.match(label,/关联技能：落雷普攻/);assert.equal(api.category(20100402).cat,'flag');
 const world={options:{battleData:{type:26}},battleTime:{battleTime:2}};
 const state=api.state(world,'self',false),handler=api.handler(state),source={uuid:1},target={compBoss:{}};
 handler(source,10,10,target,false);handler(source,20,20,target,false);
 const report=api.collect(state);assert.equal(report.totalDamage,30);assert.equal(report.books.length,1);assert.equal(report.books[0].bookId,200);
 for(const [element,expected]of [[3,228],[4,227]]){
  cfg.SkillCfg.list.push({id:30+element,bookId:300,skillFunctionType:3,elementalType:element});cfg.SkillBookCfg.list.push({id:300,type:1});
  const inputs={self:{116:.1,[expected]:.2},target:{120:0,[expected+4]:0}};
  const ctx={skillId:30+element,skillContext:{shareData:{skillCfg:cfg.SkillCfg.getById(30+element)}},target:{},battleWorld:world};
  const parts=api.parts(ctx,inputs,{skillType:.3},{});assert(parts.skillType.some(p=>p.key===expected));
 }
 const dump=await load('player_info_dump.js',`return {configure(c){e0e1CfgModule=c;},parse:e0e1ParseDesirePlan};`);
 dump.configure({DesireCfg:table([{id:1,itemId:{name:'痴尸舍利',desc:'每次释放天书时，获得2.25%pvp增伤，最多获得8次'},attr:{},skill:[402083]},{id:2,itemId:{name:'常驻'},attr:{117:350},skill:[]}])});
 const lines=dump.parse(new Map([[1,1],[2,2]]),'当前');assert.match(lines.join('\n'),/PVP增伤 3.5%/);assert.match(lines.join('\n'),/按触发条件与实际层数/);
 const template=fs.readFileSync(path.join(root,'package/plugin_manager/damage_report/template.py'),'utf8');
 const helper=template.slice(template.indexOf('  function renderBookComparison'),template.indexOf('  function renderPlayers'));
 function el(tag,cls,text){return {tag,className:cls||'',textContent:text||'',children:[],appendChild(child){this.children.push(child);}};}
 const book={bookId:1,bookName:'十绝阵'},make=(branchId,level,pathName='主阶')=>({...book,branchId,branchName:'分支'+branchId,level,pathName});
 const player={awakenings:[make(1,3),make(2,1),make(3,2),make(4,4,'分阶'),make(5,1,'分阶')]};
 const opponent={awakenings:[make(1,2),make(2,2),make(3,2),make(4,3,'分阶')]};
 const card=el('div');vm.runInNewContext(helper+';renderBookComparison(card,player,opponent);',{card,player,opponent,el});
 const details=card.children[1];assert.equal(details.tag,'details');assert(!details.open);const main=details.children[0].children[1].children;
 assert(main.every(n=>n.className==='book-level'));assert.equal(details.children[0].children[0].className,'book-lower');
 assert.equal(details.children[1].children[0].children[0].className,'book-level');assert.equal(details.children[1].children[1].children[0].className,'book-level');
 console.log('PASS buff grant versus attack context, true-book-only totals, flag roots, wind/earth attributes, conditional desires and collapsed red/green/equal/missing comparisons');
})().catch(e=>{console.error(e);process.exitCode=1;});
