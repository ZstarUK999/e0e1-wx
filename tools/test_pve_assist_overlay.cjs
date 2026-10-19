const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/pve_assist_overlay.js'),'utf8');
let paintCount=0,activationCount=0;
class Graphics{constructor(){this.colors=[];}clear(){paintCount++;this.colors=[];}rect(){}roundRect(){}circle(){}moveTo(){}lineTo(){}fill(){this.colors.push(this.fillColor);}stroke(){this.colors.push(this.strokeColor);}}
class Transform{setContentSize(w,h){this.width=w;this.height=h;}convertToNodeSpaceAR(p,out){out.x=p.x-500;out.y=p.y-400;return out;}}
class Label{static Overflow={CLAMP:1};}
class Node{static EventType={TOUCH_START:'start',TOUCH_MOVE:'move',TOUCH_END:'end',TOUCH_CANCEL:'cancel'};
 constructor(name){this.name=name;this.children=[];this.handlers={};this.isValid=true;this.layer=1;this.position={x:0,y:0};}
 set active(value){if(this._active!==value)activationCount++;this._active=value;}get active(){return this._active;}
 addChild(n){this.children.push(n);n.parent=this;}setPosition(x,y){this.position={x,y};}
 addComponent(C){if(C===Graphics || C===Label){assert(!this.renderer);this.renderer=C;}const c=new C();this[C.name]=c;return c;}
 getComponent(C){return this[C.name];}on(key,f){this.handlers[key]=f;}destroy(){this.isValid=false;for(const n of this.children)n.destroy();}}
class Color{constructor(...values){this.values=values;}}class Vec3{constructor(x=0,y=0,z=0){Object.assign(this,{x,y,z});}}
let now=0,animations=0;const cc={Node,Graphics,UITransform:Transform,Label,Color,Vec3,Camera:class{},BlockInputEvents:class{},HorizontalTextAlignment:{CENTER:1},view:{getVisibleSize:()=>({width:1000,height:800})},Tween:{stopAllByTarget(){}},tween(){return {to(){return this;},start(){animations++;}}}};
const host=new Node('host');host.addComponent(Transform);
const context={pickupMonsters:[]};let views=[];
class NativeUI{constructor(world){this.battleWorld=world;this.usedSpecialCardNum=0;this.node=new Node('native');this.speedUpNode=new Node('speed');this.speedUpNode.getComponentsInChildren=()=>[];}
 getSpeedUpConfig(){return [15,3];}isSpeedUpVisible(){return this.battleWorld.options.battleData.type===11 && this.usedSpecialCardNum>=15;}
 refreshSpeedUpButtonVisible(){this.speedUpNode.active=this.isSpeedUpVisible();}refreshSpeedNode(){} }
// Execute the game's actual threshold method, rather than duplicating its condition in this test.
const game=fs.readFileSync(process.env.PVE_GAME_SOURCE || path.join(__dirname,'../output/wx6d5e82c174635a48/65/subpackages/game/game.js'),'utf8');
const gate=game.match(/r\.isSpeedUpVisible = (function\(\) \{[\s\S]*?)\}, r\.refreshSpeedUpButtonVisible/);
assert(gate,'actual native Zhongkui speed gate');
NativeUI.prototype.isSpeedUpVisible=new Function('C','return ('+gate[1]+'});')({advSubdue:11});
const original=NativeUI.prototype.isSpeedUpVisible,originalConfig=NativeUI.prototype.getSpeedUpConfig;
const world={options:{battleData:{type:11},stageConfig:{phase:[7110201,7110202,7110203,7110204,7110205,7110206]}},battleTime:{timeScale:1,baseTimeScale:1},sceneEntity:{getComponent:()=>context},battleNode:{getComponentsInChildren:()=>[{camera:{worldToScreen(out,p){Object.assign(out,p);}},visibility:1}]} };
const ui={system:host,root:{getComponentsInChildren:()=>views},camera:{camera:{screenToWorld(out,p){Object.assign(out,p);}}}};
const native=new NativeUI(world);views=[native];
const g={UIManager:{ins:ui}};
const mods={context:{CompBattleContext:class{}},subdue:{UISubdueBattle:NativeUI},cfg:{SkillBookCfg:{getById:id=>({name:'测试天书'})}}};
const ctx={Date:{now:()=>now}};vm.createContext(ctx);vm.runInContext(source+';this.factory=createPveAssistOverlay',ctx);
const api=ctx.factory(g,cc,mods),b={world,chains:new Map(),shijue:false};
let config={enabled:true,shijue:true,zhongkui:{enabled:true,show_monsters:true,monster_count:5,unlock_speed:true}};
const helpers={now:()=>0,running:()=>true,blockedReason:()=>''};
function update(){api.update(b,config,helpers);}
function find(name){function walk(n){if(n.name===name && n.isValid)return n;for(const c of n.children){const r=walk(c);if(r)return r;}}return walk(host);}
function click(name){const n=find(name);assert(n && n.active,name);n.handlers.start({});n.handlers.end({});}
function monster(id,phase){return {uuid:id,name:'monster',compMonster:{phase:7110201+phase,config:{name:'妖物'+id}},compLife:{current:100,max:200},compCharacterNodeView:{node:{isValid:true,layer:1,worldPosition:{x:600+id,y:400}}}};}
context.pickupMonsters=[monster(1,3),...Array.from({length:7},(_,i)=>monster(i+2,1)),monster(20,5)];
update();assert(native.speedUpNode.active,'native icon must be visible before 15 casts');assert.deepEqual(Array.from(native.getSpeedUpConfig()),[0,3]);
assert.equal(world.battleTime.timeScale,1,'unlock must not auto-switch speed');
assert.equal(api.snapshot().monsters.length,5);assert(api.snapshot().monsters.every(m=>m.wave===2));
click('pve.tab.zhongkui');
const paints=paintCount,activations=activationCount;
update();assert.equal(activationCount,activations,'stable refresh must not disable/re-enable Cocos nodes');
assert(paintCount-paints<=5,'only visible arrow geometry needs repainting');
assert(find('pve.monsters.title').active);
const stableActivation=activationCount;
for(let i=0;i<500;i++)update();
assert.equal(activationCount,stableActivation,'500 idle refreshes must not churn renderer activation');
const oldPanel=find('pve.panel');oldPanel.destroy();update();
assert.notEqual(find('pve.panel'),oldPanel,'externally destroyed scene nodes must be recreated, never reused');assert(find('pve.arrow.1').active);
assert(!find('pve.monsters'),'no independent sidebar window');
assert.equal(find('pve.monster.0').parent,find('pve.panel'),'monster list shares the helper panel');
assert(find('pve.monsters.title').children[0].Label.string.includes('第2波'));
const openHeight=find('pve.panel').Transform.height;
click('pve.tab.zhongkui');assert(!find('pve.monsters.title').active);assert(!find('pve.arrow.1').active);
assert(find('pve.panel').Transform.height<openHeight,'clicking selected submenu collapses its contents');
click('pve.tab.zhongkui');
ui.dialog={children:[{active:true,isValid:true}]};update();assert(!find('pve.panel').active && !find('pve.arrow.1').active);
ui.dialog.children=[];update();assert(find('pve.panel').active);
world.battleTime.timeScale=0;update();assert(!find('pve.panel').active);world.battleTime.timeScale=1;update();
const arrow=find('pve.arrow.1');assert(arrow.Graphics.colors.some(c=>c.values[0]===255 && c.values[1]===255));
assert.equal(arrow.position.x,102,'arrow uses camera/UI projection rather than raw battle X');
click('pve.speed');assert.equal(world.battleTime.timeScale,3);click('pve.speed');assert.equal(world.battleTime.timeScale,1);
click('pve.collapse');assert(!api.snapshot().expanded);assert(find('pve.ball').active);assert(!find('pve.monsters.title').active);
click('pve.ball');assert(api.snapshot().expanded);assert(animations>0);
click('pve.tab.chain');click('pve.shijue');assert(b.shijue);click('pve.tab.zhongkui');
const dead=context.pickupMonsters.find(m=>m.uuid===2);dead.compDead={};dead.compLife.current=0;context.pickupMonsters=context.pickupMonsters.filter(e=>e!==dead);update();
assert(api.snapshot().monsters.some(m=>m.id==='2' && m.deadUntil===2000));
now=1999;update();assert(api.snapshot().monsters.some(m=>m.id==='2'));
now=2000;update();assert(!api.snapshot().monsters.some(m=>m.id==='2'));assert.equal(api.snapshot().monsters.length,5);
config={...config,zhongkui:{...config.zhongkui,monster_count:2}};update();assert.equal(api.snapshot().monsters.length,2);
world.options.stageConfig.phase=[7110206,7110202,7110204];update();
assert.equal(api.snapshot().monsters.length,1);assert.equal(api.snapshot().monsters[0].id,'20');assert.equal(api.snapshot().monsters[0].wave,1,'wave ordering comes from stage config, not numeric ID');
config={...config,zhongkui:{...config.zhongkui,unlock_speed:false}};update();assert.equal(NativeUI.prototype.isSpeedUpVisible,original);assert.equal(NativeUI.prototype.getSpeedUpConfig,originalConfig);assert(!native.speedUpNode.active);
g.__e0e1GameOverlaysEnabled=false;update();assert(!find('pve.panel'),'isolation switch removes custom Cocos nodes');
g.__e0e1GameOverlaysEnabled=true;update();assert(find('pve.panel'));
world.options.battleData.type=26;update();assert(!find('pve.panel'));assert.equal(NativeUI.prototype.isSpeedUpVisible,original);
api.destroy();console.log('PASS PvE-only ball/menu/animation, native 3x unlock/restore, lowest-wave selection, HP, projected outlined arrows, death 2s retention, count, cleanup; no network/game actions');
