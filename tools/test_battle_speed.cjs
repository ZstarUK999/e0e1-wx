const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync(require('path').join(__dirname,'../package/plugin_manager/battle_assist_runtime.js'),'utf8');
const part=source.slice(source.indexOf('  function speedEligible'),source.indexOf('  // n + min'));
let config={enabled:true,auto_speed:true},speedViews=new Map(),speedTypes=new Set([1,2,3,6,13,21,23,27]);
const world={options:{battleData:{type:1}},battleTime:{timeScale:1,baseTimeScale:1},battleState:{curState:1}};
const buttons=[1,1.3,1.6].map(value=>{const lock={active:true},selected={active:false},label={node:{},string:'old'};const button={node:{},clickCallback:()=>{},cbTarget:null,addClick(f,t){this.clickCallback=f;this.cbTarget=t;}};return {button,label,lock,selected,getComponents:()=>[button],getComponentsInChildren:()=>[label],getChildByName:n=>n==='lock'?lock:selected};});
const view={node:{},battleWorld:world,view:{node_gameScale:{active:false,children:buttons}},setSpeed(){throw Error('native locked');},refreshSpeedNode(){buttons[1].lock.active=buttons[2].lock.active=true;}};
const original=view.setSpeed,callbacks=buttons.map(b=>b.button.clickCallback);
const context={config,speedViews,speedTypes,valid:n=>!!n&&n.isValid!==false,number:Number,cc:{Component:class{},Label:class{}},g:{UIManager:{ins:{viewParams:{battle:{ui:view}},root:{getComponentsInChildren:()=>[]}}}},modules:{helper:{isFrameSyncType:()=>false,isServerResultPvpType:()=>false},types:{BattleState:{Running:1}},speedUi:{UIBattleBase:class{}}}};
vm.createContext(context);vm.runInContext(part+';this.sync=syncSpeed',context);
const sync=()=>context.sync([world]);sync();assert.equal(world.battleTime.timeScale,1);assert.equal(buttons[2].lock.active,false);assert.equal(buttons[2].label.string,'3倍速');assert.equal(buttons[2].active,true);
buttons[2].button.clickCallback();assert.equal(world.battleTime.timeScale,3);
buttons[0].button.clickCallback();sync();assert.equal(world.battleTime.timeScale,1);assert.equal(world.battleTime.baseTimeScale,1);
buttons[1].button.clickCallback();sync();assert.equal(world.battleTime.timeScale,1.3);
world.isPaused=true;world.battleTime.timeScale=0;sync();buttons[2].button.clickCallback();assert.equal(world.battleTime.timeScale,0);
world.isPaused=false;world.battleTime.timeScale=.4;sync();assert.equal(world.battleTime.timeScale,.4);
config.auto_speed=false;sync();assert.equal(view.setSpeed,original);assert.equal(view.view.node_gameScale.active,false);buttons.forEach((b,i)=>assert.equal(b.button.clickCallback,callbacks[i]));assert.equal(world.battleTime.baseTimeScale,1.3);
config.auto_speed=true;world.options.isReplay=true;sync();assert.equal(speedViews.size,0);
world.options.isReplay=false;world.options.battleData.type=24;sync();assert.equal(speedViews.size,0);
console.log('PASS unlock only, manual 3x/1x/1.3x persistence, pause, slowdown, disable restoration, replay and PvP exclusion');

// Sprite-only prefabs must get an explicit caption, without changing speed.
world.options.battleData.type=1;
class Node {constructor(){this.layer=0;}addComponent(Type){return Type.name==='Label'?{}:{setContentSize(){}};}setPosition(){}destroy(){this.destroyed=true;}}
context.cc.Node=Node;context.cc.Color=class{};context.cc.UITransform=class UITransform{};context.cc.Label=class Label{};
buttons[2].getComponentsInChildren=()=>[];buttons[2].addChild=n=>{buttons[2].caption=n;};buttons[2].getComponent=()=>({height:50});
const before=world.battleTime.timeScale;sync();assert.ok(buttons[2].caption);assert.equal(world.battleTime.timeScale,before);
config.auto_speed=false;sync();assert.equal(buttons[2].caption.destroyed,true);
console.log('PASS registry discovery, sprite-only caption and caption cleanup');
