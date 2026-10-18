const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const template=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/damage_report/template.py'),'utf8');
const script=template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];new vm.Script(script);
const code=script.slice(script.indexOf('  function bonusValue'),script.indexOf('  function renderFlags'));
function node(text=''){return {textContent:text,children:[],style:{},dataset:{},events:{},hidden:false,checked:false,
 appendChild(n){this.children.push(n);return n;},removeChild(n){this.children.splice(this.children.indexOf(n),1);},
 addEventListener(name,fn){this.events[name]=fn;},get firstChild(){return this.children[0];}};}
function text(n){return (n.textContent||'')+' '+n.children.map(text).join(' ');}
const meta=[{key:104,label:'双零普通属性',note:'双零普通属性',percent:true},{key:117,label:'仅我方属性',note:'仅我方属性',percent:true},
 {key:118,label:'仅敌方属性',note:'仅敌方属性',percent:true},{key:3,label:'短暂属性',note:'短暂属性',percent:true},
 {key:999,label:'缺失属性',note:'缺失属性',percent:true},{key:'finalPvp',label:'双零派生属性',note:'双零派生属性',percent:true}];
const zero={};[1,2,3,19,20,104,105,117,118,123,129,124,...Array.from({length:32},(_,i)=>201+i),'finalPvp'].forEach(k=>zero[k]=0);
const row0={sec:0,self:{...zero,117:.2,999:null},other:{...zero,118:.3,999:0}};
const row1={sec:1,self:{...row0.self,3:.1},other:{...row0.other}};
const row2={sec:2,self:{...row0.self},other:{...row0.other}};
const DATA={pvp:{attrMeta:meta,attrSeconds:[row0,row1,row2]}};
const nodes=new Map(),plots=[];
const document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},createElement:()=>node()};
const context={DATA,document,attrState:{sec:0,picked:[]},ATTR_MAX_SERIES:4,SELF_SLOT:1,OTHER_SLOT:2,
 el:(tag,cls,t)=>node(t),fmt:String,pctText:n=>String(n*100),fmtAttr:(m,v)=>v==null?'—':String(v),
 attrMetaOf:(p,key)=>p.attrMeta.find(m=>String(m.key)===String(key))||{label:'属性'+key},drawLine:(svg,tip,series)=>plots.push(series)};
vm.runInNewContext(code,context);
assert.equal(vm.runInNewContext('bothZero({1:0},{1:0},1)',context),true);
assert.equal(vm.runInNewContext('bothZero({1:null},{1:0},1)',context),false);
assert.equal(vm.runInNewContext('bothZero({},{1:0},1)',context),false);
vm.runInNewContext('renderLegacyAttrs();',context);
function shown(){return text(nodes.get('attr-picks'))+' '+text(nodes.get('attr-table'))+' '+text(nodes.get('bonus-summary'));}
assert(!shown().includes('双零普通属性'));assert(!shown().includes('双零派生属性'));assert(!shown().includes('短暂属性'));
assert(shown().includes('仅我方属性'));assert(shown().includes('仅敌方属性'));assert(shown().includes('缺失属性'));
assert(!text(nodes.get('bonus-summary')).includes('火系'));assert(!text(nodes.get('bonus-summary')).includes('普通增伤 '));
context.attrState.picked=[104,117];vm.runInNewContext('renderAttrPicks(DATA.pvp,[0,1,2]);renderAttrChart(DATA.pvp,[0,1,2],DATA.pvp.attrMeta);',context);
assert.deepEqual(Array.from(context.attrState.picked),[117]);assert(plots.at(-1).every(s=>!s.label.includes('双零')));
nodes.get('attr-sec').events.input({target:{value:'1'}});assert(shown().includes('短暂属性'));
context.attrState.picked=[3,118];vm.runInNewContext('renderAttrPicks(DATA.pvp,[0,1,2]);syncAttrChips();',context);
const enemyChip=nodes.get('attr-picks').children.find(c=>c.children[0].dataset.key==='118');assert.equal(enemyChip.className,'chip');
nodes.get('attr-sec').events.input({target:{value:'2'}});assert(!shown().includes('短暂属性'));assert.deepEqual(Array.from(context.attrState.picked),[118]);
const sourceLines=vm.runInNewContext("bonusSourceLines({104:0,117:0},{},[104,117],'',{104:0,117:.2});",context);
assert.equal(sourceLines.length,1);assert(sourceLines[0].includes('仅我方属性'));
const parts=vm.runInNewContext("factorPartLines({parts:{damage:[{key:104,side:'self',value:0},{key:117,side:'self',value:0}]},inputs:{self:{104:0,117:0},target:{104:0,117:.2}}},null,'damage');",context);
assert.equal(parts.length,1);assert(!parts[0].includes('双零普通属性'));
console.log('PASS both-zero attributes disappear from table, options, chart, summaries, source and factor details; missing/one-sided values stay and changing seconds resynchronizes picks');

// Compare table: names only are red, center is a signed difference, every cell has source hover text.
context.el=(tag,cls,t)=>{const n=node(t);n.className=cls || '';return n;};
const comparison={sec:0,self:{...zero,115:.4,109:.2,106:.3,107:1.5},other:{...zero,115:.2,109:.5,106:.3,107:1},
 selfSources:{115:[{label:'我方天书Buff',value:.4}]},otherSources:{109:[{label:'敌方首领Buff',value:.5}]}};
context.comparison=comparison;vm.runInNewContext('renderBonusSummary(comparison);',context);
const body=nodes.get('bonus-summary').children[0].children[1];
function findRow(label){return body.children.find(r=>r.children.length===3 && r.children[0].children[0].textContent===label);}
const book=findRow('天书增伤'),boss=findRow('首领增伤'),crit=findRow('法术暴击率'),power=findRow('法术暴击伤害');
assert(book && boss && crit && power);assert.equal(book.children[0].children[0].className,'bonus-winner');
assert.notEqual(book.children[2].children[0].className,'bonus-winner');assert.equal(boss.children[2].children[0].className,'bonus-winner');
assert(crit.children.every(c=>!c.children.some(n=>n.className==='bonus-winner')));
assert.equal(book.children[1].textContent,'+20个百分点');assert.equal(boss.children[1].textContent,'-30个百分点');
assert.match(book.children[0].title,/我方天书Buff/);assert.match(boss.children[2].title,/敌方首领Buff/);
assert.match(book.children[1].title,/差值 = 我方 − 敌方/);assert.match(book.children[1].title,/我方天书Buff/);
assert(!findRow('普通增伤'));assert.equal(book.children[0].children[1].className,'bonus-value');
console.log('PASS three-column comparison includes books, bosses and spell crit; only higher names are red and all cells provide source tooltips');

const corrected=vm.runInNewContext("bonusSourceLines({117:.09},{117:[{label:'Buff：402083 · 雷法真人3星·落雷普攻（4层）',value:.09}]},[117],'',{});",context);
assert.match(corrected[0],/Buff：未解析状态 \[ID 402083\]（4层）；关联技能：雷法真人3星·落雷普攻/);
console.log('PASS archived buff context is labeled as an associated skill rather than the granting source');

vm.runInNewContext("DATA.buffCatalog={buffs:{402083:{displayName:'痴尸舍利·天书斗法',triggerDescription:'释放天书时叠加PVP增伤，每层2.25%，最多8层',suppressRelatedSkill:true}}};",context);
const actualTrigger=vm.runInNewContext("bonusSourceLines({117:.1125},{117:[{label:'Buff：402083（5层）；配置来源：三尸·痴尸舍利；关联技能：主角普攻',value:.1125}]},[117],'',{});",context);
assert.match(actualTrigger[0],/痴尸舍利·天书斗法.*5层.*释放天书时叠加PVP增伤/);
assert(!actualTrigger[0].includes('主角普攻'));assert(!actualTrigger[0].includes('关联技能'));
assert.match(vm.runInNewContext("briefSourceName('Buff：402083（5层）；关联技能：主角普攻')",context),/释放天书时叠加PVP增伤/);
console.log('PASS PLAYER_BUFF attack context is hidden; PVP source identifies the actual book-cast stacking mechanic');
