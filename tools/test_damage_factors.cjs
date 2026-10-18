const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const probe=fs.readFileSync(path.join(root,'tools/js/damage_curve_probe.js'),'utf8');
const ctx={console:{log(){}},Map,Date,Promise,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},__e0e1RegisterRuntimeToggle(){}};
(async()=>{
 const api=await vm.runInNewContext('(async()=>{'+probe+`;return {
 configure(c,h){E0E1_CFG=c;E0E1_CHARACTER={characterHelper:h};E0E1_DEFINE={EBattleTeamOpType:{seasonEnergy:9}};E0E1_BATTLE_CONST={BattleConst:{SPCRIT_AOE_HIT_COUNT:8}};},
 players:e0e1ReadPlayers,state:e0e1NewState,handler:e0e1MakeHandler,patch:e0e1PatchFactorCapture,stop:damageCurveStop,
 setState(s){E0E1_SIDES.self=s;},sources:e0e1ReadAttrSources,context:e0e1ReadAttrContext,final:e0e1WithFinalPvp,
 keys(){return E0E1_ATTR_KEYS;},collect:e0e1CollectSide,stack(){return E0E1_DAMAGE_STACK.length;}};})()`,ctx);
 const table=rows=>({list:rows,getById:id=>rows.find(row=>row.id===Number(id))});
 const cfg={SkillCfg:table([{id:10,name:'普攻',type:1,skillFunctionType:1},{id:20,name:'天书',type:4,skillFunctionType:4,bookId:100},
 {id:30,name:'符咒',type:2,skillFunctionType:3,bookId:200},{id:99,name:'加成来源',type:4}]),
 SkillBookCfg:table([{id:100,name:'测试天书'},{id:200,name:'测试符咒'}]),SeasonStaminaCfg:table([{id:80,skillDamage:9000,finalDamage:8000}])};
 function attributes(){
  const map=new Map();api.keys().forEach(m=>map.set(m.key,{baseValue:0,addScaleValue:0,addAbsoluteValue:0,percent:m.p}));
  const group={attributes:map,get(key){const a=map.get(Number(key));return a ? (a.baseValue*(1+a.addScaleValue)+a.addAbsoluteValue)/(a.percent?10000:1):0;}};
  return {attributes:group,get:group.get.bind(group)};
 }
 api.configure(cfg,{});
 const teams=api.players({options:{battleData:{leftTeam:{name:'玩家甲',roleId:1,power:123,team:new Map([[9,{id:9,equipSkills:new Map([[20,1],[10,1],[30,1]])}]])},
 rightTeam:{name:'玩家乙',roleId:2,team:new Map([[4,{id:4}]])}}}});
 assert.equal(teams.self.name,'玩家甲');assert.equal(teams.other.name,'玩家乙');assert.equal(teams.self.fightPower,123);
 assert.equal(teams.self.books[0].bookId,100);assert.equal(teams.self.books.length,1);
 console.log('PASS native Map teams provide both player names and equipped books for named archives');
 let handler,world,source,target;
 const helper={subLife(context){if(context.throwNative)throw new Error('native error');if(context.zeroNoSignal)return 0;if(context.useShield)target.compArmor.current=0;if(context.mutate)source.compAttributes.attributes.attributes.get(104).baseValue=9900;
 handler(source,context.skillId,context.zeroSignal?0:25,target,false);return context.zeroSignal?0:'native-result';}};
 api.configure(cfg,helper);
 source={uuid:1,name:'英雄',compAttributes:attributes(),compCampFriend:true,compLife:{max:100},compArmor:{current:50},
 compSkillAssistant:{allSkills:new Map([[99,{skillId:99,changeAttributes:{3:500}}]])},
 compBuffAssistant:{buffs:[{cfg:{id:7,name:'测试Buff'},piles:2,changeAttributes:new Map([[3,1000]]),skillContext:{shareData:{skillCfg:{id:99,name:'加成来源'}}},endCond:[]}]}};
 target={uuid:2,name:'目标',compBoss:true,compMonster:{},compAttributes:attributes()};
 const vals=source.compAttributes.attributes.attributes;vals.get(3).baseValue=3000;vals.get(3).addScaleValue=.1;vals.get(3).addAbsoluteValue=2000;
 vals.get(104).baseValue=2000;vals.get(117).baseValue=1000;
 const rows=api.sources({},source)[3];assert.equal(rows.length,5);assert(Math.abs(rows.reduce((n,r)=>n+r.value,0)-.53)<1e-10);
 assert(rows.some(r=>r.label.includes('测试Buff')&&r.label.includes('2层')));assert(rows.some(r=>r.label.includes('加成来源')));
 assert(rows.some(r=>r.label.includes('未归属')));
 world={instanceId:7,options:{battleData:{type:20,leftTeam:{options:new Map([[9,80]])}},mineInfo:{isSelf:true,pvpMetrics:{otherPvpDmgRed:2500}}},getFightHero:()=>source,battleTime:{battleTime:3.1}};
 const state=api.state(world,'self',false);api.setState(state);handler=api.handler(state);
 const original=helper.subLife;api.patch();assert.notEqual(helper.subLife,original);
 const damage={battleWorld:world,source,target,skillId:10,sourceAttr:source.compAttributes.attributes,targetAttr:target.compAttributes.attributes,
 atk:163,multiplier:{baseCoeff:2,dmgAddRate:1.2,elementAddRate:1,targetType:0,dmgTypeRate:0,hpDmgAddRate:0,skillTypeAddRate:.3,attackDmgRate:.2,pvpDmgRate:-2,finalDmgRate:-2},
 skillContext:{effectParams:{hitCount:1}}};
 assert.equal(helper.subLife(damage),'native-result');assert.equal(state.factorRows.length,1);
 assert.equal(state.factorRows[0].factors.type,1.5);assert.equal(state.factorRows[0].factors.pvp,.5);assert.equal(state.factorRows[0].factors.final,.25);
 assert.equal(state.factorRows[0].group,'attack');assert.equal(state.factorRows[0].context.opponentPvpRed,.25);
 assert.equal(state.factorRows[0].factors.staminaSkill,.9);assert.equal(state.factorRows[0].factors.staminaFinal,.8);
 world.battleTime.battleTime=3.2;damage.multiplier.dmgAddRate=1.4;helper.subLife(damage);
 world.battleTime.battleTime=3.3;damage.multiplier.dmgAddRate=1.2;helper.subLife(damage);
 world.battleTime.battleTime=3.4;helper.subLife(damage);
 assert.equal(state.factorRows.length,3);assert.equal(state.factorRows[2].hits,2);
 world.battleTime.battleTime=4.1;damage.mutate=true;helper.subLife(damage);damage.mutate=false;
 assert.equal(state.factorRows[3].inputs.self[104],.2);assert.equal(state.factorRows[3].sec,4);
 assert.equal(vals.get(104).baseValue,9900); // only native fixture mutates, observer doesn't.
 damage.skillId=20;helper.subLife(damage);assert.equal(state.factorRows.at(-1).group,'book');
 damage.skillId=30;helper.subLife(damage);assert.equal(state.factorRows.at(-1).group,'skill');
 const ownerSources=state.factorRows.at(-1).sourceRef;
 damage.source={uuid:3,name:'继承攻击的召唤物',compAttributes:attributes()};helper.subLife(damage);
 assert.equal(state.factorRows.at(-1).sourceRef,ownerSources); // actual sourceAttr belongs to hero.
 damage.throwNative=true;assert.throws(()=>helper.subLife(damage),/native error/);assert.equal(api.stack(),0);damage.throwNative=false;
 const nativeRows=state.factorRows.length;handler(source,10,100,target,false);assert.equal(state.factorRows.length,nativeRows); // no real context: never infer.
 const sampled=api.final([{sec:1,self:{117:.1},other:{118:.9},selfSources:{3:rows},selfContext:{opponentPvpRed:.25}}]);
 assert.equal(sampled[0].self.finalPvp,-.15);assert.equal(sampled[0].selfSources[3],rows);
 const collected=api.collect(state);assert.equal(collected.factorRows,state.factorRows);assert.equal(collected.factorSources,state.factorSources);
 vals.get(115).baseValue=4000;vals.get(109).baseValue=2000;vals.get(127).baseValue=1000;
 target.compAttributes.attributes.attributes.get(119).baseValue=1000;
 target.compAttributes.attributes.attributes.get(105).addAbsoluteValue=-1000;
 target.compBuffAssistant={buffs:[{cfg:{id:8,name:'BOSS易伤'},piles:2,time:1,timeMax:10,
 changeAttributes:new Map([[105,-1000]]),skillContext:{shareData:{skillCfg:{id:99,name:'易伤来源技能'},source:{name:'我方英雄'}}}},
 {cfg:{id:9,name:'特殊控制',tag:123},piles:1,time:0,timeMax:3,changeAttributes:new Map()}]};
 world.battleTime.battleTime=5.1;damage.skillId=20;damage.multiplier.dmgTypeRate=.3;helper.subLife(damage);
 const split=state.factorRows.at(-1),buffs=state.factorSources[split.sourceRef].targetBuffs;
 assert.equal(buffs[0].changes[0].zone,'普通增伤区');assert.equal(buffs[0].changes[0].value,-.1);
 assert.match(buffs[0].changes[0].usage,/受击/);assert.equal(buffs[0].remainingSeconds,9);
 assert.equal(buffs[0].skillName,'易伤来源技能');assert.equal(buffs[1].changes.length,0);
 assert(split.parts.skillType.some(p=>p.key===115&&p.value===.4));
 assert(split.parts.skillType.some(p=>p.key===119&&p.value===-.1));
 assert(Math.abs(split.parts.targetType.reduce((n,p)=>n+p.value,0)-.3)<1e-10);
 const bossRows=state.factorRows.length;target.compBoss=false;helper.subLife(damage);assert.equal(state.factorRows.length,bossRows);target.compBoss=true;
 console.log('PASS BOSS-only capture, per-zone additive book/boss breakdown and BOSS buff source, duration, signed reduction and unknown mechanism');
 damage.damage=100;damage.useShield=true;target.compArmor={current:75};world.battleTime.battleTime=6.1;
 helper.subLife(damage);damage.useShield=false;
 assert.equal(state.factorRows.at(-1).factors.settlement,.25);
 assert.equal(state.factorRows.at(-1).settlement.shieldBefore,75);assert.equal(state.factorRows.at(-1).settlement.shieldAfter,0);
 const beforeZero=state.eventCount;
 damage.zeroNoSignal=true;target.compAttributes.attributes.attributes.get(1006).baseValue=1;world.battleTime.battleTime=6.2;
 assert.equal(helper.subLife(damage),0);damage.zeroNoSignal=false;
 assert.equal(state.factorRows.at(-1).factors.settlement,0);assert.equal(state.factorRows.at(-1).settlement.immunity,1);
 assert.equal(state.eventCount,beforeZero,'zero settlement does not create a damage event');
 const zeroHits=state.factorRows.at(-1).hits;damage.zeroSignal=true;helper.subLife(damage);damage.zeroSignal=false;
 assert.equal(state.factorRows.at(-1).hits,zeroHits+1,'zero signal and fallback are not double counted');
 assert.equal(state.eventCount,beforeZero);assert.equal(state.lastTime,6.2);
 console.log('PASS separate observed settlement ratio, pre/post shields, zero-damage immunity without a signal, no double counting and unchanged damage totals');
 api.stop();assert.equal(helper.subLife,original);api.patch();api.stop();assert.equal(helper.subLife,original);
 console.log('PASS native return/throw preservation, actual-hit-only capture, all three groups, same-second A→B→A changes, inheritance, provenance and teardown');
 const template=fs.readFileSync(path.join(root,'package/plugin_manager/damage_report/template.py'),'utf8');
 const script=template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];new vm.Script(script);
 const ui=script.slice(script.indexOf('  function bonusValue'),script.indexOf('  function renderAttrTable'));
 const nodes=new Map();function node(text=''){return {textContent:text,children:[],checked:false,appendChild(n){this.children.push(n);return n;},removeChild(n){this.children.splice(this.children.indexOf(n),1);},get firstChild(){return this.children[0];}};}
 function text(n){return n.textContent+' '+n.children.map(text).join(' ');}
 const DATA={pvp:{attrMeta:api.keys().map(m=>({key:m.key,label:m.label,percent:m.p}))},factorRows:state.factorRows,factorSources:state.factorSources};
 const document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}};
 const uiCtx={DATA,document,el:(tag,cls,t)=>node(t||''),attrMetaOf:(p,key)=>p.attrMeta.find(m=>m.key===key)||{label:key},fmt:String,pctText:n=>String(Math.round(n*10000)/100),fmtAttr:(m,v)=>v===undefined?'—':String(v)};
 vm.runInNewContext(ui+';renderBonusSummary({sec:3,self:{3:.5,20:.1},other:{}});renderFactorHistory({sec:3});',uiCtx);
 assert.match(text(nodes.get('bonus-summary')),/火系.*水系.*风系.*土系/);
 assert.match(text(nodes.get('bonus-summary')),/攻击加成合计\s+60%/);
 const history=text(nodes.get('factor-history'));assert.match(history,/普攻/);assert.match(history,/×1.2000/);assert.match(history,/×1.4000/);assert.match(history,/测试Buff/);assert.match(history,/未记录到该类实际命中/);
 assert(!history.includes('4.100'));
 nodes.get('factor-all-seconds').checked=true;vm.runInNewContext('renderFactorHistory({sec:3});',uiCtx);
 assert.match(text(nodes.get('factor-history')),/4.100/);
 assert.match(text(nodes.get('factor-history')),/BOSS易伤/);assert.match(text(nodes.get('factor-history')),/普通增伤区/);
 assert.match(text(nodes.get('factor-history')),/未确认/);assert.match(text(nodes.get('factor-history')),/天书增伤 \+40%/);
 assert.equal(vm.runInNewContext('bonusSum({},[3,20])',uiCtx),null);
 console.log('PASS four-element and attack summaries, per-second/all-seconds actual multipliers, source labels and missing-data handling');
})().catch(e=>{console.error(e);process.exitCode=1;});
