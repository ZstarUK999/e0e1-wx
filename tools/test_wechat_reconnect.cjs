const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('node:assert/strict');
const code=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/wechat_reconnect.js'),'utf8');
(async()=>{
 let scheduled=[],exits=0,modals=0;
 const owner={showModal(){assert.equal(this,owner);modals++;return 'native';},exitGame(){exits++;},restartGame(){throw new Error("internal restart must never run");}},original=owner.showModal;
 const g={System:{import:async()=>({PlatformManager:{ins:owner}})},console:{info(){}}};
 const ctx={setTimeout:f=>scheduled.push(f)};vm.runInNewContext(code+';this.configure=configureWechatReconnect;this.restart=restartWechatAfterKick;',ctx);
 await ctx.configure(g,true);const wrapper=owner.showModal;await ctx.configure(g,true);assert.equal(owner.showModal,wrapper);
 owner.showModal('连接异常','网络错误');assert(!(await ctx.configure(g,true)).kicked);
 assert.equal(owner.showModal('账号重复登录','其它地方登录'),'native');const event=(await ctx.configure(g,true)).event;
 owner.showModal('账号重复登录','其它地方登录');assert.equal((await ctx.configure(g,true)).event,event,'repeated modal must not reset countdown');
 assert.equal(ctx.restart(g,event),false,'old desktop process must not exit without an external launcher');assert.equal(ctx.restart(g,'wrong','wechat-recent'),false);assert.equal(ctx.restart(g,event,'wechat-recent'),true);assert.equal(ctx.restart(g,event,'wechat-recent'),false);
 assert.equal(exits,0);scheduled[0]();assert.equal(exits,1);assert.equal(modals,3);
 await ctx.configure(g,false);assert.equal(owner.showModal,original);assert(!g.__e0e1WechatReconnect);
 console.log('PASS exact duplicate-login detection, native modal preserved, no generic disconnect trigger, one deferred native exit, no internal restart, disable restores original method');
})().catch(e=>{console.error(e);process.exitCode=1;});
