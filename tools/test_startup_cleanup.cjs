const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
let now=0;
const context={Date:{now:()=>now}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('package/plugin_manager/startup_cleanup.js','utf8'),context);
const cfg={MainUI:{id:'MainUI'},GuideUI:{id:'GuideUI'}};
const ui={viewParams:{},viewQueue:[],findOpen:()=>({})};
const g={CommonUICfgId:cfg,UIManager:{ins:ui},console:{info(){}}};
let closed=0;
const screen={view:{},close(){closed++;}};
screen.view.btn_close={node:{isValid:true,activeInHierarchy:true},clickCallback:screen.close,cbTarget:screen};
ui.viewParams.ad={showing:true,cfg:{id:'StitchSoulFirstFaceUI'},ui:screen};
assert.equal(context.dismissStartupPage(g).ready,false);
assert.equal(closed,1);
context.dismissStartupPage(g);assert.equal(closed,1,'must not click twice during closing animation');
delete ui.viewParams.ad;
assert.equal(context.dismissStartupPage(g).ready,false);
now=2001;assert.equal(context.dismissStartupPage(g).ready,true);
// The Python startup grace period can still recognize a first-face arriving
// after the initial hall handoff, without treating ordinary user pages as ads.
const delayed={view:{},close(){closed++;}};
delayed.view.btn_close={node:{isValid:true},clickCallback:delayed.close,cbTarget:delayed};
ui.viewParams.delayed={showing:true,cfg:{id:'LateFirstFaceUI'},ui:delayed};
assert.equal(context.dismissStartupPage(g).pendingStartup,true);assert.equal(closed,2);
delete ui.viewParams.delayed;
ui.viewParams.other={showing:true,cfg:{id:'PaymentConfirm'},ui:screen};
assert.equal(context.dismissStartupPage(g).ready,false);assert.equal(closed,2);
assert.notEqual(context.dismissStartupPage(g).pendingStartup,true);
ui.viewParams={ad:{showing:true,cfg:{id:'StitchSoulFirstFaceUI'},ui:{view:{btn_close:{node:{},clickCallback(){throw Error('wrong handler');}}},close(){}}}};
assert.match(context.dismissStartupPage(g).message,/未核实/);
ui.viewParams={};ui.viewQueue=[{}];now=10000;
assert.equal(context.dismissStartupPage(g).ready,false,'queued activities must finish before handoff');
// No first-face page is required: an empty, stable hall is sufficient.
ui.viewQueue=[];delete g.__e0e1StartupCleanup;now=20000;
assert.equal(context.dismissStartupPage(g).ready,false);
now+=2000;assert.equal(context.dismissStartupPage(g).ready,true);
// Reproduce the live hall: inactive GuideUI + MainUI + persistent treasure
// side tip, whose cancel button is hidden. No side-tip button is touched.
for(const cancelActive of [false,true]) {
  delete g.__e0e1StartupCleanup;
  let sideClosed=0,goto=0;
  const side={view:{},close(){sideClosed++;}};
  side.view.btn_cancel={node:{isValid:true,activeInHierarchy:cancelActive},clickCallback:side.close,cbTarget:side};
  side.view.btn_goto={node:{},clickCallback(){goto++;},cbTarget:side};
  ui.viewParams={guide:{showing:true,cfg:cfg.GuideUI,ui:{view:{node_guideRoot:{active:false}}}},
    main:{showing:true,cfg:cfg.MainUI,ui:{}},side:{showing:true,cfg:{id:'TreasureActionSideTipUI'},ui:side}};
  assert.equal(context.dismissStartupPage(g).ready,false);
  now+=2000;assert.equal(context.dismissStartupPage(g).ready,true);
  assert.equal(sideClosed,0);assert.equal(goto,0);
  ui.viewParams.unknown={showing:true,cfg:{id:'PaymentConfirm'},ui:side};
  assert.match(context.dismissStartupPage(g).message,/手动关闭/);
  assert.equal(sideClosed,0);assert.equal(goto,0);
}
console.log('PASS native close bindings, no repeat, no-first-face hall, persistent side-tip regression, unknown dialogs and startup queue');
