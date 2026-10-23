// Observe only the native duplicate-login modal. Never treat network loss as a kick.
async function configureWechatReconnect(g,enabled) {
  const old=g.__e0e1WechatReconnect;
  if(!enabled){
    if(old && old.owner.showModal===old.wrapper)old.owner.showModal=old.original;
    delete g.__e0e1WechatReconnect;return {kicked:false};
  }
  if(old && old.owner.showModal===old.wrapper)return {kicked:!!old.event,event:old.event,restarted:old.restarted};
  const {PlatformManager}=await g.System.import('chunks:///_virtual/platform-manager.ts'),owner=PlatformManager && PlatformManager.ins;
  if(!owner || typeof owner.showModal!=='function' || typeof owner.exitGame!=='function')return {kicked:false,unavailable:true};
  const state={owner,original:owner.showModal,event:null,restarted:false};
  state.wrapper=function(...args){
    if(args[0]==='账号重复登录' && !state.event){
      state.event=String(Date.now())+'-'+Math.random().toString(36).slice(2);
      if(g.console)g.console.info('[plugin.kicked]',state.event);
    }
    return state.original.apply(this,args);
  };
  owner.showModal=state.wrapper;g.__e0e1WechatReconnect=state;
  return {kicked:false};
}

function restartWechatAfterKick(g,event,mode) {
  // Old desktop processes reload this script from disk, but cannot perform the external launch.
  if(mode!=='wechat-recent')return false;
  const state=g.__e0e1WechatReconnect;
  if(!state || state.event!==event || state.restarted)return false;
  state.restarted=true;
  // Acknowledge once, then close through the native exit action.
  // The desktop plugin opens the WeChat recent-use UI independently.
  setTimeout(()=>state.owner.exitGame(),100);
  return true;
}
