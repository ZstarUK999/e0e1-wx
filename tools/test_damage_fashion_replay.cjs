// Offline fixtures: player fashion, nested fashion skills, Wanshi child skills and replay pairing.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
async function load(file,tail){
 const ctx={console:{log(){}},Map,Date,Promise,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},__e0e1RegisterRuntimeToggle(){}};
 return await vm.runInNewContext('(async()=>{'+fs.readFileSync(path.join(__dirname,'js',file),'utf8')+'\n'+tail+'})()',ctx);
}
const table=rows=>({list:rows,getById:id=>rows.find(r=>r.id===Number(id))});
(async()=>{
 const cfg={FashionCfg:table([{id:5001,name:'雷法尊者',skill:[],attackSkill:[[11100,11101],[11110,11111]]},{id:2,name:'其他傀儡装',skill:[222]}]),
 SkillCfg:table([{id:11100,name:'雷击',skillFunctionType:1},{id:11101,name:'雷击后续',skillFunctionType:7},{id:222,name:'其他装',skillFunctionType:7},
 {id:111542,name:'四象召唤',skillFunctionType:17,bookId:111500,_properties:[{name:'sumSkill',expression:'111544'}]},
 {id:111544,name:'四象实际伤害',skillFunctionType:4,bookId:0},
 {id:111551,name:'基地喷涌',sourceBookId:111500,skillFunctionType:4}]),
 SkillBookCfg:table([{id:111500,name:'万尸瀑'}]),
 SkillBookEvolutionCfg:table([{id:409,name:'四象·尸潮',skillBookBelong:111500,evolutionPath:2}]),
 EvolutionSkillCfg:table([{id:1,skillId:111542,evolutionId:409,skillLevel:1},{id:2,skillId:111542,evolutionId:409,skillLevel:2},{id:3,skillId:111542,evolutionId:409,skillLevel:3}])};
 const player=await load('player_info_dump.js','e0e1CfgModule=arguments; return {parse:e0e1ParseFashion,build:e0e1BuildDump,setCfg(c){e0e1CfgModule=c;}};'.replace('e0e1CfgModule=arguments; ',''));
 player.setCfg(cfg);
 assert.match(player.parse({fashion:new Map([[5,5001]]),allFashion:new Map([[5001,3]])})[0],/【雷法尊者】.*已穿戴.*Lv3/);
 assert.doesNotMatch(player.parse({fashion:new Map(),onShow:new Map([[5,5001]])})[0],/已穿戴/);
 assert.match(player.parse({})[0],/未下发/);
 const dump=await player.build({fashion:new Map([[5,5001]])},false);
 assert.equal(dump.sections[0].name,'傀儡装');
 console.log('PASS actual equipped fashion is first, display-only and missing snapshots are distinguished');
 const damage=await load('damage_curve_probe.js',`return {classify:e0e1Classify,newState:e0e1NewState,handler:e0e1MakeHandler,collect:e0e1CollectSide,
 setCfg(c){E0E1_CFG=c;E0E1_EVO=null;E0E1_ORIGIN=null;},setManagers(b,d){E0E1_BM=b;E0E1_DUAL=d;},patch:e0e1PatchBattleManager,
 watch:e0e1WatchWorld,sweep:e0e1AttachAll,watched(){return E0E1_WATCHED.length;},replays(){return E0E1_REPLAY_CONTEXTS.length;},stop:damageCurveStop,sides(){return E0E1_SIDES;},pvp(){return E0E1_PVP;}};`);
 damage.setCfg(cfg);
 assert.equal(damage.classify(11100).cat,'leifa');assert.equal(damage.classify(11101).cat,'leifa');
 assert.equal(damage.classify(222).cat,'fashion');assert.match(damage.classify(11100).origin,/雷法尊者/);
 const w={options:{battleData:{type:20,randomSeed:1}},battleTime:{battleTime:1}};
 const st=damage.newState(w,'self',false);damage.handler(st)({},11100,100,{compBoss:true},false);damage.handler(st)({},222,50,{},false);
 const summary=damage.collect(st);assert.equal(summary.totalDamage,150);assert.equal(summary.categories.find(c=>c.key==='leifa').dmg,100);
 console.log('PASS nested fashion attack skills form an exclusive category without double counting');
 const wan=damage.classify(111544,{activeBranches:[{branchId:409,level:1}]});
 assert.equal(wan.bookId,111500);assert.equal(wan.branchId,409);assert.equal(wan.branchLevel,1);
 assert.equal(damage.classify(111544).branchLevel,null);assert.equal(damage.classify(111551).bookId,111500);
 console.log('PASS Wanshi summoned damage inherits branch, shared skill uses actual equipped level');
 let next=0;const signal=()=>({add(){},remove(){}});
 const manager={createBattle(type,options){return {instanceId:++next,options,battleSignal:{$skillDamageCollect:signal(),timeBattleTickSignal:signal()},battleTime:{battleTime:0}};},getBattles(){return [];}};
 class Controller{start(opts){this.selfScoreInfo={isSelf:true,score:10};this.otherScoreInfo={isSelf:false,score:10};
 const make=(mi)=>manager.createBattle(20,{mineInfo:mi,battleData:{type:20,randomSeed:opts.seed,leftTeam:{team:[]},rightTeam:{team:[]}}});
 this.otherBattleWorld=make(this.otherScoreInfo);this.selfBattleWorld=make(this.selfScoreInfo);return Promise.resolve('original-result');}}
 const originalCreate=manager.createBattle,originalStart=Controller.prototype.start;
 damage.setManagers({BattleManager:{ins:manager}},{ArenaDualScorePvpBattleManager:Controller});damage.patch();
 const c=new Controller();assert.equal(await c.start({isReplay:true,openType:2,seed:1}),'original-result');
 assert.equal(damage.sides().self.world,c.selfBattleWorld);assert.equal(damage.sides().other.world,c.otherBattleWorld);
 assert.equal(damage.sides().self.replay.isReplay,true);assert.equal(damage.sides().self.replay.sessionId,damage.sides().other.replay.sessionId);
 const old=damage.sides().other.world;damage.pvp().samples.push({sec:99});
 await c.start({isReplay:true,openType:2,seed:2});
 assert.notEqual(damage.sides().other.world,old);assert.equal(damage.sides().other.world,c.otherBattleWorld);
 assert.equal(damage.pvp().samples.length,0);assert.equal(damage.collect(damage.sides().self).replay.isReplay,true);
 c.selfBattleWorld.isQuitted=true;c.otherBattleWorld.isQuitted=true;old.isQuitted=true;
 damage.sweep();assert.equal(damage.sides().self.world,null);assert.equal(damage.sides().other.world,null);
 assert.equal(damage.replays(),0);assert(damage.collect(damage.sides().self).replay.isReplay);
 console.log('PASS exited worlds and replay controllers released while archived data remains readable');
 console.log('PASS season replay supports other-world-first creation, correct sides and consecutive battle isolation');
 damage.stop();assert.equal(manager.createBattle,originalCreate);assert.equal(Controller.prototype.start,originalStart);
 damage.patch();await c.start({isReplay:true,openType:2,seed:3});assert.equal(damage.sides().self.world,c.selfBattleWorld);
 damage.stop();assert.equal(manager.createBattle,originalCreate);
 console.log('PASS stopping and re-enabling restores original methods without duplicate hooks');
 // Bloodmoon replay discovered after start: no replay tag, enemy world first.
 function untaggedPair(seed,enemyFirst){
   const metrics={}, make=isSelf=>manager.createBattle(20,{mineInfo:{isSelf,score:800,pvpMetrics:metrics},battleData:{type:20,randomSeed:seed,leftTeam:{team:[]},rightTeam:{team:[]}}});
   const self=make(true),other=make(false);
   for(const world of enemyFirst?[other,self]:[self,other])damage.watch(world);
   assert.equal(damage.sides().self.world,self);assert.equal(damage.sides().other.world,other);
   return {self,other};
 }
 untaggedPair(43,false);
 damage.pvp().samples.push({sec:99});
 const pair=untaggedPair(44,true);
 assert.equal(damage.pvp().samples.length,0);
 damage.handler(damage.sides().other)({},11100,123,{compBoss:true},false);
 damage.watch(pair.self);damage.watch(pair.other);
 assert.equal(damage.collect(damage.sides().other).totalDamage,123);
 damage.pvp().samples.push({sec:55});
 untaggedPair(44,false); // Same seed, different metrics means a new battle.
 assert.equal(damage.pvp().samples.length,0);
 assert.equal(damage.collect(damage.sides().other).totalDamage,0);
 damage.stop();
 console.log('PASS untagged bloodmoon replay retains enemy data in either order and isolates repeated seeds');
 const template=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/damage_report/template.py'),'utf8');
 const reportScript=template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];new vm.Script(reportScript);
 const render=reportScript.slice(reportScript.indexOf('  function renderBookComparison'),reportScript.indexOf('  // ── 拆解图'));
 const nodes=new Map();
 function node(text=''){return {textContent:text,children:[],hidden:true,appendChild(n){this.children.push(n);return n;},removeChild(n){this.children.splice(this.children.indexOf(n),1);},get firstChild(){return this.children[0];}};}
 const DATA={battleType:20,replay:{isReplay:true},categories:[{key:'leifa',dmg:123,hits:2}],other:{categories:[{key:'leifa',dmg:45,hits:1}]}};
 const document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},createTextNode:node};
 const context={DATA,document,sd:()=>DATA,fmt:String,el:(tag,cls,text)=>node(text)};
 vm.runInNewContext(render+';renderPlayers();',context);
 assert.equal(nodes.get('leifa-card').hidden,false);assert.match(nodes.get('leifa-summary').textContent,/我方：123.*敌方：45/);
 DATA.players={self:{name:'甲',fashions:[{name:'雷法尊者',level:3}]}};
 vm.runInNewContext('renderPlayers();',context);
 function texts(n){return (n.textContent||'')+' '+n.children.map(texts).join(' ');}
 assert.match(texts(nodes.get('players')),/雷法尊者 Lv3/);assert.match(texts(nodes.get('players')),/血月战场回放/);
 console.log('PASS report renders independent damage without player snapshot, fashion and season replay labels');
 const align=reportScript.slice(reportScript.indexOf('  function pvpIntervalSources'),reportScript.indexOf('  // ── PVP 三图'));
 const sample={events:[{t:3.3125,skill:20100102,skillName:'2%火幡',boss:true,dmg:180143985094820},
 {t:3.3125,skill:20100104,skillName:'3%火幡',boss:true,dmg:270215977642230},
 {t:4.1,skill:99,skillName:'下一秒',boss:true,dmg:100}]};
 const result=vm.runInNewContext(align+';pvpIntervalSources(sample,[{t:3,sec:3},{t:4,sec:4},{t:5,sec:5}]);',{sample});
 assert.equal(result[1][0].skillId,20100104);assert.equal(result[1][1].skillId,20100102);
 assert.equal(result[1].reduce((sum,r)=>sum+r.dmg,0),450359962737050);
 assert.equal(result[2][0].skillId,99);
 const compact={skills:[{skillId:20100102,name:'火幡',bossPerSecond:[0,0,0,180143985094820,0]}]};
 const fallback=vm.runInNewContext(align+';pvpIntervalSources(sample,[{t:3},{t:4}]);',{sample:compact});
 assert.equal(fallback[1][0].dmg,180143985094820);
 console.log('PASS score-increment tooltip aligns previous-second flag damage and preserves raw spike');
 const projection=reportScript.slice(reportScript.indexOf('  function flagSkills'),reportScript.indexOf('  var DATA = withoutFlags'));
 const raw={totalDamage:1050,bossDamage:1050,eventCount:3,categories:[{key:'flag',dmg:1000},{key:'book',dmg:50}],
 curves:[{key:'flag',perSecond:[0,1000],bossPerSecond:[0,1000]},{key:'__total',dmg:1050,perSecond:[0,1050],bossPerSecond:[0,1050]}],
 skills:[{skillId:1,cat:'flag',dmg:1000,hits:2,perSecond:[0,1000],bossPerSecond:[0,1000]},{skillId:2,cat:'book',dmg:50,hits:1}],
 events:[{skill:1,cat:'flag',t:1.2,boss:true,dmg:1000},{skill:2,cat:'book',t:1.3,boss:true,dmg:50}],
 perSecondBossTop:[[],[{skillId:1,dmg:1000},{skillId:2,dmg:50}]],
 other:{skills:[{skillId:3,cat:'flag',dmg:200,hits:1,bossPerSecond:[0,200]}]},
 pvp:{derived:[{t:1,selfDmg:0,otherDmg:0,selfScore:800},{t:2,selfDmg:1050,otherDmg:250,selfScore:850}]}};
 const before=JSON.stringify(raw);
 const filtered=vm.runInNewContext(projection+';withoutFlags(raw);',{raw});
 assert.equal(filtered.totalDamage,50);assert.equal(filtered.bossDamage,50);assert.equal(filtered.eventCount,1);
 assert.equal(filtered.skills.length,1);assert.equal(filtered.events.length,1);assert.equal(filtered.categories.length,1);
 assert.equal(filtered.curves[0].perSecond[1],50);assert.equal(filtered.curves[0].cumulative[1],50);
 assert.equal(filtered.perSecondBossTop[1].length,1);
 assert.equal(filtered.pvp.derived[1].selfDmg,50);assert.equal(filtered.pvp.derived[1].otherDmg,50);
 assert.equal(filtered.pvp.derived[1].share,0.5);assert.equal(filtered.pvp.derived[1].selfScore,850);
 assert.equal(JSON.stringify(raw),before);assert.match(template,/<details class="card" id="flag-card" hidden>/);
 const noFlag=vm.runInNewContext(projection+';withoutFlags(raw);',{raw:{skills:[],pvp:{derived:[{t:1,selfDmg:20,otherDmg:10}]}}});
 assert.equal(noFlag.pvp.derived[0].selfDmg,20);
 console.log('PASS flags are isolated from totals, curves, sources and both-side PVP intervals without changing raw scores');
})().catch(e=>{console.error(e);process.exitCode=1;});
