const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const template=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/damage_report/template.py'),'utf8');
const script=template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];new vm.Script(script);
function node(text=''){return {textContent:text,children:[],style:{setProperty(k,v){this[k]=v;}},dataset:{},hidden:false,checked:true,value:'',open:false,
 appendChild(n){this.children.push(n);n.parentNode=this;return n;},removeChild(n){this.children.splice(this.children.indexOf(n),1);},setAttribute(k,v){this[k]=v;},
 get firstChild(){return this.children[0];},get selectedOptions(){return this.children.filter(n=>n.value===this.value);},getBoundingClientRect(){return {left:0,top:0,width:1000,height:300};}};}
function text(n){return (n.textContent||'')+' '+n.children.map(text).join(' ');}
const nodes=new Map(),draws=[];
const document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}};
const make=(sec,group,damage,type,skillId,hits=1)=>({sec,group,skillId,hits,boss:true,name:group==='book'?'真实天书':'实际普攻',firstT:sec+.1,lastT:sec+.2,sourceRef:0,
 factors:{attack:100,coefficient:2,damage,element:1,type,crit:1,pvp:1,final:1},inputs:{self:{115:.5,708:.3},target:{115:0,708:0}},
 parts:{type:[],skillType:[{side:'self',key:115,value:.5}],attackBonus:[{side:'self',key:708,value:.3}]}});
const ownBook=make(1,'book',1.6,1.5,20,2),otherBook=make(1,'book',1.2,1.2,20);
const DATA={pvp:{attrMeta:[{key:115,label:'天书增伤',percent:true},{key:708,label:'普攻增伤',percent:true}]},
 factorRows:[ownBook,make(1,'attack',1.4,1.8,10),make(3,'attack',1.5,1.8,10)],
 factorSources:[{self:{115:[{label:'天书Buff',value:.5}]}}],
 other:{factorRows:[otherBook,make(2,'book',1.3,1.2,20)],factorSources:[{self:{115:[{label:'敌方Buff',value:.2}]}}]}};
ownBook.factors.settlement=.25;ownBook.settlement={inputDamage:100,actualDamage:25,shieldBefore:75,shieldAfter:0};
ownBook.inputs.self[117]=.8;ownBook.inputs.target[118]=.9;ownBook.context={opponentPvpRed:.3};ownBook.factors.pvp=1.5;
otherBook.inputs.self[117]=.4;otherBook.inputs.target[118]=.8;otherBook.context={opponentPvpRed:.2};otherBook.factors.pvp=1.2;
for(const [value,label] of [['book','天书伤害'],['attack','普攻伤害'],['card','符咒伤害'],['skill','其他技能伤害']]){const option=node(label);option.value=value;document.getElementById('formula-type').appendChild(option);}
const context={DATA,document,SELF_SLOT:1,OTHER_SLOT:2,el:(tag,cls,t)=>{const n=node(t);n.className=cls||'';return n;},
 fmt:String,pctText:n=>String(Math.round(n*10000)/100),attrMetaOf:(p,key)=>p.attrMeta.find(m=>m.key===key)||{label:'属性'+key},fmtAttr:(m,v)=>String(v),
 drawLine:(svg,tip,series,opts)=>draws.push({series,opts}),renderFactorHistory(){},
 FACTOR_META:[['attack','攻击区',[1,2,3,19,20],[]],['coefficient','系数',[],[]],['damage','增伤',[104],[105]],['type','类型',[],[]]]};
const helpers=script.slice(script.indexOf('  function bonusValue'),script.indexOf('  function bonusComparisonRows'));
const explorer=script.slice(script.indexOf('  var formulaState='),script.indexOf('  function renderFlags'));
const buffHelpers=script.slice(script.indexOf('  function bossBuffLines'),script.indexOf('  function renderBossBuffs'));
vm.runInNewContext(helpers+buffHelpers+explorer+';renderAttrs();',context);
assert.equal(nodes.get('formula-comparison').hidden,true);
assert.equal(nodes.get('factor-details').open,false);
assert.equal(draws.at(-1).series[0].values[1],1.6);assert.equal(draws.at(-1).series[0].values[2],null);
assert.equal(draws.at(-1).opts.connectGaps,true);assert.equal(draws.at(-1).series[0].values[0],null);assert.match(text(nodes.get('formula-chart-note')),/我方起始记录 1s/);assert.equal(draws.at(-1).opts.gaps,true);assert.equal(typeof draws.at(-1).opts.onSelect,'function');
draws.at(-1).opts.onSelect(draws.at(-1).opts.xLabels.indexOf(1));
assert.equal(nodes.get('formula-comparison').hidden,false);assert.match(text(nodes.get('bonus-summary')),/类型增伤区/);
const rows=nodes.get('bonus-summary').children[0].children;
assert(rows.some(r=>r.children.some(c=>c.children.some(n=>n.className && n.className.includes('bonus-winner')))));
assert(rows.some(r=>r.children.some(c=>c.children.some(n=>n.className && n.className.includes('bonus-lower')))));
const typeDrill=rows.find(r=>r.children[0] && r.children[0].children[0] && r.children[0].children[0].id==='formula-parts-type');
assert(typeDrill);assert.match(text(typeDrill),/天书增伤/);assert.match(text(typeDrill),/天书Buff/);
assert.match(text(nodes.get('bonus-summary')),/自身PVP增伤 80% − 对面PVP减伤 30% = 对抵PVP增伤 50%/);
assert.match(text(nodes.get('bonus-summary')),/自身PVP增伤 40% − 对面PVP减伤 20% = 对抵PVP增伤 20%/);
assert.match(text(nodes.get('bonus-summary')),/BOSS扣血结算（观测比）/);
assert.match(text(nodes.get('bonus-summary')),/结算前护盾/);assert.match(text(nodes.get('bonus-summary')),/不重复乘入增伤/);
const topType=rows.find(r=>r.children[0] && r.children[0].children[0] && r.children[0].children[0].textContent==='类型增伤区');
assert.equal(typeDrill.hidden,true);assert.equal(topType.children[0].children[0]['aria-expanded'],'false');
topType.children[0].children[0].onclick();assert.equal(typeDrill.children[0].children[0].hidden,false);assert.equal(typeDrill.hidden,false);
assert.equal(topType.children[0].children[0]['aria-expanded'],'true');assert.equal(topType.children[2].children[0]['aria-expanded'],'true');
topType.children[2].children[0].onclick();assert.equal(typeDrill.hidden,true);assert.equal(topType.children[0].children[0]['aria-expanded'],'false');
assert(!text(nodes.get('bonus-summary')).includes('→ 具体属性 → 属性来源'));
nodes.get('formula-type').onchange({target:{value:'attack'}});nodes.get('formula-type').value='attack';draws.at(-1).opts.onSelect(draws.at(-1).opts.xLabels.indexOf(1));
assert(!text(nodes.get('bonus-summary')).includes('天书增伤'));assert.match(text(nodes.get('bonus-summary')),/普攻增伤/);
assert.match(text(nodes.get('bonus-summary')),/实际附加修正/);
const stat=vm.runInNewContext('formulaStat([{hits:1,factors:{damage:1}},{hits:3,factors:{damage:3}}],"damage")',context);
assert.equal(stat.value,2.5);assert.equal(stat.min,1);assert.equal(stat.max,3);
assert(template.indexOf('id="factor-details"')>template.indexOf('id="zero-card"'));
assert(!/<details[^>]*id="factor-details"[^>]*\bopen\b/.test(template));
assert.match(template,/<div class="formula-comparison-body" id="bonus-summary">/);
assert(!template.includes('section("天书", p.books'));
console.log('PASS formula filters and skill mode, no-hit gaps, click-to-compare, red/green labels, zone→attribute→source drilldown, attack excludes book attributes, flat table and folded bottom details');

// Exercise the real SVG hover: totals use both sides; Top sources use the matching side denominator.
const line=script.slice(script.indexOf('  function drawLine'),script.indexOf('  // 曲线点表示'));
const svg=node(),wrap=node(),tip=node();wrap.appendChild(svg);context.svg=svg;context.tip=tip;
context.svgEl=(tag,attrs)=>{const n=node();Object.assign(n,attrs);return n;};
vm.runInNewContext(line+';drawLine(svg,tip,[{label:"我方",slot:1,values:[100]},{label:"敌方",slot:2,values:[300]}],{showPercent:true,topSources:[{label:"我方",slot:1,bySecond:[[{name:"技能A",dmg:25}]]}]});',context);
svg.onpointermove({clientX:400,clientY:100});const hover=text(tip);
assert.match(hover,/100 · 25.00%/);assert.match(hover,/300 · 75.00%/);assert.match(hover,/25 · 25.00%/);
let clicked=null;context.select=i=>clicked=i;
vm.runInNewContext('drawLine(svg,tip,[{label:"我方",slot:1,values:[1,null,3]}],{gaps:true,xLabels:[1,2,3],onSelect:select});',context);
assert.equal(svg.children.filter(n=>n.class==='series-line').length,2);svg.onclick({clientX:862});assert.equal(clicked,2);
svg.onpointermove({clientX:400,clientY:100});assert.match(text(tip),/点击查看/);
console.log('PASS real SVG hover percentages, own-side source denominator, missing-data gaps and nearest-second click');

vm.runInNewContext('drawLine(svg,tip,[{label:1,slot:1,values:[null,1,null,3,null]}],{gaps:true,connectGaps:true,xLabels:[0,1,2,3,4]});',context);
assert.equal(svg.children.filter(n=>n.class==='series-gap').length,1);assert.equal(svg.children.filter(n=>n.class==='series-line').length,2);
console.log('PASS missing-hit bridge without inventing leading/trailing data');

DATA.buffCatalog={version:'test',buffs:{14001:{sources:['高级霸体'],tag:23},341204:{sources:['白骨夫人皮肤'],attributes:[{key:105,name:'伤害减免',percent:true}]},111011:{sources:['雷公'],effects:['周期触发：DMG(dmg/2)']}}};
const buff={id:341204,name:'Buff 341204',piles:5,changes:[{key:105,name:'伤害减免',value:-.75,percent:true,zone:'普通增伤区'}]};
context.buff=buff;
assert.match(vm.runInNewContext('bossBuffHeading(buff)',context),/白骨夫人皮肤/);
assert.match(vm.runInNewContext('bossBuffLines(buff).join(";")',context),/伤害减免 -75%.*降低 BOSS 减伤/);
assert.match(vm.runInNewContext('bossBuffLines({id:14001}).join(";")',context),/控制状态：高级霸体/);
assert.match(vm.runInNewContext('bossBuffLines({id:111011}).join(";")',context),/周期触发伤害.*独立伤害事件/);
ownBook.sourceRef=0;DATA.factorSources[0].targetBuffs=[buff];context.ownBook=ownBook;
const settled=vm.runInNewContext('formulaParts([ownBook,ownBook],{key:"settlement"},DATA)',context);
assert.equal(settled.find(p=>p.id==='inputDamage').sources.filter(s=>s.includes('伤害减免 -75%')).length,1);
assert(!settled.find(p=>p.id==='actualDamage').sources.some(s=>s.includes('白骨夫人')));
console.log('PASS named BOSS buffs, signed actual reductions, control and periodic effects, per-buff deduplication and no repeated lists on actual damage');

assert.equal(vm.runInNewContext('bossContributionLabel(119,"天书减伤",.7)',context),'BOSS天书易伤收益');
assert.equal(vm.runInNewContext('bossContributionLabel(119,"天书减伤",-.7)',context),'BOSS天书减伤抵扣');
assert.equal(vm.runInNewContext('bossContributionLabel(119,"天书减伤",0)',context),'BOSS天书受击修正');
console.log('PASS target reduction contribution names follow the actual formula sign');

// Screenshot regression: two normal book hits plus one independent hit with zero-initialized multipliers.
const normal={sec:14,group:'book',boss:true,skillId:111544,hits:1,name:'万尸瀑',damage:100,
 factors:{attack:205734,coefficient:3.6,damage:12.5066,element:3.4875,targetType:1.5085,hp:.85,skillType:2.6,attackBonus:0,type:5.9585},
 inputs:{self:{115:1.9,708:1.2},target:{119:-.7}},parts:{targetType:[{side:'self',key:109,value:.529},{side:'self',key:127,value:.826},{side:'self',key:111,value:.1535}],hp:[{side:'self',key:113,value:.85}],skillType:[{side:'self',key:115,value:1.9},{side:'target',key:119,value:.7}]}};
const independent={...normal,factors:{attack:0,coefficient:0,damage:0,element:0,targetType:0,hp:0,skillType:0,attackBonus:0,type:1},parts:{skillType:[{side:'self',key:115,value:1.9},{side:'target',key:119,value:.7},{label:'条件效果、倍率下限或未拆分部分',value:-2.6}]}};
context.regressionSide={factorRows:[normal,independent,{...normal,skillId:111344}],factorSources:[]};
vm.runInNewContext("formulaState.type='book';formulaState.skill='all';",context);
const selected=vm.runInNewContext('formulaRows(regressionSide,14)',context);assert.equal(selected.length,2);
assert.equal(vm.runInNewContext('formulaStat(formulaRows(regressionSide,14),"attack").value',context),205734);
assert.equal(vm.runInNewContext('formulaStat(formulaRows(regressionSide,14),"type").value',context),5.9585);
assert.equal(vm.runInNewContext('formulaRows(regressionSide,14,true).length',context),3);
const pieces=vm.runInNewContext('formulaParts(formulaRows(regressionSide,14),{key:"type",parts:["targetType","hp","skillType","attackBonus"]},regressionSide)',context);
assert(!pieces.some(p=>p.id==='self:708' || p.id==='target:709' || p.value<0));
assert(Math.abs(1+pieces.reduce((n,p)=>n+p.value,0)-5.9585)<1e-9);
assert.match(template,/formula-parts \{[^}]*margin:[^;]*30px/);assert.match(template,/formula-zone-row/);
console.log('PASS screenshot: independent hit stays recorded but cannot dilute attack/type means; book detail excludes attack bonus and reconciles to actual multiplier');

const secondProfile={...normal,sampleKind:'second',factors:{...normal.factors,attack:100,coefficient:null,damage:2,element:3,type:4,pvp:1.5,final:1.2,crit:1,skillCrit:1,settlement:.01}};
context.secondSide={factorRows:[normal],factorSnapshots:[{...secondProfile,sec:0},{...secondProfile,sec:1}]};
context.secondProfile=secondProfile;
assert.equal(vm.runInNewContext('formulaRows(secondSide,0).length',context),1);
assert.equal(vm.runInNewContext('formulaRows(secondSide,0)[0].sampleKind',context),'second');
assert.equal(vm.runInNewContext('formulaRows(secondSide,14,true).length',context),1);
assert.equal(vm.runInNewContext('formulaFactorValue(secondProfile,"coefficient")',context),null);
assert(Math.abs(vm.runInNewContext('formulaFactorValue(secondProfile,"combined")',context)-4320)<1e-9);
secondProfile.factors.coefficient=999;secondProfile.factors.settlement=999;
assert(Math.abs(vm.runInNewContext('formulaFactorValue(secondProfile,"combined")',context)-4320)<1e-9);
assert.equal(vm.runInNewContext('formulaParts([secondProfile],{key:"combined"},secondSide).some(p=>p.id==="coefficient" || p.id==="settlement")',context),false);
console.log('PASS snapshot-backed timeline starts before hits; total includes attack and each major zone once, excludes base coefficient and observed settlement');

vm.runInNewContext("formulaState.zone='coefficient';",context);
assert.equal(vm.runInNewContext('formulaRows(secondSide,14)[0].sampleKind',context),undefined);
assert.equal(vm.runInNewContext('formulaStat(formulaRows(secondSide,14),"coefficient").value',context),3.6);
console.log('PASS base skill coefficient remains an actual-hit observation even when per-second snapshots exist');

// Regression: unrelated attack snapshots must not hide the available book hit zones.
context.DATA={pvp:{attrMeta:[]},factorSnapshots:[{...secondProfile,group:'attack',skillId:10}],factorRows:[{...normal,factors:{...normal.factors,pvp:1.5,final:1.2,settlement:1}}],other:{factorRows:[]}};
vm.runInNewContext("formulaState.type='book';formulaState.skill='all';formulaState.zone='damage';",context);
const stableZones=Array.from(vm.runInNewContext('formulaZones().map(z=>z.key)',context));
assert(stableZones.includes('damage') && stableZones.includes('attack') && stableZones.includes('coefficient') && stableZones.includes('combined'));
for(const zone of ['coefficient','settlement','damage','combined']){
 context.zoneKey=zone;vm.runInNewContext('formulaState.zone=zoneKey;renderFormulaFilters();',context);
 assert.deepEqual(Array.from(vm.runInNewContext('formulaZones().map(z=>z.key)',context)),stableZones);
}
assert.equal(vm.runInNewContext('formulaRows(DATA,14,false,"damage")[0].skillId',context),normal.skillId);
console.log('PASS partial-category snapshots cannot hide book filters; switching observed/snapshot zones keeps the entire filter list stable');

// Element panels must compare the attribute, not a value diluted by other elements.
const fireRow={...normal,hits:5,parts:{element:[{side:'self',key:201,value:3.2715},{side:'self',key:209,value:.44}]}};
const waterRow={...normal,hits:6,parts:{element:[{side:'self',key:202,value:2.2365}]}};
const windRow={...normal,hits:2,parts:{element:[{side:'self',key:203,value:2.457}]}};
const earthRow={...normal,hits:3,parts:{element:[{side:'self',key:204,value:2.506}]}};
context.elementRows=[fireRow,waterRow,windRow,earthRow];context.elementSide={factorSources:[]};
const elementParts=vm.runInNewContext('formulaParts(elementRows,{key:"element"},elementSide)',context);
const firePart=elementParts.find(p=>p.id==='self:201');assert(Math.abs(firePart.attributeValue-3.2715)<1e-12);
assert(Math.abs(firePart.value-1.02234375)<1e-12);assert.equal(firePart.applicableHits,5);assert.equal(firePart.totalHits,16);
assert(Math.abs(firePart.applicableFraction-5/16)<1e-12);
assert(Math.abs(1+elementParts.reduce((n,p)=>n+p.value,0)-3.77553125)<1e-10);
console.log('PASS real fire attribute remains 327.15%, contribution is separately 102.234375% at 5/16 applicable records');

context.DATA={pvp:{attrMeta:[{key:201,label:'火系伤害',percent:true},{key:209,label:'火系天书伤害',percent:true},{key:202,label:'水系伤害',percent:true},{key:203,label:'风系伤害',percent:true},{key:204,label:'土系伤害',percent:true}]},factorRows:context.elementRows,factorSources:[],other:{factorSources:[],factorRows:[{...fireRow,hits:10,parts:{element:[{side:'self',key:201,value:3.263}]}},{...waterRow,hits:1}]}};
vm.runInNewContext("formulaState.zone='element';formulaState.type='book';formulaState.skill='all';formulaState.sec=14;renderFormulaComparison();",context);
const elementText=text(nodes.get('bonus-summary'));
assert.match(elementText,/327.15%/);assert.match(elementText,/326.3%/);assert.match(elementText,/\+0.85个百分点/);
assert.match(elementText,/实际贡献（加权均值） 102.2344%/);
function sourceTitles(node){return (node.title || '')+' '+node.children.map(sourceTitles).join(' ');}
assert.match(elementText,/不适用，贡献按0计/);
assert.match(elementText,/本秒无适用记录/);
console.log('PASS element table compares actual attributes and precise differences, shows weights/contributions separately, and labels inapplicable sides without false zeros');

context.DATA={pvp:{attrMeta:[{key:104,label:'伤害加成',percent:true},{key:105,label:'伤害减免',percent:true}]},buffCatalog:{buffs:{341204:{sources:['【红】白骨夫人皮肤-lv5']},111713:{sources:['【红天书】-黄天令-释放-lv8','【红天书】-黄天令觉醒初阶-释放-lv8','【红天书】-黄天令觉醒-释放-lv4'],sourceCount:8}}}};
const common={label:'Buff：341204（5层）；配置来源：【红】白骨夫人皮肤-lv5；关联技能：【红】白骨夫人皮肤-lv5',value:-.75};
context.rolledSide={factorSources:[{self:{104:[{label:'基础面板',value:5}]},target:{105:[common]}},{self:{104:[{label:'基础面板',value:5},{label:'技能：加成技能',value:.5}]},target:{105:[common,{label:'Buff：111713（1层）；配置候选来源：长列表；关联技能：【红天书】-黄天令觉醒-释放-lv4',value:-.6}]}}]};
context.rolledRows=[{...normal,hits:2,sourceRef:0,parts:{damage:[{side:'self',key:104,value:5},{side:'target',key:105,value:.75}]}},{...normal,hits:3,sourceRef:1,parts:{damage:[{side:'self',key:104,value:5.5},{side:'target',key:105,value:1.35}]}}];
const rolled=vm.runInNewContext('formulaParts(rolledRows,{key:"damage"},rolledSide)',context);
const boss=rolled.find(p=>p.id==='target:105');assert(Math.abs(boss.value-1.11)<1e-12);assert.equal(boss.sources.length,2);
assert.match(boss.sources.join(';'),/白骨夫人皮肤：本秒贡献 \+75%.*生效 5\/5/);
assert.match(boss.sources.join(';'),/黄天令·释放：本秒贡献 \+36%.*生效 3\/5.*生效时 \+60%/);
const own=rolled.find(p=>p.id==='self:104');assert.equal(own.sources.length,2);assert.match(own.sources.join(';'),/基础面板：本秒贡献 \+500%.*加成技能：本秒贡献 \+30%/);
assert.equal(vm.runInNewContext('buffDisplayName(111713)',context),'黄天令·释放');
assert(!vm.runInNewContext('buffSourceLabel(rolledSide.factorSources[1].target[105][1].label)',context).includes('配置候选来源'));
console.log('PASS white-bone effect counted once per hit (75%), Huangtian conditional contribution 60%×3/5=36%, all attribute sources consolidated and level variants shortened');

context.rolledRows[0].firstT=26.09;context.rolledRows[0].sec=26;
context.rolledRows[1].firstT=26.59;context.rolledRows[1].sec=26;
context.rolledSide.factorRows=context.rolledRows;
const peak=vm.runInNewContext('formulaPartNumberInfo(formulaParts(rolledRows,{key:"damage"},rolledSide).find(p=>p.id==="target:105"),rolledRows)',context);
assert.equal(peak.peak,1.35);assert(Math.abs(peak.mean-1.11)<1e-12);assert(peak.variable);
assert.equal(vm.runInNewContext('formulaNumberInfo([formulaObservation(rolledRows[0],.75),formulaObservation(rolledRows[1],.75)]).variable',context),false);
const changes=vm.runInNewContext('formulaAttributeChanges(rolledSide,26)',context);
assert(changes.some(s=>s.includes('本秒新增') && s.includes('黄天令') && s.includes('26.59s')));
context.rolledSide.factorRows.push({...context.rolledRows[0],sec:27,firstT:27.1});
assert(vm.runInNewContext('formulaAttributeChanges(rolledSide,27)',context).some(s=>s.includes('本秒失去') && s.includes('黄天令')));
assert(!/\.formula-plot:hover \.series-line\s*\{[^}]*stroke:/.test(template));
nodes.get('open-damage-history').onclick();assert.equal(nodes.get('factor-details').open,true);
console.log('PASS peak display, weighted contribution, uniform-value suppression, attributed additions/removals and visible history expansion');

let visits=0;
context.largeSide={factorRows:Array.from({length:12000},(_,i)=>({...normal,sec:i%120,get boss(){visits++;return true;}}))};
vm.runInNewContext("formulaState.type='book';formulaState.skill='all';formulaState.zone='damage';for(let sec=0;sec<120;sec++)formulaRows(largeSide,sec);",context);
assert.equal(visits,12000,'each record classified once, not once per second');
context.largeSide.factorRows.push({...normal,sec:120});
assert.equal(vm.runInNewContext('formulaRows(largeSide,120).length',context),1);
console.log('PASS 12000-row timeline uses one scan and invalidates its index when rows grow');
