// 来自抖音 0.1.73 的 FirstFaceMgr / NATIONAL_FESTIVAL 开屏链路。
// 只触发已绑定 close 的按钮，不点击前往、领取或今日不再显示。
function dismissStartupPage(g) {
  const ui=g.UIManager && g.UIManager.ins,cfg=g.CommonUICfgId;
  if(!ui || !cfg || !ui.findOpen(cfg.MainUI))return {ready:false,message:'等待大厅加载'};
  const state=g.__e0e1StartupCleanup || (g.__e0e1StartupCleanup={quiet:null,clicks:new WeakSet()});
  // 摸金侧提示是大厅常驻提示，现场 btn_cancel 还可能隐藏；它不是开屏门槛。
  const background=new Set(['MainUI','Debug','MoveDebug','TipsUI','PowerUp','FightPowerUp','TreasureActionSideTipUI']);
  const views=Object.values(ui.viewParams || {}).filter(v=>{
    if(!v.showing && !v.loading)return false;
    if(v.cfg===cfg.GuideUI){const root=v.ui && v.ui.view && v.ui.view.node_guideRoot;if(root && root.active===false)return false;}
    return !background.has(v.cfg && v.cfg.id);
  });
  if(!views.length){
    if(ui.viewQueue && ui.viewQueue.length){state.quiet=null;return {ready:false,message:'等待开屏队列'};}
    if(state.quiet===null)state.quiet=Date.now();
    return {ready:Date.now()-state.quiet>=2000,message:'确认大厅稳定'};
  }
  state.quiet=null;
  const param=views[views.length-1],screen=param.ui,id=param.cfg && param.cfg.id || '';
  // 主流程已核对的宣传、签到及特权弹窗；陌生页和战斗/引导交给用户。
  const allowed=/FirstFaceUI$/.test(id) || new Set(['SeasonFaceUI','SeasonStyxFaceUI','SeasonHonorRankLegionRoleListUI','SignDays','FirstCharge','PrivilegeGiftUI','PrivilegeGivingUI','NoticeUI','LimitPackUI']).has(id);
  if(param.loading || !screen || !screen.view)return {ready:false,pendingStartup:allowed,message:'等待开屏页加载：'+id};
  if(!allowed || screen.battleWorld || screen.battleWorldOther)return {ready:false,message:'待手动关闭的开屏页面：'+id};
  const view=screen.view;
  const button=[view.btn_close,view.button_close,view.btn_Close,view.btnClose,screen.closeBtn].find(b=>
    b && b.node && b.node.isValid!==false && b.node.activeInHierarchy!==false &&
    typeof b.clickCallback==='function' && b.clickCallback===screen.close && b.cbTarget===screen);
  if(!button)return {ready:false,pendingStartup:true,message:'开屏页关闭按钮尚未核实：'+id};
  if(state.clicks.has(screen))return {ready:false,pendingStartup:true,message:'等待开屏页关闭：'+id};
  state.clicks.add(screen);
  button.clickCallback.call(button.cbTarget);
  if(g.console)g.console.info('[plugin.ui]','关闭开屏活动：'+id);
  // WeakSet 不持有已销毁界面；同一关闭请求不会重复发送。
  return {ready:false,pendingStartup:true,message:'已点击开屏页关闭按钮：'+id};
}
