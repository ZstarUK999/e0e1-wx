const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
class Transform{setContentSize(w,h){this.width=w;this.height=h;}}
class Label{set string(value){this.writes=(this.writes||0)+1;this.value=value;}get string(){return this.value;}}
Label.CacheMode={CHAR:2};
Label.Overflow={CLAMP:1,SHRINK:2};
class Graphics{roundRect(){}fill(){}clear(){}}
class Node{
 constructor(name){this.name=name;this.children=[];this.parts=new Map();this.events={};this.isValid=true;this.layer=1;this.position={x:0,y:0};}
 addComponent(Type){const value=new Type();value.node=this;this.parts.set(Type,value);return value;}
 getComponent(Type){return this.parts.get(Type);}
 addChild(child){child.parent=this;this.children.push(child);}
 setPosition(x,y){this.position={x,y};}
 on(name,fn){this.events[name]=fn;}
 destroy(){this.isValid=false;this.children.slice().forEach(n=>n.destroy());if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}
}
Node.EventType={TOUCH_START:'start',TOUCH_MOVE:'move',TOUCH_END:'end'};
const cc={Node,UITransform:Transform,Label,Graphics,BlockInputEvents:class{},Color:class{},HorizontalTextAlignment:{CENTER:1},view:{getVisibleSize:()=>({width:750,height:1334})}};
const host=new Node('system'),timers=new Map();let next=0,now=1000;
const g={UIManager:{ins:{system:host}},System:{import:async()=>cc}};
const box={Date:{now:()=>now},setInterval(fn){timers.set(++next,fn);return next;},clearInterval(id){timers.delete(id);}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../package/plugin_manager/automation_overlay.js'),'utf8'),box);
const overlay=box.createAutomationOverlay(g);
function find(name,node=host){if(node.name===name)return node;for(const child of node.children){const value=find(name,child);if(value)return value;}return null;}
(async()=>{
 await overlay.update({run_id:'one',active:true,task:'三尸盗掠扫描'});
 assert.equal(timers.size,1);assert.equal(host.children.length,1);
 assert.match(find('当前操作').getComponent(Label).string,/三尸盗掠扫描/);
 overlay.setOperation('等待战斗结算');assert.match(find('当前操作').getComponent(Label).string,/等待战斗结算/);
 const panel=host.children[0];
 assert.equal(find('托管状态（拖动）').getComponent(Transform).width,396,'Label initialization must preserve title width');
 const shortHeight=panel.getComponent(Transform).height;
 const longOperation='等待当前战斗结算后收取所有奖励并重新开启下一轮墓藏，正在确认返回主界面后继续处理剩余任务';
 overlay.setOperation(longOperation);
 const detailNode=find('当前操作'),detailLabel=detailNode.getComponent(Label);
 assert.equal(detailLabel.string.replace(/\n/g,''),'三尸盗掠扫描'+longOperation,'wrapped text must remain complete');
 assert(panel.getComponent(Transform).height>shortHeight,'long content expands panel');
 assert.equal(detailNode.getComponent(Transform).height,detailLabel.string.split('\n').length*detailLabel.lineHeight+8);
 const exitNode=find('退出托管');
 assert(detailNode.position.y-detailNode.getComponent(Transform).height/2>exitNode.position.y+17,'button must remain below text');
 assert.equal(find('托管状态（拖动）').getComponent(Label).enableWrapText,false);
 overlay.setOperation('等待战斗结算');
 const before=panel.position.y;
 find('托管状态（拖动）').events.move({getUIDelta:()=>({x:10,y:-20})});assert.equal(panel.position.y,before-20);
 for(let i=0;i<20;i++)await overlay.update({run_id:'one',active:true,task:'三尸盗掠扫描'});
 assert.equal(host.children.length,1);assert.equal(timers.size,1);
 const text=find('当前操作').getComponent(Label),writes=text.writes;
 assert.equal(text.cacheMode,Label.CacheMode.CHAR);
 for(let i=0;i<100;i++)for(const fn of timers.values())fn();
 assert.equal(text.writes,writes,'unchanged text must not rebuild');
 find('退出托管').events.end({});assert.ok(overlay.shouldStop());
 await overlay.update({run_id:'one',active:true});assert.ok(overlay.shouldStop(),'stale active updates cannot clear a stop request');
 await overlay.update({run_id:'one',active:false});assert.equal(timers.size,0);assert.equal(host.children.length,0);
 await overlay.update({run_id:'two',active:true});assert.equal(overlay.shouldStop(),false);
 now+=13000;for(const fn of timers.values())fn();assert.ok(overlay.shouldStop(),'lost control connection pauses automation');
 await overlay.update({run_id:'three',active:true,phase:'waiting',task:'',next_task:'法器盗掠扫描',next_check_at:now+65000});
 assert.match(find('托管状态（拖动）').getComponent(Label).string,/正在等待/);
 assert.match(find('当前操作').getComponent(Label).string,/法器盗掠扫描/);
 assert.match(find('当前操作').getComponent(Label).string,/1分5秒后检查/);
 now+=1000;for(const fn of timers.values())fn();
 assert.match(find('当前操作').getComponent(Label).string,/1分4秒后检查/);
 await overlay.update({run_id:'three',active:true,phase:'waiting',next_task:'',next_check_at:null,status:'当前没有启用的定时任务'});
 assert.match(find('当前操作').getComponent(Label).string,/没有启用/);
 g.__e0e1GameOverlaysEnabled=false;
 await overlay.update({run_id:'hidden',active:true});
 assert.equal(host.children.length,0);assert.equal(timers.size,1,'hidden mode retains the safety lease watchdog');
 now+=13000;for(const fn of timers.values())fn();assert(overlay.shouldStop());
 g.__e0e1GameOverlaysEnabled=true;await overlay.update({run_id:'restored',active:true});assert.equal(host.children.length,1);
 overlay.destroy();assert.equal(timers.size,0);assert.equal(host.children.length,0);
 console.log('PASS automation status, drag, stop latch, restart, lease expiry and complete timer/node cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
