// 三尸自动合成的游戏侧操作。与日常任务无关，单独一份运行时。
// 只做两件事：按（种类×品质）统计可合成数量，以及执行一次二合一。
//
// 与日常任务那套最大的区别：连续合成期间不回主界面。
// h.open() 在页面未打开时会先 home()，那是日常任务"每个操作完回大厅"的机制，
// 这里只在批次开始时导航一次，之后复用已经打开的合成页。
//
// 合成不可逆：每一步都带阶段标记，失败时把断在哪一步直接报回上层。

function createDesireRuntime(g,h) {
  const fail=(message,status)=>Object.assign(new Error(message),{status:status||'unavailable'});
  const config=()=>h.configuration();
// 种类（1贪 2嗔 3痴）→ 组内两个子类型。合成硬约束 canDoCompose：type 相同 && quality 相同，心与凡不能互合。
const DESIRE_KINDS={1:[1,4],2:[2,5],3:[3,6]};
async function desireConfigs() {
  const module=await g.System.import('chunks:///_virtual/configs.ts');
  if (!module || !module.ItemCfg || !module.DesireCfg || !module.ComposeCfg) throw fail('三尸配置表未加载');
  return {ItemCfg:module.ItemCfg,DesireCfg:module.DesireCfg,ComposeCfg:module.ComposeCfg};
}
let desireModuleCache=null;
async function desireModule() {
  // 不依赖界面是否打开：三尸模块是单例，优先按官方入口取，取到就缓存。
  if (desireModuleCache) return desireModuleCache;
  const manager=await g.System.import('chunks:///_virtual/module-manager.ts');
  const getter=manager && (manager.GET_MODULE || manager.default);
  // ModuleLocalType 在 module-manager 与 base-module 两处都可能导出，DEASIRE 是官方拼写。
  let Type=manager && manager.ModuleLocalType;
  if (!Type) Type=(await g.System.import('chunks:///_virtual/base-module.ts')).ModuleLocalType;
  const key=Type && (Type.DEASIRE!==undefined?'DEASIRE':'DESIRE');
  if (getter && Type && key) return (desireModuleCache=getter(Type[key]));
  const {cfg}=config();
  const screen=cfg.DesireUI?h.ui().findOpen(cfg.DesireUI):null;
  if (screen && screen.module) return (desireModuleCache=screen.module);
  throw fail('三尸模块入口未解析');
}
// 可合成的品质档：ComposeCfg.quality 是目标品质，材料品质 = quality - 1。
function composableQualities(ComposeCfg) {
  const set=new Set();
  (ComposeCfg.list||[]).forEach(row=>{ const q=Number(row.quality)-1; if(Number.isFinite(q)) set.add(q); });
  return set;
}
// 与游戏自身口径一致：locked 与已镶嵌（planInfo 非空）都不参与合成。
function desireCandidates(ItemCfg,DesireCfg,ComposeCfg,type,quality) {
  const bag=g.ROLE && g.ROLE.desire && g.ROLE.desire.bag;
  if (!bag || typeof bag.forEach!=='function') throw fail('三尸背包不可用');
  const composable=composableQualities(ComposeCfg);
  const out=[];
  bag.forEach((item,uuid)=>{
    if (!item || item.locked) return;
    if (item.planInfo && typeof item.planInfo.size==='number' && item.planInfo.size>0) return;
    const cfgId=Number(item.cfgId);
    const itemCfg=ItemCfg.getById(cfgId), desireCfg=DesireCfg.getById(cfgId);
    if (!itemCfg || !desireCfg) return;
    if (Number(itemCfg.quality)!==Number(quality) || Number(desireCfg.type)!==Number(type)) return;
    if (!composable.has(Number(itemCfg.quality))) return;
    out.push({uuid,cfgId,num:Number(item.num)>0?Number(item.num):1});
  });
  return out;
}
// 取两件：优先两个不同 uuid；只有单个堆叠且 num>=2 时才复用同一 uuid（服务端语义未确认，故标记出来）。
async function desirePickPair(type,quality) {
  const {ItemCfg,DesireCfg,ComposeCfg}=await desireConfigs();
  const list=desireCandidates(ItemCfg,DesireCfg,ComposeCfg,type,quality);
  if (list.length>=2) return {picks:[{uuid:list[0].uuid,cfgId:list[0].cfgId},{uuid:list[1].uuid,cfgId:list[1].cfgId}],sameUuid:false};
  if (list.length===1 && list[0].num>=2)
    return {picks:[{uuid:list[0].uuid,cfgId:list[0].cfgId},{uuid:list[0].uuid,cfgId:list[0].cfgId}],sameUuid:true};
  return null;
}
// 按（种类×品质）统计可用数量；堆叠按 num 累加（官方 getGemsCanPutIn 会把同一堆叠推多次）。
async function desireGroupCounts() {
  const {ItemCfg,DesireCfg,ComposeCfg}=await desireConfigs();
  const bag=g.ROLE && g.ROLE.desire && g.ROLE.desire.bag;
  if (!bag || typeof bag.forEach!=='function') throw fail('三尸背包不可用');
  const composable=composableQualities(ComposeCfg);
  const groups=new Map();
  const skipped={locked:0,embedded:0,uncomposable:0};
  bag.forEach((item,uuid)=>{
    if (!item) return;
    if (item.locked) { skipped.locked++; return; }
    if (item.planInfo && typeof item.planInfo.size==='number' && item.planInfo.size>0) { skipped.embedded++; return; }
    const cfgId=Number(item.cfgId);
    const itemCfg=ItemCfg.getById(cfgId), desireCfg=DesireCfg.getById(cfgId);
    if (!itemCfg || !desireCfg) return;
    const quality=Number(itemCfg.quality), type=Number(desireCfg.type);
    if (!Number.isFinite(quality) || !Number.isFinite(type) || !composable.has(quality)) { skipped.uncomposable++; return; }
    const key=type+':'+quality, group=groups.get(key)||{type,quality,count:0,uuids:[]};
    group.count+=Number(item.num)>0?Number(item.num):1;
    group.uuids.push(uuid);
    groups.set(key,group);
  });
  const rows=Array.from(groups.values()).map(r=>({type:r.type,quality:r.quality,count:r.count,
    distinct:r.uuids.length,pairs:Math.floor(r.count/2)}));
  rows.sort((a,b)=>a.type-b.type||a.quality-b.quality);
  rows.skipped=skipped;
  return rows;
}
async function desireBagStats() {
  const {ComposeCfg}=await desireConfigs();
  const rows=await desireGroupCounts();
  const rates=(ComposeCfg.list||[]).filter(r=>Number(r.num)===2).map(r=>({
    quality:Number(r.quality)-1,target:Number(r.quality),ratio:Number(r.ratio),returned:Number(r.returned)}));
  rates.sort((a,b)=>a.quality-b.quality);
  const names={}, codes={};
  try {
    const rh=(await g.System.import('chunks:///_virtual/role-helper.ts')).roleHelper;
    for (let q=1;q<=8;q++) names[q]=String((rh && rh.getRareName && rh.getRareName(q)) || q);
  } catch (e) { /* 拿不到就退回数字 */ }
  try {
    const Type=(await g.System.import('chunks:///_virtual/types-common.ts')).DesireType;
    if (Type) Object.keys(Type).forEach(k=>{ if (Number.isFinite(Number(k))) codes[Number(k)]=Type[k]; });
  } catch (e) { /* 拿不到就退回数字 */ }
  return {confirmed:true,groups:rows,rates,qualityNames:names,typeCodes:codes,
    composeCnt:Number(g.ROLE.desire && g.ROLE.desire.composeCnt)||0};
}
async function desireSwitchTab(screen,index) {
  if (typeof h.switchTab==='function') return await h.switchTab(screen,index);
  const {Button}=config();
  if (screen.curSelectedIndex!==index) await h.click(screen.view.btnTabGroup.children[index].getComponent(Button));
  return await h.wait(()=>screen.pages && screen.pages[index],'UI页签未加载');
}
async function composePage() {
  const {cfg}=config();
  const screen=await h.open(cfg.DesireUI);
  const page=await desireSwitchTab(screen,1);
  await h.wait(()=>page && (!page.node || page.node.activeInHierarchy!==false),'三尸合成页未就绪');
  return page;
}
// 不抛异常的短轮询：用来"看一眼会不会弹确认框"，等不到就当没弹。
function waitMaybe(predicate, ms) {
  const end=Date.now()+(ms||2000);
  return (async ()=>{
    while (true) {
      const value=predicate();
      if (value) return value;
      if (Date.now()>=end) return null;
      await new Promise(resolve=>setTimeout(resolve,120));
    }
  })();
}
function composeButton(page) {
  const view=page && page.view || {};
  const {cc}=config();
  const usable=b=>b && (!b.node || b.node.active!==false)
    && b.interactable!==false && b.enabledInHierarchy!==false;
  // 先按"绑定了合成回调"找，别赌 view.btn_compose 一定存在：
  // 官方页面里按钮可能挂在子组件上，字段名也可能变。
  const named=(page && page.node && typeof page.node.getComponentsInChildren==='function')
    ? (page.node.getComponentsInChildren(cc.Button)||[]) : [];
  const bound=named.filter(b=>{
    const cb=b.clickCallback;
    if (typeof cb==='function' && (cb===page.onComposeClick || String(cb.name||'').includes('Compose'))) return true;
    return (b.clickEvents||[]).some(e=>e && String(e.handler||'').includes('Compose'));
  });
  for (let i=0;i<bound.length;i++) if (usable(bound[i])) return bound[i];
  const order=page && page.hasComposeAll?[view.btn_compose2,view.btn_compose]:[view.btn_compose,view.btn_compose2];
  for (let i=0;i<order.length;i++) if (usable(order[i])) return order[i];
  for (let i=0;i<named.length;i++) if (usable(named[i])) return named[i];
  return null;
}
async function desireProbe() {
  // 纯观察：把合成链路上的每一环都报出来，失败时一眼能看出断在哪。
  const {cfg,defs}=config();
  const out={confirmed:true};
  out.cfg={DesireUI:!!cfg.DesireUI,CommonConfirm:!!cfg.CommonConfirm,Congrats:!!cfg.Congrats};
  out.defs={DesireService:!!(defs&&defs.DesireService),
    composeGem:!!(defs&&defs.DesireService&&typeof defs.DesireService.composeGem==='function')};
  let module=null;
  try { module=await desireModule(); }
  catch (e) { out.moduleError=String(e && e.message || e); }
  out.module=!!module;
  if (module) out.moduleApi={putInGem:typeof module.putInGem,getPutInGems:typeof module.getPutInGems,
    clearPutInGems:typeof module.clearPutInGems,composeGem:typeof module.composeGem};
  const bag=g.ROLE && g.ROLE.desire && g.ROLE.desire.bag;
  out.bag={present:!!bag,size:bag && typeof bag.size==='number'?bag.size:null};
  try { out.groups=await desireGroupCounts(); }
  catch (e) { out.groupsError=String(e && e.message || e); }
  const screen=cfg.DesireUI?h.ui().findOpen(cfg.DesireUI):null;
  out.screenOpen=!!screen;
  if (screen) {
    const page=screen.pages && screen.pages[1];
    const state=b=>{
      if (!b) return null;
      return {active:b.node?b.node.active!==false:null,
              interactable:b.interactable!==false,
              enabled:b.enabledInHierarchy!==false,
              clickable:b.clickInteractable!==false};
    };
    out.page={present:!!page,hasComposeAll:!!(page&&page.hasComposeAll),
      curSelectedIndex:screen.curSelectedIndex,
      hasTabGroup:!!(screen.view&&screen.view.btnTabGroup),
      buttons:page&&page.view?{btn_compose:state(page.view.btn_compose),
        btn_compose2:state(page.view.btn_compose2)}:null,
      slots:module&&typeof module.getPutInGems==='function'?module.getPutInGems():null};
    if (cfg.CommonConfirm) out.confirmOpen=!!h.ui().findOpen(cfg.CommonConfirm);
  }
  return out;
}
// 种类过滤器只在背包页上，合成页读的是 module.getPutInGems()，与过滤器无关。
// 设它纯粹是为了让界面和本次批次一致（用户能看到自己在合哪一类），失败不影响合成。
function setDesireFilter(screen,kind) {
  const {cc}=config();
  const bag=screen && screen.view && screen.view.bag;
  if (!bag || !bag.btn_switch_group) throw new Error('未找到三尸种类过滤器');
  const root=bag.btn_switch_group;
  let toggles=root.children && root.children[0] ? root.children[0].getComponentsInChildren(cc.Toggle) : [];
  if (!toggles || toggles.length<2) toggles=root.getComponentsInChildren(cc.Toggle);
  if (!toggles || toggles.length<2) throw new Error('种类过滤器 Toggle 未解析');
  const index=Number(kind)||0;
  for (let i=0;i<toggles.length;i++) toggles[i].isChecked=(i===index);
  if (typeof bag.updatebag==='function') bag.updatebag();
  else if (typeof bag.onSwitchClick==='function') bag.onSwitchClick();
  else throw new Error('背包刷新入口未解析');
}
// 批次内只在开始时导航一次。h.open() 在页面未打开时会先 home()，
// 那是日常任务"每个操作完回到主界面"的机制，连续合成时用它就会来回弹。
function currentComposePage() {
  const {cfg}=config();
  if (!cfg.DesireUI) return null;
  const screen=h.ui().findOpen(cfg.DesireUI);
  const page=screen && screen.pages && screen.pages[1];
  return page && (!page.node || page.node.activeInHierarchy!==false) ? page : null;
}
async function desireOpen(kind) {
  const page=await composePage();
  const {cfg}=config();
  const screen=h.ui().findOpen(cfg.DesireUI);
  if (screen && kind) {
    try { setDesireFilter(screen,kind); }
    catch (e) { if (h.log) h.log('三尸种类过滤器未设置（不影响合成）：'+(e && e.message || e)); }
  }
  return {confirmed:true, hasComposeAll: !!(page && page.hasComposeAll)};
}
async function desireClose() {
  await h.home();
  return {confirmed:true};
}
async function composeOnce(type,quality) {
  // 每一步都打标记：失败时把"断在哪一步"直接带回面板，不用靠猜。
  let stage='取三尸模块';
  try {
  const {cfg,defs,data}=config();
  const module=await desireModule();
  stage='定位合成页';
  // 不调 composePage()：批次开始已经打开过，这里只找现成的页面，找不到就报错让批次重开。
  const page=currentComposePage();
  if (!page) throw fail('三尸合成页未打开','unavailable');
  stage='选两件材料';
  const found=await desirePickPair(type,quality);
  if (!found) throw fail('没有可用于合成的两件三尸','rejected');
  const {picks,sameUuid}=found;
  if (typeof module.putInGem!=='function' || typeof module.getPutInGems!=='function') throw fail('三尸模块接口未核实');
  stage='填入合成槽';
  // 直接填槽，不点背包列表：onComposeClick 只读 getPutInGems()，与列表怎么填的无关；
  // 官方自己的「直接放入」也是 module.putInAllGem(...)，同一条路径。
  module.clearPutInGems();
  module.putInGem(picks[0]);
  module.putInGem(picks[1]);
  const slots=()=>module.getPutInGems()||[];
  await h.wait(()=>slots().filter(v=>Number(v)>0).length===2,'合成槽未填入两件三尸');
  stage='找合成按钮';
  const button=composeButton(page);
  if (!button) throw fail('合成按钮未核实');
  const opened=()=>cfg.CommonConfirm?h.ui().findOpen(cfg.CommonConfirm):null;
  const cleared=()=>slots().every(v=>Number(v)===0);
  stage='点合成并等待回执';
  // 点合成后 UI 会播 spine 再 yield wait(1) 才发请求，默认 8s 不够，给 30s。
  const resp=await h.observe([defs.DesireService.composeGem], async ()=>{
    await h.click(button,{waitCompletion:false});
    // 不去猜品质阈值：确认框弹出来就点掉，没弹就说明这次不需要确认。
    const confirm=await waitMaybe(()=>opened(),1500);
    if (confirm) {
      const ok=confirm.view && (confirm.view.btn_confirm || confirm.view.btn_ok);
      if (!ok) throw fail('合成确认框没有已核实的确认按钮');
      await h.click(ok,{waitCompletion:false});
    }
  }, ()=>cleared() || !!(cfg.Congrats && h.ui().findOpen(cfg.Congrats)), 30000);
  // 确认框不在 blockedViews 白名单里，留着会让后续所有写操作和 home() 都被拒。
  stage='关闭确认框';
  const stuck=opened();
  if (stuck) await h.click(stuck.view.btn_close || stuck.view.btn_cancel,{waitCompletion:false});
  if (cfg.CommonConfirm) await h.wait(()=>!opened(),'合成确认框未关闭');
  stage='关闭奖励页';
  await h.dismissRewards(resp && resp.items && resp.items.length>0);
  stage='回读库存';
  const rates=(data && data.ComposeCfg && data.ComposeCfg.list)||[];
  const row=rates.filter(r=>Number(r.quality)===Number(quality)+1 && Number(r.num)===2)[0];
  return {confirmed:true, success: resp && resp.result===true, type:Number(type), quality:Number(quality),
    itemIds:picks.map(p=>Number(p.cfgId)), sameUuid:!!sameUuid,
    ratio:row?Number(row.ratio)/100:null, returned:row?Number(row.returned):null,
    items:(resp && Array.isArray(resp.items))?resp.items.length:0,
    groups:(await desireGroupCounts())};
  } catch (e) {
    // 保留原始 status（unavailable/rejected 才能被上层判成"没执行"），只补上阶段与原文。
    const status=(e && e.status) || 'uncertain';
    throw Object.assign(new Error('三尸合成失败（阶段：'+stage+'）：'+(e && e.message || e)), {status});
  }
}
  return {async dispatch(op,args) {
    if(op==='desire_compose_probe')return await desireProbe();
    if(op==='desire_bag_stats')return await desireBagStats();
    if(op==='desire_compose_open')return await desireOpen(args.kind);
    if(op==='desire_compose_once')return await composeOnce(args.type,args.quality);
    if(op==='desire_compose_close')return await desireClose();
    throw fail('未知三尸操作');
  }};
}
