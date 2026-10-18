// 仅自身正常UI操作：不拼协议、不改战斗/奖励、不编辑方案或交换培养。
function createEnergyRuntime(g, timing) {
  timing = timing || {};
  const timeoutMs = timing.timeoutMs || 8000;
  const pauseMs = timing.pauseMs || 500;
  // 全局设置里的观察延时优先；非法值回退到构造参数。
  function stepDelay() {
    const resident=g.__e0e1PluginRuntime;
    const value=resident && resident.config && resident.config.ui && Number(resident.config.ui.delay_ms);
    return Number.isInteger(value) && value>=0 && value<=5000 ? value : pauseMs;
  }
  const guard = g.__e0e1EnergyGuard || (g.__e0e1EnergyGuard = {busy: false, uncertain: false, pending: false});
  const pause = () => new Promise(resolve => setTimeout(resolve, stepDelay()));
  let cfg, data, roleHelper, shop, cardType, defs, manager, Button, magicTypes, cc;
  const classes = {};
  async function uiClass(module, name) {
    const key=module+':'+name;
    if (!classes[key]) classes[key]=(await g.System.import('chunks:///_virtual/'+module))[name];
    return classes[key];
  }
  const error = (message, status) => Object.assign(new Error(message), {status: status || 'unavailable'});
  async function initialize() {
    if (!g.ROLE || !g.UIManager || !g.System) throw error('游戏未就绪');
    const modules = await Promise.all(['configs.ts','role-helper.ts','shop-helper.ts','define-index.ts','service-manager.ts','button-plus.ts','magic-artifact-types.ts'].map(n=>g.System.import('chunks:///_virtual/'+n)));
    [data] = modules;
    roleHelper = modules[1].roleHelper;
    shop = modules[2].shopHelper;
    cardType = modules[2].cardType;
    defs = modules[3]; manager = modules[4].ServiceManager.ins;
    Button = modules[5].default; magicTypes = modules[6].MagicArtifactPageType;
    cc = await g.System.import('cc');
    cfg = g.CommonUICfgId;
    if (!cfg) cfg = (await g.System.import('chunks:///_virtual/ui-common-cfg.ts')).CommonUICfgId;
  }
  const ui = () => g.UIManager.ins;
  async function wait(predicate, message) {
    const end = Date.now() + timeoutMs;
    while (true) {
      const value = predicate();
      if (value) return value;
      // 观察延时可能大于剩余等待时间；不能因为一次长暂停就判定超时。
      const remaining = end - Date.now();
      if (remaining <= 0) throw error(message, 'uncertain');
      await new Promise(resolve => setTimeout(resolve, Math.min(stepDelay(), remaining)));
    }
  }
  function background(view) {
    if (view.cfg === cfg.GuideUI && cfg.GuideUI) {
      const root = view.ui && view.ui.view && view.ui.view.node_guideRoot;
      return !!root && root.active === false;
    }
    return ['Debug','MoveDebug','TipsUI','PowerUp','FightPowerUp'].some(key=>cfg[key] && view.cfg === cfg[key]);
  }
  function normalPages() {
    return ['AttrUp','GameMethod','Hangup','DesireUI','MagicArtifactUI','PetUI','Setting','MineUI','MineOtherUI','MineOtherMagicArtifactUI','MineListUI','ArenaUI','ChatUI','ChatRecruitUI','MainMoreUI']
      .map(key=>cfg[key]).filter(Boolean);
  }
  function blockedViews() {
    const allowed = [cfg.MainUI, ...normalPages(), cfg.Congrats, cfg.HeroLevelUp].filter(Boolean);
    return Object.values(ui().viewParams || {}).filter(v=> (v.showing || v.loading) &&
      (v.ui && (v.ui.battleWorld || v.ui.battleWorldOther) || !background(v) && !allowed.includes(v.cfg)));
  }
  function blockers() {
    const names=blockedViews().map(v=>String(v.cfg && v.cfg.id || v.cfgId || '未知界面'));
    if (!ui().findOpen(cfg.MainUI)) names.push('MainUI未就绪');
    return names;
  }
  function safe() {
    return blockers().length === 0;
  }
  function uiBusy() {
    return Object.values(ui().viewParams || {}).some(v=>v.ui && (v.ui.busy || (v.ui.pages || []).some(p=>p && p.busy)));
  }
  async function click(control, options) {
    options=options || {};
    const unlock=control && control.Button_btn;
    const button=unlock || control;
    const node=button && (button.node || button);
    if (!node || typeof node.emit!=='function' || button.interactable===false || button.enabledInHierarchy===false || node.activeInHierarchy===false)
      throw error('UI按钮不可点击');
    await wait(()=>!button.continuous && button.clickInteractable!==false, 'UI按钮仍在防连点/等待操作');
    if (g.console) g.console.info('[plugin.ui]', '点击UI：'+String(node.name || '已绑定按钮/列表条目'));
    // UI事件仍执行原绑定；只旁观返回的Promise，不直接调用业务方法。
    const original=button.clickCallback;
    let completion=Promise.resolve();
    const observed=typeof original==='function'?function(...args){
      const result=original.apply(this,args);
      if (result && typeof result.then==='function') {
        guard.callback_count=(guard.callback_count||0)+1;
        completion=Promise.resolve(result).finally(()=>{guard.callback_count--;});
      }
      return result;
    }:null;
    if (observed) button.clickCallback=observed;
    try {
      for (const type of [cc.Node.EventType.TOUCH_START,cc.Node.EventType.TOUCH_END]) {
        const event=cc.EventTouch ? new cc.EventTouch([],true,type) : {type};
        event.target=node;
        node.emit(type,event);
      }
    } finally {
      if (observed && button.clickCallback===observed) button.clickCallback=original;
    }
    if (options.waitCompletion===false) {
      completion.catch(e=>{guard.uncertain=true;if(g.console)g.console.error('[plugin.error]',String(e));});
      await pause();
      return;
    }
    await bounded(completion,'UI回调尚未完成');
    await pause();
    await wait(()=>!uiBusy() && button.clickInteractable!==false,'UI页面回调尚未收尾');
  }
  async function open(which) {
    if (!safe()) throw error('当前存在战斗或其他阻挡界面');
    const existing=ui().findOpen(which);
    if (existing) return existing;
    await home();
    const main=ui().findOpen(cfg.MainUI);
    let control;
    if (which===cfg.GameMethod) control=main.view.button_method;
    else if (which===cfg.MineUI || which===cfg.ArenaUI) {
      await click(main.view.button_method);
      const method=await wait(()=>ui().findOpen(cfg.GameMethod),'玩法页面未打开');
      control=which===cfg.MineUI?method.view.btn_mine:method.view.btn_arena;
    }
    else if (which===cfg.PetUI) control=main.view.button_pet;
    else if (which===cfg.DesireUI) control=main.view.btn_desire;
    else if (which===cfg.Hangup) {
      const Type=await uiClass('main_ui_hang_up_button.ts','main_ui_hang_up_button');
      const component=main.node.getComponentInChildren(Type);
      control=component && component.btn_hang_up;
    } else if (which===cfg.MagicArtifactUI) {
      await click(main.view.button_attrUp);
      const attr=await wait(()=>ui().findOpen(cfg.AttrUp),'属性页面未打开');
      const Type=await uiClass('attr-attr-up.ts','AttrAttrUp');
      const contents=attr.node ? attr.node.getComponentInChildren(Type) : attr;
      const item=await wait(()=>contents && contents.magicArtifactItem,'法器入口未显示');
      const Unlock=await uiClass('common-unlock-button.ts','default');
      control=(item.getComponent && item.getComponent(Unlock)) || item.getComponentInChildren(Unlock);
    } else throw error('没有核实此页面的UI导航按钮');
    await click(control);
    const retained=await wait(()=>ui().find(which),'UI导航未打开目标页面');
    if (retained.waitAfterOpen) await bounded(retained.waitAfterOpen,'页面打开动画未结束');
    return await wait(()=>ui().findOpen(which),'页面尚未显示');
  }
  async function switchTab(screen,index) {
    if (screen.curSelectedIndex!==index) {
      const node=screen.view.btnTabGroup.children[index];
      await click(node.getComponent(Button));
    }
    return await wait(()=>screen.pages && screen.pages[index],'UI页签未加载');
  }
  async function listNode(list,index) {
    if (!list || typeof list.getItemByListId!=='function') throw error('UI列表不可用');
    if (!list.getItemByListId(index) && typeof list.scrollTo==='function') list.scrollTo(index,0);
    return await wait(()=>list.getItemByListId(index),'目标UI列表条目未渲染');
  }
  async function bounded(promise, message) {
    let timer;
    try {
      return await Promise.race([promise, new Promise((_,reject)=>{timer=setTimeout(()=>reject(error(message,'uncertain')),timeoutMs);})]);
    } finally {clearTimeout(timer);}
  }
  async function dismissRewards(expectedItems) {
    let view = ui().find(cfg.Congrats);
    if (expectedItems && !view) view=await wait(()=>ui().find(cfg.Congrats),'奖励界面未完成加载');
    if (view) {
      if (view.waitAfterOpen) await bounded(view.waitAfterOpen,'奖励界面未正常打开');
      const reward = await wait(()=>view.ui || ui().findOpen(cfg.Congrats),'奖励实例未加载');
      const closeButton=closeControl(reward,'closeSelf');
      const end=Date.now()+timeoutMs;
      while (ui().findOpen(cfg.Congrats)) {
        if (Date.now()>end) throw error('奖励动画未正常关闭','uncertain');
        await click(closeButton);
      }
      if (view.waitAfterClose) await bounded(view.waitAfterClose,'奖励关闭动画未完成');
      await pause();
    }
    if (ui().find(cfg.HeroLevelUp)) throw error('升级界面需手动确认，暂停扫荡');
  }
  function closeControl(screen,handler) {
    const view=screen.view || {};
    if (view.btn_close || view.button_close) return view.btn_close || view.button_close;
    const buttons=screen.node && screen.node.getComponentsInChildren ? screen.node.getComponentsInChildren(cc.Button) : [];
    const match=buttons.find(b=>b.clickCallback===screen[handler || 'close'] || (b.clickEvents || []).some(e=>e.handler===handler));
    if (!match) throw error('未找到页面已绑定的UI关闭按钮');
    return match;
  }
  async function home() {
    // 先查完整页面栈，不能关闭普通页后才发现正在战斗/引导/过渡。
    const blocked=blockedViews();
    if (blocked.length) throw error('无法返回主界面：'+blocked.map(v=>v.cfg && v.cfg.id || '未知界面').join(', '));
    await dismissRewards();
    if (!ui().findOpen(cfg.MainUI)) {
      const main=ui().find(cfg.MainUI);
      if (main && main.waitAfterOpen) await bounded(main.waitAfterOpen,'主界面仍在加载');
      else throw error('主界面尚未加载，不能绕过UI直接创建页面');
    }
    // 保存原ViewParams后等待完整关闭生命周期，findOpen消失不代表动画已结束。
    const pages=normalPages();
    const views=Object.values(ui().viewParams || {}).filter(v=>pages.includes(v.cfg) && (v.showing || v.loading)).reverse();
    for (const view of views) {
      const retained=ui().find(view.cfg) || view;
      if (retained.waitAfterOpen) await bounded(retained.waitAfterOpen,'功能页面未完成加载');
      const screen=retained.ui || ui().findOpen(view.cfg);
      if (!screen) throw error('界面实例尚未加载');
      const currentBlocked=blockedViews();
      if (screen.battleWorld || screen.battleWorldOther || currentBlocked.length)
        throw error('页面加载后出现战斗或阻挡状态，停止返回主界面');
      await click(closeControl(screen,'close'));
      if (retained.waitAfterClose) await bounded(retained.waitAfterClose,'界面关闭动画未完成');
      else await wait(()=>!ui().findOpen(view.cfg),'界面关闭未完成');
    }
    if (!safe()) throw error('返回后主界面仍被阻挡：'+blockers().join(', '));
    return true;
  }
  function serialize(value) {
    if (value instanceof Map || Object.prototype.toString.call(value)==='[object Map]')
      return Array.from(value.entries()).sort((a,b)=>String(a[0]).localeCompare(String(b[0]))).map(([k,v])=>[k,serialize(v)]);
    if (Array.isArray(value)) return value.map(serialize);
    if (value && typeof value==='object') return Object.fromEntries(Object.keys(value).sort().map(k=>[k,serialize(value[k])]));
    return value;
  }
  function capture() {
    const r = g.ROLE;
    const formation = r.pet.formation;
    const slots = formation.plan.get(formation.planOnUsed);
    return {role_id:r.id, selection:{sanshi:r.desire.planOnUsed, artifact:r.magic.onUseMagic, plan:r.magic.onUsePlan, eye:r.pet.fightId},
      formation:formation.planOnUsed, slots:[r.pet.fightId,...[1,2,3].map(i=>slots && slots.get(i) || 0)],
      contents:{sanshi:serialize(r.desire.plan), magic:serialize(r.magic.plan), pets:Array.from(r.pet.bag.entries()).map(([id,p])=>[id,serialize({level:p.level,quality:p.quality,skillLevel:p.skillLevel})]).sort((a,b)=>a[0]-b[0])}};
  }
  function gold() {
    const attributes = g.ROLE.hero && g.ROLE.hero.attribute && g.ROLE.hero.attribute.attributes;
    if (!attributes || typeof attributes.get !== 'function') throw error('未找到自身贪财属性');
    const value = attributes.get(data.BattleAttributeKey.GOLD_UP);
    if (!Number.isFinite(value)) throw error('自身贪财尚未同步');
    return value;
  }
  async function desireScreen() {
    const screen = await open(cfg.DesireUI);
    const page=await switchTab(screen,0);
    const Type=await uiClass('ui-desire-switch-btn.ts','UIDesireSwitchBtn');
    const buttons=await wait(()=>{const items=page.switch_btns.getComponentsInChildren(Type);return items.length?items:null;},'三尸方案按钮未加载');
    return {screen,page,buttons};
  }
  async function magicScreen(pageType) {
    const screen = await open(cfg.MagicArtifactUI);
    if (!screen.module.isUnlock) throw error('法器未解锁');
    const m = screen.module;
    if ((m._pendingTemperEntryLocks && m._pendingTemperEntryLocks.size) || (m._temperEntryLockSyncs && m._temperEntryLockSyncs.size))
      throw error('法器有未保存操作，不能自动切方案');
    const page=await switchTab(screen,pageType);
    return {screen, page, module:m};
  }
  async function petScreen() {
    const screen=await open(cfg.PetUI);
    await wait(()=>Array.isArray(screen.petList) && screen.petList.length,'鬼仆UI列表未就绪');
    return screen;
  }
  function displayedPetName(pet) {
    const config=pet.skin>0 && data.PetSkinCfg ? data.PetSkinCfg.getById(pet.skin) : data.PetCfg.getById(pet.cfgId);
    return String(config && config.name || '').trim();
  }
  async function catalog(name) {
    // 先打开鬼仆页面核对UI实际显示名，不在法器页面才搜索原始背包。
    const pets=await petScreen();
    const twins=pets.petList.filter(p=>displayedPetName(p)===String(name).trim());
    if (!twins.length) {
      const message='鬼仆UI未找到“'+name+'”；当前显示名：'+pets.petList.map(displayedPetName).join(', ');
      await home();
      throw error(message);
    }
    // 同名个体随机取一个上阵，只影响本次选择，恢复仍按原阵眼ID。
    const chosen=twins[Math.floor(Math.random()*twins.length)];
    if (g.console) g.console.info('[plugin.ui]','阵眼“'+name+'”同名个体'+twins.map(p=>p.id).join(', ')+'，本次随机选中 '+chosen.id);
    await home();
    const d = await desireScreen();
    const sanshi = d.buttons.map((b,i)=>!b.isLock && g.ROLE.desire.plan.has(i)?i:null).filter(i=>i!==null);
    const m = (await magicScreen(magicTypes.Artifact)).module;
    const artifacts = m.getArtifactConfigs().filter(c=>m.isArtifactOpen(c.id) && m.isArtifactActivated(c.id)).map(c=>c.id);
    const plans = Array.from(g.ROLE.magic.plan.keys()).filter(id=>m.isTemperPlanUnlocked(id));
    const magic = artifacts.flatMap(artifact=>plans.map(plan=>({artifact,plan})));
    const original = g.ROLE;
    if (!original.pet.fightId || !original.pet.bag.has(original.pet.fightId) ||
        !original.pet.formation.planOnUsed || !sanshi.includes(original.desire.planOnUsed) ||
        !artifacts.includes(original.magic.onUseMagic) || !plans.includes(original.magic.onUsePlan)) {
      await home();
      throw error('原阵眼、法器或方案无法通过现有正常UI恢复，未改变装备');
    }
    await home();
    return {sanshi,magic,eye:chosen.id};
  }
  async function observe(expected, action, verify, waitMs) {
    if (!expected.length || expected.some(fn=>typeof fn!=='function')) throw error('正常请求入口未解析，未点击');
    const limit=waitMs || timeoutMs;
    const original = manager.service;
    let started=false, receipt, failure;
    const wrapper = function(fn, ...args) {
      const promise = original.call(this, fn, ...args);
      if (expected.includes(fn) && (fn !== defs.SystemService.adCallBack || (args[0] && args[0].adId === 8))) {
        if (started) {guard.uncertain=true; throw error('同一步骤出现多个请求', 'uncertain');}
        started=true; guard.pending=true;
        Promise.resolve(promise).then(value=>{receipt=value;guard.pending=false;},err=>{failure=err;guard.pending=false;});
      }
      return promise;
    };
    manager.service=wrapper;
    try {
      // 按钮回调本身可能等待响应；用独立等待判断，响应未确认时不继续。
      guard.action_pending=true;
      Promise.resolve().then(action).catch(err=>{failure=err;}).finally(()=>{guard.action_pending=false;});
      // 回执轮询不用观察延时，否则大延时会把正常响应误判成超时。
      const end=Date.now()+limit;
      while (!(receipt || failure) && Date.now()<=end)
        await new Promise(resolve=>setTimeout(resolve,Math.min(stepDelay(),100)));
      if (!(receipt || failure)) {
        // 区分“点击没发出请求”和“请求已发出没回来”，两者风险不同。
        throw error(started ? '正常UI请求已发出但未收到回执，结果未知' : '点击未产生正常请求，未修改任何状态',
          started ? 'uncertain' : 'unavailable');
      }
      await wait(()=>!guard.action_pending,'按钮回调尚未完成');
      if (failure) throw error(String(failure), started?'uncertain':'unavailable');
      if (!receipt || !Object.prototype.hasOwnProperty.call(receipt,'err')) throw error('响应形状未知', 'uncertain');
      if (receipt.err != null) {
        guard.pending=false;
        throw error('服务器拒绝本次正常操作：'+(receipt.err.error || receipt.err.code || '未知原因'), 'rejected');
      }
      await wait(verify, '自身状态尚未同步，禁止重复操作');
      guard.pending=false;
      return receipt.resp;
    } finally {
      if (manager.service === wrapper) manager.service=original;
    }
  }
  async function setEye(id) {
    if (g.ROLE.pet.fightId===id) return;
    if (!g.ROLE.pet.bag.has(id)) throw error('阵眼不在自身鬼仆列表');
    const screen=await petScreen();
    const index=screen.petList.findIndex(p=>p.id===id);
    if (index<0) throw error('目标鬼仆不在当前UI列表中');
    if (screen.curSelectId!==id) {
      await click(await listNode(screen.view.list_pet,index));
      await wait(()=>screen.curSelectId===id,'鬼仆UI选择未生效');
    }
    await observe([defs.PetService.petFight], ()=>click(screen.view.btn_inParty), ()=>g.ROLE.pet.fightId===id);
  }
  async function select(choice) {
    if (g.ROLE.desire.planOnUsed!==choice.sanshi) {
      const d=await desireScreen(), b=d.buttons[choice.sanshi];
      if (!b || b.isLock || !g.ROLE.desire.plan.has(choice.sanshi)) throw error('三尸方案不是已有可用方案');
      await observe([defs.DesireService.switchPlan], ()=>click(b), ()=>g.ROLE.desire.planOnUsed===choice.sanshi);
    }
    const artifact=await magicScreen(magicTypes.Artifact);
    if (!artifact.module.isArtifactOpen(choice.artifact) || !artifact.module.isArtifactActivated(choice.artifact)) throw error('法器尚未激活，不能装备');
    if (g.ROLE.magic.onUseMagic!==choice.artifact) {
      const configs=artifact.module.getArtifactConfigs();
      const index=configs.findIndex(item=>item.id===choice.artifact);
      const item=await listNode(artifact.page.artifactSelector.listArtifacts,index);
      const Type=await uiClass('magic-artifact-list-item.ts','MagicArtifactListItem');
      await click(item.getComponent(Type).btnSelect);
      await wait(()=>artifact.module.getSelectedArtifactId()===choice.artifact,'法器UI选择未生效');
      await observe([defs.MagicService.useMagicWeapon], ()=>click(artifact.page.btnEquip), ()=>g.ROLE.magic.onUseMagic===choice.artifact);
    }
    if (g.ROLE.magic.onUsePlan!==choice.plan) await applyTemperPlan(choice.plan);
    return gold();
  }
  async function applyTemperPlan(planId) {
    const temper=await magicScreen(magicTypes.Temper);
    const states=temper.module.getTemperPlanDisplayStates();
    const index=states.findIndex(p=>p.planId===planId && p.unlocked && g.ROLE.magic.plan.has(p.planId));
    if (index<0) throw error('法器方案不是已有可用方案');
    const selector=temper.page.selectPlan;
    if (!selector.isShow) await click(selector.btnOpen);
    const item=selector.list_select_item && selector.list_select_item[index];
    const node=item ? item.node : await listNode(selector.list,index);
    const Type=await uiClass('magic-artifact-temper-plan-item.ts','MagicArtifactTemperPlanItem');
    await observe([defs.MagicService.switchPlan], ()=>click(node.getComponent(Type).btnSelect), ()=>g.ROLE.magic.onUsePlan===planId);
  }
  // 法器各方案的贪财词条之和：官方词条表里 attrType 指向属性ID，可直接算，不用逐个切换实测。
  function planScores(module) {
    const goldKey=Number(data.BattleAttributeKey.GOLD_UP);
    const scores=new Map(), names=new Map();
    const rows=typeof module.getTemperPlans==='function' ? module.getTemperPlans() : null;
    if (!rows) return {scores,names,available:false};
    rows.forEach(plan=>{
      let sum=0;
      (plan.entries||[]).forEach(entry=>{
        const row=data.MagicArtifactEntryCfg && data.MagicArtifactEntryCfg.getById(entry.entryId);
        if (row && Number(row.attrType)===goldKey) sum+=Number(entry.value)||0;
      });
      scores.set(plan.planId,sum);
      names.set(plan.planId,plan.customName || '');
    });
    return {scores,names,available:scores.size>0};
  }
  // 属性由服务器下发，切换后要等读数连续一段时间不变才算这次方案的真实值。
  // 一直没稳定返回null：宁可不切，也不能把上一次的读数当成这次的结果。
  async function stableGold(limit) {
    const end=Date.now()+(limit || 4000);
    let previous=Number(gold()), since=Date.now();
    while (Date.now()<=end) {
      await new Promise(resolve=>setTimeout(resolve,Math.min(stepDelay(),150)));
      const value=Number(gold());
      if (value!==previous) { previous=value; since=Date.now(); }
      else if (Date.now()-since>=400) return value;
    }
    return null;
  }
  // 只有“贪财+X%”才是贪财加成；“每拥有8%贪财，获得2.25%增伤”是把已有贪财转成增伤，不算加成。
  function goldBonus(desc) {
    if (!desc) return 0;
    const text=String(desc).replace(/\s+/g,'');
    const re=/贪财[+＋]?([0-9]+(?:\.[0-9]+)?)%/g;
    let match, total=0, found=false;
    while ((match=re.exec(text))!==null) { total+=parseFloat(match[1]); found=true; }
    return found ? Math.round(total*100)/100 : 0;
  }
  // 三尸没有结构化属性，只有描述文本（如“贪财+3%”），按文本抠数值求和给每套方案打分。
  function desireScores() {
    const scores=new Map(), bag=new Map();
    const source=g.ROLE.desire && g.ROLE.desire.bag;
    if (source && typeof source.forEach==='function') source.forEach((item)=>{ if (item) bag.set(item.id,item); });
    const plans=g.ROLE.desire && g.ROLE.desire.plan;
    if (!plans || typeof plans.forEach!=='function') return scores;
    plans.forEach((slots, planId)=>{
      let sum=0;
      if (slots && typeof slots.forEach==='function') slots.forEach(instanceId=>{
        const item=bag.get(instanceId);
        if (!item) return;
        const row=rowOf('DesireCfg', item.cfgId);
        const desc=row && row.itemId ? row.itemId.desc : (row && row.desc);
        sum+=goldBonus(desc);
      });
      scores.set(planId,sum);
    });
    return scores;
  }
  // 每套方案装了几个三尸：贪财打平时优先保留配置更完整的一套。
  function desireSize(planId) {
    const slots=g.ROLE.desire && g.ROLE.desire.plan && g.ROLE.desire.plan.get(planId);
    return slots && typeof slots.size==='number' ? slots.size : 0;
  }
  async function optimize() {
    // 优先按数据分选三尸（只切换一次，避免属性同步时序问题）；数据分不可用才逐个实测。
    const d=await desireScreen();
    const candidates=d.buttons.map((b,i)=>i).filter(i=>!d.buttons[i].isLock && g.ROLE.desire.plan.has(i));
    if (!candidates.length) throw error('三尸页面没有可切换的已有方案');
    const dScores=desireScores();
    const dValues=candidates.map(index=>dScores.get(index) || 0);
    const dataUsable=new Set(dValues).size>1;
    let sanshi=g.ROLE.desire.planOnUsed, measured=new Map();
    if (dataUsable) {
      const best=Math.max(...dValues);
      const top=candidates.filter(index=>(dScores.get(index)||0)===best);
      // 当前方案已经是最高就不动；否则在并列最高里选配置更完整的一套。
      sanshi=top.includes(g.ROLE.desire.planOnUsed)
        ? g.ROLE.desire.planOnUsed
        : top.reduce((a,b)=>desireSize(b)>desireSize(a)?b:a, top[0]);
      log('三尸按词条数据选方案'+sanshi+'（各方案贪财加成 '+dValues.join('/')+'，当前'+g.ROLE.desire.planOnUsed+'）');
    } else {
      for (const index of candidates) {
        if (g.ROLE.desire.planOnUsed!==index) {
          await observe([defs.DesireService.switchPlan], ()=>click(d.buttons[index]), ()=>g.ROLE.desire.planOnUsed===index);
        }
        measured.set(index, await stableGold());
      }
      const trusted=new Map(Array.from(measured.entries()).filter(([,value])=>value!==null));
      const values=Array.from(trusted.values());
      const trustworthy=trusted.size===candidates.length && new Set(values).size>1;
      if (trustworthy) sanshi=candidates.reduce((best,index)=>trusted.get(index)>trusted.get(best)?index:best,candidates[0]);
      log(trustworthy ? '三尸按实测选方案'+sanshi+'（各方案贪财 '+values.join('/')+'）'
        : '三尸各方案贪财读数不可信（'+Array.from(measured.entries()).map(([k,v])=>k+':'+(v===null?'未同步':v)).join('/')+'），保持当前方案'+sanshi);
    }
    if (g.ROLE.desire.planOnUsed!==sanshi) {
      await observe([defs.DesireService.switchPlan], ()=>click(d.buttons[sanshi]), ()=>g.ROLE.desire.planOnUsed===sanshi);
    }
    await home();
    const artifact=(await magicScreen(magicTypes.Artifact)).module;
    const {scores,names,available}=planScores(artifact);
    const plans=Array.from(g.ROLE.magic.plan.keys()).filter(id=>artifact.isTemperPlanUnlocked(id));
    let plan=g.ROLE.magic.onUsePlan;
    if (available) {
      const ranked=plans.slice().sort((a,b)=>(scores.get(b)||0)-(scores.get(a)||0));
      if (ranked.length && (scores.get(ranked[0])||0)>(scores.get(plan)||0)) plan=ranked[0];
    }
    if (g.ROLE.magic.onUsePlan!==plan) await applyTemperPlan(plan);
    await home();
    const choice={sanshi,plan,artifact:g.ROLE.magic.onUseMagic};
    log('方案选择：三尸'+sanshi+'（各方案贪财数据分 '+dValues.join('/')+
      (measured.size ? '；实测 '+Array.from(measured.entries()).map(([k,v])=>k+':'+(v===null?'未同步':v)).join('/') : '')+
      '），法器方案'+plan+'「'+(names.get(plan)||'')+'」（贪财词条和'+(scores.get(plan)||0)+'）'+
      (available?'':'；词条表不可用，沿用当前方案'));
    return {choice,scores:Array.from(scores.entries()).map(([id,value])=>[id,value,names.get(id)||'']),
      measured:Array.from(measured.entries()),desire_scores:Array.from(dScores.entries()),gold:gold()};
  }
  function multiplierOptions() {
    const options=data.ConstantCfg.config.HangUpTimes;
    return Array.isArray(options) && options.length ? options : [1];
  }
  // 体力定时用：当前体力、上限，以及"上次恢复时刻"和服务器时间（毫秒→秒）。
  async function energyTiming() {
    let now=Date.now();
    try {
      const module=await g.System.import('chunks:///_virtual/date-util.ts');
      const clock=module && module.default;
      if (clock && Number(clock.serverTime)>0) now=Number(clock.serverTime);
    } catch (e) { /* 拿不到服务器时间就用本地时间，任务会退化为粗略估算 */ }
    const raw=g.ROLE.energy && g.ROLE.energy.lastRecoveryTime;
    return {last_recovery:Number(raw)>0 ? Number(raw)/1000 : null, server_now: now/1000};
  }
  function canSwitchMultiplier(screen) {
    const button=screen && screen.view && screen.view.btn_TiemChange;
    return !!button && button.interactable!==false && button.enabledInHierarchy!==false &&
      (!button.node || button.node.activeInHierarchy!==false);
  }
  // 体力够就选最大倍率，一次扫荡花掉更多体力，减少点击次数。
  function pickMultiplier(screen, base, energy) {
    const options=multiplierOptions();
    if (!canSwitchMultiplier(screen)) return screen && screen.hangUpTime!==undefined ? screen.hangUpTime : 0;
    let best=0;
    options.forEach((times,index)=>{
      if (base*times<=energy && (options[best]===undefined || times>options[best])) best=index;
    });
    return best;
  }
  async function quote() {
    await dismissRewards();
    const screen=await open(cfg.Hangup), r=g.ROLE;
    const base=roleHelper.getHangUpCost();
    const options=multiplierOptions();
    const index=pickMultiplier(screen, base, r.energy.energyValue);
    const cost=base*options[index];
    const level=data.LevelCfg.getById(r.level);
    const adCount=r.adCallBack.get(8) || 0;
    const allowed=shop.getCurLifeCardType()!==cardType.UnActive || r.hangUp.sweepNum<level.HangUpFreeTime || adCount<level.HangUpAdTime;
    // 正常clickSweep会按账号的永久广告权益走官方流程，不代发或伪造广告回调。
    return {energy:r.energy.energyValue,sweep_num:r.hangUp.sweepNum,completed_count:r.hangUp.sweepNum+adCount,
      cost,times:options[index],times_index:index,times_options:options.slice(),
      can_switch:canSwitchMultiplier(screen),allowed};
  }
  async function rewardInfo() {
    const clock=(await g.System.import('chunks:///_virtual/date-util.ts')).default;
    const elapsed=(clock.serverTime-g.ROLE.hangUp.lastRewardTime)/1000;
    const minimum=data.ConstantCfg.config.HangUpRewardPeriod;
    if (!Number.isFinite(elapsed) || elapsed<0 || !Number.isFinite(minimum) || minimum<0) throw error('挂机领取时间尚未同步');
    return {elapsed,minimum};
  }
  async function rewardClaim() {
    const info=await rewardInfo();
    if (info.elapsed<info.minimum) throw error('挂机时间不足，未点击领取','rejected');
    const screen=await open(cfg.Hangup), before=g.ROLE.hangUp.lastRewardTime;
    const response=await observe([defs.RoleService.getHangUpReward],()=>click(screen.view.button_get_reward),()=>g.ROLE.hangUp.lastRewardTime>before);
    await dismissRewards(response && response.items && response.items.length>0);
    return {claimed:true};
  }
  async function sweep() {
    const before=await quote();
    if (!before.allowed || !(before.cost>0) || before.energy<before.cost) throw error('当前体力不足/次数耗尽，未点击购买入口','rejected');
    const screen=ui().findOpen(cfg.Hangup);
    // 先把左上角扫荡次数（倍率）切到体力允许的最大档，再一次扫荡。
    if (before.can_switch && screen.hangUpTime!==before.times_index) {
      const end=Date.now()+timeoutMs;
      while (screen.hangUpTime!==before.times_index && Date.now()<=end) await click(screen.view.btn_TiemChange);
      await wait(()=>screen.hangUpTime===before.times_index,'扫荡次数档位未切换成功');
    }
    const quoted=await quote();
    log('扫荡设置：'+quoted.times+'倍，消耗体力'+quoted.cost+'（剩余'+quoted.energy+'）');
    const response = await observe([defs.RoleService.sweepHangUp,defs.SystemService.adCallBack], ()=>click(screen.view.button_saodang),
      ()=>g.ROLE.hangUp.sweepNum+(g.ROLE.adCallBack.get(8)||0)>before.completed_count && g.ROLE.energy.energyValue<before.energy);
    const items = response && (response.items || response.data);
    await dismissRewards(Array.isArray(items) && items.length>0);
    return {energy:g.ROLE.energy.energyValue,sweep_num:g.ROLE.hangUp.sweepNum,
      completed_count:g.ROLE.hangUp.sweepNum+(g.ROLE.adCallBack.get(8)||0),times:quoted.times,cost:quoted.cost};
  }
  async function restore(original) {
    if (original.role_id!==g.ROLE.id || original.formation!==g.ROLE.pet.formation.planOnUsed) throw error('账号/阵法变化，不能盲目恢复','uncertain');
    await setEye(original.selection.eye);
    await select(original.selection);
    const current=capture();
    if (JSON.stringify(current)!==JSON.stringify(original)) throw error('方案内容、阵脚或培养发生变化，需人工核对','uncertain');
    return current;
  }
  // ── 配置表名称解析（与 tools/js/player_info_dump.js 同一套口径）──
  const HIDE_NAMES = {0:'天书', 1:'三尸', 2:'脸谱', 3:'鬼仆阵法', 4:'法器'};
  function hideNames(mask) {
    const names = [];
    for (let bit = 0; bit < 8; bit++) if (mask & (1 << bit)) names.push(HIDE_NAMES[bit] || ('bit' + bit));
    return names;
  }
  function cjk(text) { return !!text && /[\u4e00-\u9fa5]/.test(String(text)); }
  function rowOf(table, id) {
    try {
      const source = data && data[table];
      return source && typeof source.getById === 'function' ? source.getById(Number(id)) || null : null;
    } catch (e) { return null; }
  }
  function nameOf(table, id) {
    const row = rowOf(table, id);
    if (!row) return null;
    for (const value of [row.name, row.Name, row.cfgName, row.title, row.note]) {
      if (cjk(value)) return String(value);
    }
    return null;
  }
  function descOf(table, id) {
    const row = rowOf(table, id);
    if (!row) return null;
    for (const value of [row.desc, row.des, row.description]) {
      if (cjk(value)) return String(value);
    }
    return null;
  }
  function attrText(attrId, value) {
    const row = rowOf('AttrCfg', attrId);
    const style = row && row.style !== undefined ? Number(row.style) : 0;
    if (style !== 2 || value === undefined || value === null) return String(value);
    return String(Math.round(Number(value) / 100 * 100) / 100) + '%';
  }
  function isMap(value) { return !!value && Object.prototype.toString.call(value) === '[object Map]'; }
  function eachMap(value, limit, fn) {
    if (!isMap(value)) return;
    let index = 0;
    value.forEach((item, key) => { if (index++ < limit) fn(item, key); });
  }
  function percentFrom(desc, keyword) {
    if (!desc) return 0;
    const text = String(desc).toLowerCase().replace(/\s+/g, '');
    const kw = String(keyword).toLowerCase();
    for (const pattern of ['([0-9]+(?:\\.[0-9]+)?)%' + kw, kw + '[+＋]?([0-9]+(?:\\.[0-9]+)?)%']) {
      const re = new RegExp(pattern, 'g');
      let match, total = 0, found = false;
      while ((match = re.exec(text)) !== null) { total += parseFloat(match[1]); found = true; }
      if (found) return Math.round(total * 100) / 100;
    }
    return 0;
  }
  function label(id, table, fallback) {
    return nameOf(table, id) || fallback || ('ID' + id);
  }
  function snapshotSections(snapshot) {
    const out = [];
    const head = [];
    [['角色ID','id'],['昵称','name'],['服务器','sName'],['等级','level'],['战力','fightPower'],
     ['最高战力','maxFightPower'],['阴司','legionName'],['关卡波次','stageWave']].forEach(([title, key]) => {
      const value = snapshot[key];
      if (value !== undefined && value !== null && value !== '' && value !== 0) head.push(title + '=' + value);
    });
    if (head.length) out.push(head.join('  '));
    const wornFashion = isMap(snapshot.fashion) ? snapshot.fashion :
      (snapshot.fashion && isMap(snapshot.fashion.onUse) ? snapshot.fashion.onUse : null);
    const fashionLevels = isMap(snapshot.allFashion) ? snapshot.allFashion :
      (snapshot.fashion && snapshot.fashion.level);
    const fashionLines = [];
    if (wornFashion) eachMap(wornFashion, 30, (id, slot) => {
      const name = nameOf('FashionCfg',id) || ('傀儡装ID'+id);
      const level = isMap(fashionLevels) ? fashionLevels.get(Number(id)) : null;
      fashionLines.push((name==='雷法尊者'?'【雷法尊者】 ':'') + name + '（已穿戴，部位'+slot+
        (level!==null && level!==undefined?'，Lv'+level:'')+'）');
    });
    fashionLines.sort((a,b)=>Number(b.includes('【雷法尊者】'))-Number(a.includes('【雷法尊者】')));
    out.push('── 傀儡装 ──\n  '+(fashionLines.length?fashionLines.join('\n  '):wornFashion?'未穿戴傀儡装':'穿戴资料未下发'));

    const books = [];
    eachMap(snapshot.equipSkill, 12, (id, slot) => books.push('槽位' + slot + ' ' + label(id, 'SkillBookCfg')));
    const levels = [];
    eachMap(snapshot.skillLevel, 40, (level, id) => levels.push(label(id, 'SkillBookCfg') + ' Lv.' + level));
    const epics = [];
    eachMap(snapshot.epicLevel, 20, (level, id) => epics.push(label(id, 'SkillBookCfg') + ' Lv.' + level));
    const awaken = [];
    eachMap(snapshot.epicAwakening, 20, (branches, bookId) => {
      if (!isMap(branches)) return;
      const parts = [];
      eachMap(branches, 20, (level, branchId) => parts.push(label(branchId, 'SkillBookEvolutionCfg') + ' Lv.' + level));
      if (parts.length) awaken.push(label(bookId, 'SkillBookCfg') + '：' + parts.join('、'));
    });
    const combines = [];
    eachMap(snapshot.skillCombineLevel, 20, (level, id) =>
      combines.push((nameOf('RareskillCombCfg', id) || nameOf('SkillBookCfg', id) || ('ID' + id)) + ' Lv.' + level));
    const bookLines = [].concat(
      books.length ? ['装备中：' + books.join('、')] : [],
      levels.length ? ['天书等级：' + levels.join('、')] : [],
      epics.length ? ['顶级天书：' + epics.join('、')] : [],
      awaken.length ? ['顶级天书觉醒：' + awaken.join('；')] : [],
      combines.length ? ['天书组合：' + combines.join('、')] : []);
    if (bookLines.length) out.push('── 天书 ──\n  ' + bookLines.join('\n  '));

    const desire = (planMap, title) => {
      const lines = [];
      const grouped = {};
      let up = 0, down = 0;
      eachMap(planMap, 80, (id, key) => {
        const slot = Math.floor(Number(key) / 65536);
        const name = nameOf('DesireCfg', id);
        if (!name) return;
        const desc = descOf('DesireCfg', id);
        const text = name + (desc ? ' —— ' + desc.replace(/\s+/g, ' ').slice(0, 60) : '');
        (grouped[slot] = grouped[slot] || []).push(text);
        up += percentFrom(desc, 'pvp增伤');
        down += percentFrom(desc, 'pvp减伤') + percentFrom(desc, 'pvp减免');
      });
      Object.keys(grouped).sort().forEach(slot => grouped[slot].forEach((text, index) => {
        lines.push(title + ' 槽' + slot + '#' + (index + 1) + ' ' + text);
      }));
      if (up || down) lines.push(title + ' 汇总：PVP增伤 ' + up + '%' + (down ? '、PVP减伤 ' + down + '%' : ''));
      return lines;
    };
    const desireLines = desire(snapshot.desirePlan, '[当前]');
    eachMap(snapshot.allDesirePlan, 8, (planMap, planId) => {
      desireLines.push(...desire(planMap, '[方案' + planId + ']'));
    });
    if (desireLines.length) out.push('── 三尸 ──\n  ' + desireLines.join('\n  '));

    const equipLines = [];
    const levelMap = snapshot.equipmentLevel;
    eachMap(snapshot.equipment, 10, (item, slot) => {
      if (!item || item.configId === undefined) return;
      const row = rowOf('EquipmentCfg', item.configId);
      const name = nameOf('EquipmentCfg', item.configId);
      if (!name) return;
      const parts = [name];
      const level = isMap(levelMap) ? levelMap.get(slot) : undefined;
      if (level !== undefined && level !== null) parts.push('等级' + level);
      if (row && row.quality) parts.push('品质' + row.quality);
      let line = '· ' + parts.join(' ');
      if (Array.isArray(item.entry) && item.entry.length) {
        const entries = [];
        item.entry.slice(0, 8).forEach(entry => {
          const entryRow = rowOf('EquipmentEntryCfg', entry.id);
          const entryName = nameOf('EquipmentEntryCfg', entry.id);
          if (!entryName) return;
          entries.push(entryName + ' ' + attrText(entryRow && entryRow.group, entry.value) + (entry.unlock ? '(已解锁)' : ''));
        });
        if (entries.length) line += '\n   词条：' + entries.join('、');
      }
      equipLines.push(line);
    });
    eachMap(snapshot.equipmentSuit, 10, (count, id) => {
      const name = nameOf('EquipmentSuitCfg', id);
      if (name) equipLines.push('· 套装 ' + name + ' ' + count + '件');
    });
    if (equipLines.length) out.push('── 脸谱 ──\n  ' + equipLines.join('\n  '));

    const petLines = [];
    const pet = snapshot.pet;
    if (pet && pet.cfgId !== undefined && nameOf('PetCfg', pet.cfgId)) {
      petLines.push('· 出战 ' + nameOf('PetCfg', pet.cfgId) + ' 等级' + pet.level + (pet.quality ? ' 品质' + pet.quality : ''));
      if (Array.isArray(pet.entry) && pet.entry.length) {
        const entries = [];
        pet.entry.slice(0, 8).forEach(id => { const name = nameOf('PetEntryCfg', id); if (name) entries.push(name); });
        if (entries.length) petLines.push('   词条：' + entries.join('、'));
      }
      const skills = [];
      eachMap(pet.skillLevel, 10, (level, id) => { const name = nameOf('SkillBookCfg', id); if (name) skills.push(name + ' Lv.' + level); });
      if (skills.length) petLines.push('   技能：' + skills.join('、'));
    }
    const info = snapshot.formationPetInfo;
    if (info && info.formationLevel !== undefined) petLines.push('· 阵法等级 ' + info.formationLevel);
    if (info) eachMap(info.formationPetInfo, 6, (slotPet, slot) => {
      if (!slotPet || slotPet.cfgId === undefined) return;
      const name = nameOf('PetCfg', slotPet.cfgId);
      if (name) petLines.push('· 阵位' + slot + ' ' + name + ' 等级' + slotPet.level);
    });
    if (petLines.length) out.push('── 鬼仆阵法 ──\n  ' + petLines.join('\n  '));

    const magicLines = [];
    const magic = snapshot.magic;
    if (magic) {
      const head2 = [];
      const current = nameOf('MagicArtifactBaseCfg', magic.onUseMagic);
      if (current) head2.push('当前法器 ' + current);
      if (magic.refineLevel !== undefined) head2.push('精炼' + magic.refineLevel + '阶');
      if (head2.length) magicLines.push('· ' + head2.join(' '));
      eachMap(magic.plan, 8, (item, planId) => {
        if (!item) return;
        const parts = [];
        let up = 0, down = 0;
        eachMap(item.entry, 8, (entry) => {
          if (!entry || entry.cfgId === undefined) return;
          const row = rowOf('MagicArtifactEntryCfg', entry.cfgId);
          const name = row && cjk(row.des) ? row.des : null;
          parts.push((name || ('词条ID' + entry.cfgId)) + ' ' + attrText(row && row.attrType, entry.value));
          if (!name) return;
          if (/pvp增伤/i.test(name)) up += Number(entry.value) / 100;
          else if (/pvp减伤|pvp减免/i.test(name)) down += Number(entry.value) / 100;
        });
        magicLines.push('· 方案「' + (item.name || planId) + '」' + (parts.length ? '：' + parts.join('、') : ''));
        if (up || down) magicLines.push('   └ 汇总：PVP增伤 ' + (Math.round(up * 100) / 100) + '%' + (down ? '、PVP减伤 ' + (Math.round(down * 100) / 100) + '%' : ''));
      });
    }
    if (magicLines.length) out.push('── 法器 ──\n  ' + magicLines.join('\n  '));

    const attrs = [];
    eachMap(snapshot.attribute, 80, (value, attrId) => {
      const name = nameOf('AttrCfg', attrId);
      if (name) attrs.push(name + ' ' + attrText(attrId, value));
    });
    if (attrs.length) out.push('── 属性 ──\n  ' + attrs.join('\n  '));
    if (Array.isArray(snapshot.unlockModuleIds) && snapshot.unlockModuleIds.length)
      out.push('── 玩法 ──\n  已解锁 ' + snapshot.unlockModuleIds.length + ' 项：' + snapshot.unlockModuleIds.join(', '));
    return out;
  }
  // 登录鉴权用：只读本地角色快照，不依赖任何页面是否打开。
  // 实测游戏里 g.ROLE.heroId 是空的，真正的账号号在 g.ROLE.id（纯数字），
  // 所以 player_id 以 role_id 为准，hero_id 只在它没有时才兜底。
  function identity() {
    const r=g.ROLE||{};
    const role=r.id!=null?String(r.id):'';
    const hero=r.heroId!=null?String(r.heroId):'';
    const legion=(r.legion && (r.legion.legionName||r.legion.name)) || r.legionName || '';
    // name 是玩家的角色名（昵称），后台用它显示"是谁在用来"
    return {player_id:role||hero, role_id:role, hero_id:hero,
            name:String(r.name||''), legion_name:String(legion||'')};
  }

  function playerInformation() {
    const screen=ui().findOpen(cfg.Setting);
    const page=screen && screen.view && screen.view.page_info;
    if (!page || screen.isValid===false || !page.node || page.node.activeInHierarchy!==true ||
        typeof screen.isSelf!=='boolean' || screen.isSelf!==page.isPersonal) return null;
    if (!screen.isSelf && (!screen.info || page.info!==screen.info)) return null;
    // 本人与他人都按 player_info_dump.js 的口径解析本地快照（GDRoleSnap），含对方界面上隐藏的分区。
    const snapshot = screen.isSelf ? (screen.info || g.ROLE) : screen.info;
    if (!snapshot) return null;
    let sections;
    try {
      sections = snapshotSections(snapshot);
    } catch (e) {
      sections = [];
    }
    if (screen.isSelf) {
      return {subject:'本人（完整信息）', text:sections.length ? sections.join('\n') : '快照中没有可展示的数据'};
    }
    const hidden = hideNames(Number(snapshot.previewHide) || 0);
    const head = ['玩家信息（本地快照全量，参考 player_info_dump）',
      hidden.length ? '对方设置了隐藏：' + hidden.join('、') : '对方未设置隐藏'];
    return {subject:'玩家信息（全量快照）', text:head.concat(sections).join('\n')};
  }
  const log=message=>{ if (g.console) g.console.info('[plugin.ui]', String(message)); };
  // 战斗界面（MineBattleUI 等）在独立的 BattleUICfgId 里，不在 CommonUICfgId。
  let battleCfg=null;
  async function battleConfig() {
    if (!battleCfg) {
      const module=await g.System.import('chunks:///_virtual/ui-battle-cfg.ts');
      battleCfg=module.BattleUICfgId || {};
    }
    return battleCfg;
  }
  const extra=typeof createDailyRuntime==='function'?createDailyRuntime(g,{ui,uiClass,click,open,wait,bounded,observe,dismissRewards,home,switchTab,
    configuration:()=>({cfg,data,defs,cc,Button}),listNode,log,battleCfg:battleConfig}):null;
  // 三尸合成是独立的运行时（package/plugin_manager/desire_runtime.js），
  // 只借用这里的通用UI辅助，不进日常任务的任何分支。
  const DESIRE_OPS=['desire_bag_stats','desire_compose_probe','desire_compose_open','desire_compose_once','desire_compose_close'];
  const desire=typeof createDesireRuntime==='function'?createDesireRuntime(g,{ui,uiClass,click,open,wait,bounded,observe,dismissRewards,home,switchTab,
    configuration:()=>({cfg,data,defs,cc,Button}),listNode,log,battleCfg:battleConfig}):null;
  return {async dispatch(op, args) {
    args=args || {};
    const readOnly=['inspect','capture','player_information','reward_info','desire_bag_stats','desire_compose_probe','identity'].includes(op);
    if (guard.busy && !readOnly) return {status:'uncertain',message:'已有正常UI操作未完成'};
    if (guard.uncertain && !readOnly) return {status:'uncertain',message:'前次操作结果未知，需核对恢复记录'};
    if (!readOnly) guard.busy=true;
    try {
      await initialize();
      let value;
      if (op==='inspect') value={...(await energyTiming()),energy:g.ROLE.energy.energyValue,maximum:roleHelper.getMaxEnergy(),safe:safe()&&!guard.busy&&!guard.uncertain,
        blockers:[...blockers(),...(guard.busy || guard.pending || guard.action_pending?['存在未完成操作']:[]),...(guard.uncertain?['前次操作结果未知']:[])]};
      else if (op==='capture') value=capture();
      else if (op==='player_information') value=playerInformation();
      else if (op==='identity') value=identity();
      else if (op==='reward_info') value=await rewardInfo();
      else if (op==='home') value=await home();
      else {
        if (!safe()) throw error('当前界面被阻挡：'+blockers().join(', '));
        if (op==='catalog') value=await catalog(args.name);
        else if (op==='optimize') value=await optimize();
        else if (op==='eye') value=await setEye(args.eye);
        else if (op==='select') value=await select(args);
        else if (op==='quote') value=await quote();
        else if (op==='sweep') value=await sweep();
        else if (op==='reward_claim') value=await rewardClaim();
        else if (op==='restore') value=await restore(args.original);
        // 三尸的操作必须走它自己的运行时：daily_runtime 对不认识的操作是 throw，
        // 放到后面就永远轮不到 desire。
        else if (desire && DESIRE_OPS.includes(op)) value=await desire.dispatch(op,args);
        else if (extra) value=await extra.dispatch(op,args);
        else throw error('未知操作');
      }
      return {status:'ok',value:value===undefined?null:value};
    } catch (e) {
      const status=guard.pending || e.status==='uncertain'?'uncertain':e.status || 'unavailable';
      if (status==='uncertain') guard.uncertain=true;
      if (g.console) g.console.error('[plugin.error]',String(e.message || e));
      return {status,message:String(e.message || e)};
    } finally {
      if (!readOnly) guard.busy=false;
    }
  }};
}
