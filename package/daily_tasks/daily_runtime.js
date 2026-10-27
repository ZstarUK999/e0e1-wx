// 已核对的日常UI链路。只读自身计数和公开列表，动作仅h.click触发正常事件。
function createDailyRuntime(g,h) {
  const fail=(message,status)=>Object.assign(new Error(message),{status:status||'unavailable'});
  const config=()=>h.configuration();
  // Retry only local UI transitions, never the enclosing claim/purchase/battle.
  async function retryUI(action,ready,message) {
    for(let attempt=1;attempt<=3;attempt++) {
      if(ready())return ready();
      try {await action();return await h.wait(ready,message);}
      catch(e) {
        const guard=g.__e0e1EnergyGuard || {};
        if(guard.pending || guard.callback_count || guard.uncertain)throw e;
        if(ready())return ready();
        if(attempt===3)throw fail(message+'（已尝试3次）','uncertain');
        if(g.console?.warn)g.console.warn('[plugin.ui]',message+'，重试 '+(attempt+1)+'/3');
      }
    }
  }
  // 战斗界面 id 在 BattleUICfgId（不是 CommonUICfgId），取不到就退回到 CommonUICfgId 的同名字段。
  async function battle(which) {
    const cfg=config().cfg;
    let battleCfg=null;
    if (typeof h.battleCfg==='function') battleCfg=await h.battleCfg();
    return (battleCfg && battleCfg[which]) || cfg[which] || null;
  }
  const kindNumber=kind=>kind==='sanshi'?0:kind==='artifact'?1:(()=>{throw fail('未知墓藏类型');})();
  const mineService=kind=>kind==='sanshi'?config().defs.MineService:config().defs.MagicService;
  const self=kind=>kind==='sanshi'?g.ROLE.mine:g.ROLE.artifactMine;
  async function minePage(kind) {
    const {cfg}=config(), index=kindNumber(kind), root=await h.open(cfg.MineUI);
    const view=h.ui().find(cfg.MineUI);
    if (view && view.waitAfterOpen) await h.bounded(view.waitAfterOpen,'墓藏页面打开尚未完成');
    const page=index===0?root.view.mine_sanshi:root.view.mine_magic_artifact;
    await retryUI(()=>h.click(index===0?root.view.btn_sanshi:root.view.btn_magic_artifact),
      ()=>root._mineType===index && page && page.node.activeInHierarchy!==false,'墓藏页面未就绪');
    return page;
  }
  async function items(page) {
    const Type=await h.uiClass('mine-item.ts','MineItem');
    return page.mine_content.node_items.children.map(n=>n.getComponent(Type)).filter(Boolean);
  }
  // 服务器时间（秒）与下次跨日所需的数据：给任务算"要等多久"。
  async function serverClock(withCrossDay) {
    let now=Date.now();
    try {
      const module=await g.System.import('chunks:///_virtual/date-util.ts');
      const clock=module && module.default;
      if (clock && Number(clock.serverTime)>0) now=Number(clock.serverTime);
    } catch (e) { /* 拿不到服务器时间就用本地时间 */ }
    const raw=withCrossDay ? Number(g.ROLE && g.ROLE.crossDayAt) : 0;
    return {server_now: now/1000, cross_day_at: Number(raw)>0 ? Number(raw)/1000 : null};
  }
  // 最近一个还没到期的墓时间戳（秒）：所有格子 siteTime 里大于当前时间的最小值。
  function nextReadyAt(own, nowMs) {
    let result=null;
    const sites=own && own.siteTime;
    if (!sites || typeof sites.forEach!=='function') return null;
    sites.forEach((value)=>{
      const time=Number(value);
      if (!Number.isFinite(time) || time<=nowMs) return;
      result=result===null?time:Math.min(result,time);
    });
    return result===null?null:result/1000;
  }
  async function state(kind,countsOnly) {
    kindNumber(kind);
    const list=countsOnly?[]:await items(await minePage(kind)), own=self(kind);
    if (!own || !Number.isFinite(own.battleNumDay) || !Number.isFinite(own.helpNumDay))
      throw fail('墓藏次数尚未同步');
    const {data}=config();
    const constant=kind==='sanshi'?data.MineCfg:data.ArtifactMineCfg;
    const constants=constant && constant.config;
    const raid=constants && constants[kind==='sanshi'?'MineExploreNum':'ArtifactExploreNum'];
    const fill=constants && constants[kind==='sanshi'?'MineGoodNum':'ArtifactGoodNum'];
    if (!Number.isFinite(raid) || !Number.isFinite(fill)) throw fail('墓藏每日次数配置未核实，不执行扫描');
    const types=(await g.System.import('chunks:///_virtual/types-mine.ts')).MineItemState;
    if (!types) throw fail('墓藏格状态枚举未解析');
    const clock=await serverClock(true);
    return {ready:true,finished:list.some(i=>i.state===types.unlock_finish),filling:list.some(i=>i.state===types.unlock_filling),
      idle:list.some(i=>i.state===types.unlock_idle),raid_remaining:Math.max(0,raid-own.battleNumDay),fill_remaining:Math.max(0,fill-own.helpNumDay),
      next_ready_at:nextReadyAt(own, clock.server_now*1000), server_now:clock.server_now, cross_day_at:clock.cross_day_at};
  }
  async function collect(kind) {
    const page=await minePage(kind), list=await items(page), {cc}=config();
    const types=(await g.System.import('chunks:///_virtual/types-mine.ts')).MineItemState;
    const item=list.find(i=>i.state===types.unlock_finish)||list.find(i=>i.state===types.unlock_filling);
    if (!item) throw fail('尚无可收取墓藏','rejected');
    const response=await h.observe([mineService(kind).recDigReward],()=>h.click(item.node.getComponent(config().Button)),()=>!list.some(i=>i.state===types.unlock_finish || i.state===types.unlock_filling));
    await h.dismissRewards(response && response.items && response.items.length>0);
    return {confirmed:true};
  }
  async function start(kind) {
    const page=await minePage(kind), list=await items(page);
    const types=(await g.System.import('chunks:///_virtual/types-mine.ts')).MineItemState;
    const item=list.find(i=>i.state===types.unlock_idle);
    if (!item) throw fail('没有可重开的空闲墓藏','rejected');
    await h.observe([mineService(kind).startDig],()=>h.click(item.node.getComponent(config().Button)),()=>!list.some(i=>i.state===types.unlock_idle));
    return {confirmed:true};
  }
  async function closeScreen(which) {
    const view=h.ui().find(which), screen=view && view.ui;
    if (!screen) return;
    if(!screen.view)throw fail('页面正在释放，未点击关闭或导航按钮','uncertain');
    const button=screen.view.btn_close || screen.view.button_close || screen.view.btn_back;
    if (!button) throw fail('页面关闭按钮未核实');
    await retryUI(async()=>{
      const current=h.ui().findOpen(which);
      if(current)await h.click(current.view.btn_close || current.view.button_close || current.view.btn_back);
    },()=>!h.ui().findOpen(which),'页面关闭未完成');
    if (view.waitAfterClose) await h.bounded(view.waitAfterClose,'页面关闭未完成');
  }
  async function recruit(kind) {
    if (!(g.ROLE.legion && g.ROLE.legion.legionId>0)) throw fail('未加入阴司，无法正常招募','rejected');
    const page=await minePage(kind),{cfg}=config();
    await h.click(page.btn_recruit);
    const chat=await h.wait(()=>h.ui().findOpen(cfg.ChatRecruitUI),'招募页面尚未打开');
    const node=await h.listNode(chat.view.list,0);
    const Type=await h.uiClass('chat-recruit-item.ts','ChatRecruitItem');
    const item=node.getComponent(Type);
    if (!item || item.lbl_status.string!=='发布招募') {
      await closeScreen(cfg.ChatRecruitUI);await closeScreen(cfg.ChatUI);
      throw fail(item && item.lbl_status.string || '招募按钮尚未就绪','rejected');
    }
    // 发送后官方回调关闭招募窗口；不自行发消息或绕过冷却。
    await h.click(item.btn_recruit);
    await h.wait(()=>!h.ui().findOpen(cfg.ChatRecruitUI),'招募未收到正常发送成功回执');
    await closeScreen(cfg.ChatUI);
    return {confirmed:true};
  }
  const REFRESH_MIN=5, REFRESH_MAX=10;
  function rowsOf(list,mode) {
    return list.map(t=>({id:t.id,site_num:Number(t.siteNum)||0,can_fill:mode==='fill',
      name:t.name||'',server:t.sName||'',legion:t.legionName||'',fight_power:t.fightPower||0}));
  }
  function bestOf(list) {
    return list.reduce((best,item)=>!best||item.site_num>best.site_num?item:best,null);
  }
  function report(kind,mode,count,discovered,best,fresh,total) {
    if (!h.log) return;
    h.log(`${kind==='sanshi'?'三尸':'法器'}墓${mode==='fill'?'填土':'盗掠'}刷新第${count}次：`+
      `本次${total}名，新增${fresh}名，累计新增${discovered.size}名，见过的最好目标 `+
      (best?`${best.server}·${best.name}(${best.id}) ${best.site_num}棺`:'无'));
  }
  // 刷新结果要等列表渲染稳定再点下一次，否则会连着发刷新、漏掉中间出现的好目标。
  async function settleList(screen) {
    let previous=null;
    const end=Date.now()+3000;
    while (Date.now()<end) {
      const current=(screen._dataList||[]).map(item=>item.id).join(',');
      if (current===previous) return current;
      previous=current;
      await new Promise(resolve=>setTimeout(resolve,150));
    }
    return previous||'';
  }
  async function targets(kind,mode,refresh,minimum,excludeIds,preferredId) {
    const {cfg,Button}=config();
    const tab=mode==='fill'?1:0;
    minimum=Number(minimum)||0;
    // 目标页有官方列表入口，不必为打开列表绕回大厅。
    const otherRoot=h.ui().findOpen(cfg.MineOtherUI);
    if(otherRoot && !otherRoot.view)throw fail('目标墓藏正在释放，未发起新的导航','uncertain');
    let existing=h.ui().findOpen(cfg.MineListUI);
    if (existing && existing.mineType!=null && existing.mineType!==kindNumber(kind)) {
      await closeScreen(cfg.MineListUI);existing=null;
    }
    if (!existing) {
      await h.observe([mineService(kind).getNeighbors],async()=>{
        if (otherRoot && otherRoot._openMineType===kindNumber(kind)) await h.click(otherRoot.view.btn_list);
        else {
          if (otherRoot) await closeScreen(cfg.MineOtherUI);
          const page=await minePage(kind);
          await h.click(page.btn_other);
        }
      },()=>{
        const screen=h.ui().findOpen(cfg.MineListUI);
        return screen && screen._curSelect>=0 && Array.isArray(screen._dataList);
      });
    }
    const screen=await h.wait(()=>h.ui().findOpen(cfg.MineListUI),'墓葬目标列表未打开');
    const view=h.ui().find(cfg.MineListUI);
    if (view && view.waitAfterOpen) await h.bounded(view.waitAfterOpen,'墓藏列表打开尚未完成');
    await settleList(screen);
    if (screen._curSelect!==tab) {
      const before=screen._dataList;
      await h.observe([mineService(kind).getNeighbors],()=>h.click(screen.view.btnTabGroup.children[tab].getComponent(Button)),
        ()=>screen._curSelect===tab && screen._dataList!==before);
      await settleList(screen);
    }
    // 刷新会整批换掉列表：只有当前列表里的目标才点得进去，所以刷到达标目标就立刻停。
    const discovered=new Set(), everSeen=new Set();
    let count=0, list=screen._dataList||[];
    const current=()=>rowsOf(list,mode);
    const excluded=new Set(excludeIds||[]);
    const reached=()=>current().some(item=>!excluded.has(item.id) && (!preferredId || item.id===preferredId) && minimum>0 && item.site_num>=minimum);
    const note=(label)=>{ if (h.log) h.log(label); };
    if (reached()) note(`${kind==='sanshi'?'三尸':'法器'}墓当前列表已有≥${minimum}棺的目标，无需刷新`);
    // 多轮刷新只用于盗掠扫描；填土仍只取一次列表，避免超出任务超时。
    if (refresh && mode==='raid') {
      while (count<REFRESH_MAX && !reached()) {
        const before=screen._dataList;
        await h.observe([mineService(kind).getNeighbors],()=>h.click(screen.view.btn_refresh),
          ()=>screen._dataList!==before,20000);
        count++;
        await settleList(screen);
        list=screen._dataList||[];
        const fresh=list.filter(item=>!everSeen.has(item.id));
        list.forEach(item=>everSeen.add(item.id));
        fresh.forEach(item=>discovered.add(item.id));
        report(kind,mode,count,discovered,bestOf(current()),fresh.length,list.length);
        if (reached()) note(`第${count}次刷新后出现≥${minimum}棺的目标，停止刷新`);
        // 至少刷新五次；之后只要还能刷出新玩家就继续，刷不出新人即结束本轮。
        else if (count>=REFRESH_MIN && fresh.length===0) break;
      }
    } else if (refresh) {
      const before=screen._dataList;
      await h.observe([mineService(kind).getNeighbors],()=>h.click(screen.view.btn_refresh),
        ()=>screen._dataList!==before,20000);
      count=1;
      await settleList(screen);
      list=screen._dataList||[];
      report(kind,mode,count,new Set(list.map(item=>item.id)),bestOf(current()),list.length,list.length);
    }
    return {targets:current(),refresh_count:count,new_players:discovered.size,reached_minimum:reached()};
  }
  function otherPage(root,kind) {
    return root && root.view && (kind==='sanshi'?root.view.mine_other_sanshi:root.view.mine_other_magic_artifact);
  }
  function navigating() {
    const which=config().cfg.PageTurning;
    if(!which)return false;
    const retained=h.ui().find(which);
    return !!h.ui().findOpen(which) || !!(retained && (retained.loading || retained.showing));
  }
  async function readyOther(_root,kind,id) {
    const cfg=config().cfg, view=h.ui().find(cfg.MineOtherUI);
    if(view && view.waitAfterOpen)await h.bounded(view.waitAfterOpen,'目标墓藏打开尚未完成');
    // The native list callback destroys the previous MineOtherUI before asynchronously creating its replacement.
    // Reacquire it on every observation; never retain the pre-transition component or dereference its released view.
    return await h.wait(()=>{
      if(navigating())return false;
      const root=h.ui().findOpen(cfg.MineOtherUI),retained=h.ui().find(cfg.MineOtherUI);
      if(!root || root.isValid===false || !root.view || retained && (retained.loading || retained.showing===false))return false;
      const page=otherPage(root,kind);
      return page && (!page.node || page.node.activeInHierarchy!==false) &&
        page._targetId===id && page._loadedTargetId===id && !page._helpBusy &&
        page.btn_help && page.btn_help.interactable!==false && page;
    },'目标墓藏信息仍在加载、切换或目标不匹配');
  }
  async function other(kind,id,mode) {
    const {cfg}=config();const active=h.ui().findOpen(cfg.MineOtherUI);
    if(active && !active.view)throw fail('目标墓藏正在释放，停止切换玩家','uncertain');
    const activePage=otherPage(active,kind),sameKind=active &&
      (active._mineType===undefined || active._mineType===kindNumber(kind));
    if(activePage && sameKind && activePage._targetId===id)return await readyOther(active,kind,id);
    if(active) {
      // The next-player button keeps the existing page alive and awaits its native transition.
      if(activePage && sameKind && active._openMineType===kindNumber(kind) &&
         Array.isArray(active.targetIds) && active.targetIds[active.targetIndex+1]===id && active.view.btn_next) {
        await readyOther(active,kind,activePage._targetId);
        await h.click(active.view.btn_next);
        return await readyOther(null,kind,id);
      }
      // Non-adjacent target: finish the normal back/close lifecycle before opening a new list.
      // Do not launch gotoOtherMine while the old MineOtherUI is still being destroyed.
      await h.home();
      await h.wait(()=>!h.ui().findOpen(cfg.MineOtherUI) && !navigating(),'旧目标墓藏尚未退出，未切换玩家');
    }
    let screen=h.ui().findOpen(cfg.MineListUI);
    if (!screen || screen._curSelect!==(mode==='fill'?1:0)) {
      await targets(kind,mode,false);screen=h.ui().findOpen(cfg.MineListUI);
    }
    const index=screen._dataList.findIndex(t=>t.id===id);
    if (index<0) throw fail('目标已不在当前UI列表','rejected');
    const node=await h.listNode(screen.view.list_record,index),Type=await h.uiClass('mine-list-item.ts','MineListItem');
    const item=await h.wait(()=>{
      const rendered=node.getComponent(Type);
      return rendered && rendered._data && rendered._data.id===id && rendered;
    },'目标列表条目仍在更新');
    if (!screen._dataList[index] || screen._dataList[index].id!==id) throw fail('目标列表已更新，请重新扫描','rejected');
    await h.click(item.btn_goto);
    const root=await h.wait(()=>h.ui().findOpen(cfg.MineOtherUI),'目标墓藏页未打开');
    return await readyOther(root,kind,id);
  }
  async function fill(kind,id) {
    const before=self(kind).helpNumDay,page=await other(kind,id,'fill');
    if (!page._sameLegion) throw fail('当前目标不是可正常填土的同阴司玩家','rejected');
    const response=await h.observe([mineService(kind).legionHelp],()=>h.click(page.btn_help),()=>self(kind).helpNumDay>before);
    await h.dismissRewards(response && response.items && response.items.length>0);
    try { await readyOther(h.ui().findOpen(config().cfg.MineOtherUI),kind,id); }
    catch(e) { throw fail('填土已确认，但目标页尚未完成刷新，停止重复操作','uncertain'); }
    return {confirmed:true};
  }
  // 结算页没有已核实的关闭按钮时，按用户操作习惯点击页面空白处退出。
  async function dismissByBlank(which,root) {
    const {cc}=config();
    const node=root && root.node;
    if (!node || typeof node.emit!=='function') return false;
    const type=cc && cc.Node && cc.Node.EventType ? cc.Node.EventType.TOUCH_END : 'touch-end';
    try {
      await retryUI(()=>node.emit(type,{type}),()=>!h.ui().findOpen(which),'结算页点击空白处未关闭');
    } catch (e) { return false; }
    return true;
  }
  async function resultScreen(which) {
    const root=await h.wait(()=>h.ui().findOpen(which),'战斗结算页面未显示');
    const view=h.ui().find(which);
    if (view && view.waitAfterOpen) await h.bounded(view.waitAfterOpen,'结算页打开未完成');
    const result=view && view.params && view.params[0];
    if (!result || ![0,1].includes(result.result)) throw fail('战斗结算结果未核实','uncertain');
    if (root.closeInteractable===false) await h.wait(()=>root.closeInteractable,'结算页暂不可关闭');
    const buttons=root.node && typeof root.node.getComponentsInChildren==='function'
      ? root.node.getComponentsInChildren(config().cc.Button) || [] : [];
    const close=buttons.find(b=>(b.clickEvents||[]).some(e=>e.handler==='close') || b.clickCallback===root.close);
    const control=root.view.btn_close || root.view.button_close || close;
    if (control) await retryUI(()=>h.click(control),()=>!h.ui().findOpen(which),'战斗结算页面仍未关闭');
    else if (!await dismissByBlank(which,root)) throw fail('战斗结算页未能正常退出','uncertain');
    if (view.waitAfterClose) await h.bounded(view.waitAfterClose,'战斗结算关闭未完成');
    await h.wait(()=>!h.ui().findOpen(which),'战斗结算页面仍未关闭');
    return {confirmed:true,win:result.result===1};
  }
  async function waitBattleResult(resultCfg) {
    const battleCfg=await battle('MineBattleUI');
    if (!battleCfg) throw fail('战斗界面配置未解析，未进入战斗','unavailable');
    const started=Date.now();
    while (!h.ui().findOpen(resultCfg)) {
      const screen=h.ui().findOpen(battleCfg);
      const skip=screen && screen.view && screen.view.btn_skip;
      // 进战斗就点官方跳过，然后等结算页出现。
      if (skip && skip.node.activeInHierarchy!==false && skip.interactable!==false) await h.click(skip);
      if (Date.now()-started>120000) throw fail('战斗尚未产生正常结算，停止继续挑战','uncertain');
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    return await resultScreen(resultCfg);
  }
  async function raid(kind,id) {
    const page=await other(kind,id,'raid'),{cfg}=config();
    if (page._sameLegion) throw fail('同阴司目标不可盗掠','rejected');
    const battleCfg=await battle('MineBattleUI');
    if (!battleCfg) throw fail('战斗界面配置未解析，未发起盗掠','unavailable');
    await h.observe([mineService(kind).startRob],()=>h.click(page.btn_help,{waitCompletion:false}),()=>!!h.ui().findOpen(battleCfg));
    const receipt=await waitBattleResult(cfg.MinePveBattleResultUI);
    // 官方结算关闭回调会打开 MainUI 再 gotoMine；等待它完成，避免抢先另开一遍。
    try {
      await h.wait(()=>h.ui().findOpen(cfg.MineUI),'盗掠结算后尚未返回墓藏');
      const view=h.ui().find(cfg.MineUI);
      if (view && view.waitAfterOpen) await h.bounded(view.waitAfterOpen,'墓藏返回动画尚未完成');
    } catch(e) { throw fail('盗掠已结算，但返回墓藏尚未完成','uncertain'); }
    return receipt;
  }
  async function arenaPage() {
    const screen=await h.open(config().cfg.ArenaUI);
    await h.wait(()=>!screen.inSyncIng && (screen.opponents||screen.robotList),'斗法列表加载中');
    return screen;
  }
  async function arenaState() {
    const screen=await arenaPage();
    const tickets=g.ROLE.arena.dayBattleNum;
    const text=screen.view.label_refreshTime.string;
    const count=Number(String(text).split('/')[0]);
    if (!Number.isFinite(tickets) || !Number.isFinite(count)) throw fail('斗法剩余次数尚未同步');
    const list=screen.robotList && screen.robotList.length?screen.robotList.map(id=>({id,rank:0})):(screen.opponents||[]).map(p=>({id:p.id,rank:p.rankId}));
    return {targets:list,tickets,refresh_remaining:count};
  }
  async function arenaRefresh() {
    const screen=await arenaPage(),before=g.ROLE.arena.dayRefreshNum;
    const fn=config().defs.ArenaService.getArenaOpponent;
    await h.observe([fn],()=>h.click(screen.view.btn_refresh),()=>g.ROLE.arena.dayRefreshNum>before && !screen.inSyncIng);
    return await arenaState();
  }
  async function arenaChallenge(id) {
    const screen=await arenaPage(), {cfg,defs}=config();
    const data=screen.robotList && screen.robotList.length?screen.robotList.map(id=>({id})):(screen.opponents||[]);
    const index=data.findIndex(p=>p.id===id);
    if (index<0 || g.ROLE.arena.dayBattleNum<=0) throw fail('没有可用挑战次数或目标已变化','rejected');
    const node=await h.listNode(screen.view.list_items,index), Type=await h.uiClass('arena-item.ts','arena_item');
    const item=node.getComponent(Type);
    if (!item || (item.roleInfo?item.roleInfo.id:item.robotId)!==id) throw fail('当前渲染目标ID不匹配','rejected');
    await h.click(item.btn_challenge);
    const confirm=await h.wait(()=>h.ui().findOpen(cfg.ArenaChallengeUI),'斗法确认页未打开');
    const battleCfg=await battle('MineBattleUI');
    if (!battleCfg) throw fail('战斗界面配置未解析，未发起挑战','unavailable');
    // 战斗入口会先清界面再走转场，加载比普通请求慢：等到战斗页或结算页出现即可。
    await h.observe([defs.ArenaService.arenaChallenge],()=>h.click(confirm.view.btn_challenge,{waitCompletion:false}),
      ()=>!!h.ui().findOpen(battleCfg)||!!h.ui().findOpen(cfg.ArenaBattleResultUI),30000);
    return await waitBattleResult(cfg.ArenaBattleResultUI);
  }
  async function summonPage() {
    const {cfg}=config(),screen=await h.open(cfg.Draw);
    const index=screen.drawTypeInfos.findIndex(x=>x.cfgId===1 && x.eType===1);
    if(index<0)throw fail('常规免费召唤入口未解锁');
    await retryUI(()=>h.click(screen.view.node_pages[index].getComponent(config().Button)),
      ()=>screen.curSelectPage===index && !screen.inDrawing,'召唤页尚未就绪');
    return screen;
  }
  async function summonState() {
    await summonPage();
    const {data}=config(),clock=await serverClock(false),cd=Number(data.ConstantCfg.config.DrawAdCd)*60;
    const own=g.ROLE.recruit && g.ROLE.recruit.items.get(1),last=own?Number(own.lastFreeTime)/1000:0;
    if(!Number.isFinite(cd) || cd<=0 || !Number.isFinite(last))throw fail('免费召唤冷却配置尚未同步');
    // Match the native strict `serverTime-lastFreeTime > cooldown` test.
    return {remaining_seconds:Math.max(0,Math.ceil(last+cd-clock.server_now+0.001)),cooldown_seconds:cd};
  }
  async function closeReward(which,handler) {
    const screen=await h.wait(()=>h.ui().findOpen(which),'奖励页面尚未打开');
    if('isFinish' in screen)await h.wait(()=>screen.isFinish,'奖励动画尚未完成');
    await retryUI(async()=>{
      const current=h.ui().findOpen(which);
      if(current) {
        if('isFinish' in current)await h.wait(()=>current.isFinish,'奖励动画尚未完成');
        await h.click(h.closeControl(current,handler));
      }
    },()=>!h.ui().find(which),'奖励页面尚未关闭');
  }
  async function closeDrawRewards(cfg) {
    // A great reward opens DrawSpecialBook first; DrawReward only opens after it closes.
    await h.wait(()=>h.ui().findOpen(cfg.DrawReward) ||
      (cfg.DrawSpecialBook && h.ui().findOpen(cfg.DrawSpecialBook)),'召唤奖励或特殊秘籍展示页尚未打开');
    for(let count=0;cfg.DrawSpecialBook && h.ui().findOpen(cfg.DrawSpecialBook);count++) {
      if(count>=100)throw fail('特殊秘籍展示次数异常','uncertain');
      const screen=h.ui().findOpen(cfg.DrawSpecialBook);
      await h.wait(()=>!screen.inAni,'特殊秘籍展示动画尚未完成');
      const before=screen.drawCardId,remaining=screen.allDrawCardIds?.length;
      await retryUI(()=>h.click(h.closeControl(screen,'closeSelf')),
        ()=>!h.ui().findOpen(cfg.DrawSpecialBook) || screen.inAni ||
          screen.drawCardId!==before || screen.allDrawCardIds?.length!==remaining,
        '特殊秘籍展示页尚未推进或关闭');
    }
    await closeReward(cfg.DrawReward,'onClickClose');
  }
  async function freeSummon() {
    const info=await summonState();
    if(info.remaining_seconds>0)throw fail('免费召唤仍在冷却','rejected');
    const {cfg,defs}=config(),screen=await summonPage(),before=Number(g.ROLE.recruit.items.get(1)?.lastFreeTime || 0);
    let result;
    try {
      result=await h.observe([defs.RoleService.recruit],()=>h.click(screen.view.button_drawAd,{waitCompletion:false}),
        ()=>Number(g.ROLE.recruit.items.get(1)?.lastFreeTime || 0)>before,120000);
    } catch(error) {
      // An ad callback can arrive later; do not replay an unconfirmed click.
      if(error.status!=='rejected')error.status='uncertain';
      throw error;
    }
    if((result.baseItems || []).length || (result.coinItems || []).length)await closeDrawRewards(cfg);
    await h.wait(()=>!screen.inDrawing,'免费召唤动画尚未收尾');
    return {confirmed:true,cooldown_seconds:info.cooldown_seconds};
  }
  async function petPage() {
    const {cfg,Button}=config(),screen=await h.open(cfg.PetUI);
    const {PetPageType}=await g.System.import('chunks:///_virtual/ui-pet.ts');
    if(!PetPageType || !Number.isInteger(PetPageType.Hatch))throw fail('阴契页签枚举未解析');
    return await retryUI(()=>h.click(screen.view.node_pageList[PetPageType.Hatch].getComponent(Button)),
      ()=>screen.curPage===PetPageType.Hatch && screen.view.node_page_hatch,'阴契页面尚未加载');
  }
  async function petState(ids) {
    await petPage();
    const {data}=config(),{petHelper}=await g.System.import('chunks:///_virtual/pet-helper.ts');
    const {roleHelper}=await g.System.import('chunks:///_virtual/role-helper.ts');
    if(!Array.isArray(ids) || ids.some(id=>!Number.isInteger(id) || data.ItemCfg.getById(id)?.type!==data.ItemType.PET_ITEM))throw fail('阴契种类无效','rejected');
    const eggs=ids.map(id=>data.ItemCfg.getById(id)).filter(x=>roleHelper.getItemCount(x.id)>0 && data.PetIncubateCfg.getById(x.param?.[0]));
    eggs.sort((a,b)=>b.quality-a.quality || b.sort-a.sort || b.id-a.id);
    let claim=0;
    for(let slot=1;slot<=4;slot++)if(petHelper.checkPetHatchCompleteListSlotExist(slot)[0]>0){claim=slot;break;}
    const freeSlot=petHelper.getFreePetHatchSlot();
    const {CommonUnlockFunctionType}=await g.System.import('chunks:///_virtual/common-unlock-button.ts');
    const unlock=data.UnlockCfg.getById(CommonUnlockFunctionType.PET_HATCH_QUEUE);
    const queueUnlocked=!!unlock && roleHelper.checkCondition(unlock.condition);
    const queueCount=petHelper.getPetHatchQueueNum();
    const queueCapacity=petHelper.getUnlockedPetHatchSlotCount()*Number(data.ConstantCfg.config.PetIncubateSlotBornListNum);
    // Match native tryHatch: fill direct slots first, then its pos:0 queue branch.
    const canQueue=queueUnlocked && !petHelper.checkPetHatchFull() && !petHelper.checkPetHatchQueueFull();
    return {item_id:eggs[0]?.id || null,free_slot:freeSlot,can_place:freeSlot>0 || canQueue,
      queue_count:queueCount,queue_capacity:queueCapacity,claim_slot:claim,
      remaining_seconds:petHelper.getMinSecondsUntilPetHatchFinish() || 60};
  }
  async function petStart(id) {
    const status=await petState([id]);
    if(!status.can_place || status.item_id!==id)throw fail('阴契不足，或解封槽及队列已满／尚未解锁','rejected');
    const page=await petPage(),{defs}=config(),{roleHelper}=await g.System.import('chunks:///_virtual/role-helper.ts');
    const index=page.curEggs.indexOf(id);
    if(index<0)throw fail('所选阴契不在当前列表','rejected');
    const node=await h.listNode(page.list_eggs,index),Type=await h.uiClass('pet-egg-item.ts','PetEggItem');
    const item=node.getComponent(Type),before=roleHelper.getItemCount(id);
    if(!item || item.eggId!==id)throw fail('阴契列表条目未匹配','rejected');
    await h.observe([defs.PetService.bornPet],()=>h.click(item.btnHatch),()=>roleHelper.getItemCount(id)===before-1 &&
      (status.free_slot>0 || g.ROLE.pet.bornList.length===status.queue_count+1));
    return {confirmed:true};
  }
  async function petClaim(slot) {
    const page=await petPage(),{defs,cfg}=config(),{petHelper}=await g.System.import('chunks:///_virtual/pet-helper.ts');
    if(!Number.isInteger(slot) || slot<1 || slot>4 || petHelper.checkPetHatchCompleteListSlotExist(slot)[0]<=0)throw fail('该解封槽尚未完成','rejected');
    const Type=await h.uiClass('hatch-slot-item.ts','HatchSlotItem'),item=page.node.getComponentsInChildren(Type).find(x=>x.index===slot);
    if(!item || item.inClaim)throw fail('解封槽正在领取','rejected');
    const completed=()=>[1,2,3,4].reduce((sum,index)=>sum+petHelper.checkPetHatchCompleteListSlotExist(index)[0],0);
    // Native one-click claim is visible only for multiple completed contracts.
    if(completed()>1 && page.unlockReceiveAll && page.btn_recive_all?.node?.activeInHierarchy!==false){
      const result=await h.observe([defs.PetService.getBornPetAll],()=>h.click(page.btn_recive_all,{waitCompletion:false}),()=>completed()===0);
      await h.wait(()=>page.node.getComponentsInChildren(Type).every(x=>!x.inClaim),'一键解封动画尚未收尾');
      if((result.items || []).length){
        await h.wait(()=>h.ui().findOpen(cfg.UINewPet) || h.ui().findOpen(cfg.Congrats),'解封结果尚未显示');
        // The native full-screen close control is the blank-area tap; multiple
        // rare pets may share one result screen and need more than one tap.
        for(let count=0;h.ui().findOpen(cfg.UINewPet) && count<100;count++)
          await h.click(h.closeControl(h.ui().findOpen(cfg.UINewPet),'closeSelf'));
        await h.wait(()=>!h.ui().find(cfg.UINewPet),'鬼仆结果尚未关闭');
        await h.dismissRewards(true);
      }
      return {confirmed:true};
    }
    await h.observe([defs.PetService.getBornPet],()=>h.click(item.btn_claim),()=>!item.inClaim);
    await closeReward(cfg.UINewPet,'closeSelf');
    await h.dismissRewards();
    return {confirmed:true};
  }
  async function fodderPets() {
    const {petHelper}=await g.System.import('chunks:///_virtual/pet-helper.ts');
    const own=g.ROLE.pet,protectedIds=new Set([String(own.fightId)]);
    const plans=own.formation && own.formation.plan;
    if(plans && typeof plans.forEach==='function')plans.forEach(slots=>{
      if(slots && typeof slots.forEach==='function')slots.forEach(id=>protectedIds.add(String(id)));
    });
    return Array.from(own.bag.values()).map(p=>{
      const quality=Number(p.quality),progress=Number(p.mergerCount);
      return {id:p.id,quality,progress,eligible:Number.isInteger(quality) && quality>=2 && quality<=4 &&
        Number.isInteger(progress) && progress>=0 && p.lock===0 && !protectedIds.has(String(p.id)) && petHelper.checkPetInFormation(p.id)===-1};
    });
  }
  async function fodderPage() {
    const {cfg,Button}=config(),screen=await h.open(cfg.PetUI);
    const {PetPageType}=await g.System.import('chunks:///_virtual/ui-pet.ts');
    if(!Number.isInteger(PetPageType?.QualityUp))throw fail('献祭页签枚举未解析');
    const page=await retryUI(()=>h.click(screen.view.node_pageList[PetPageType.QualityUp].getComponent(Button)),
      ()=>screen.curPage===PetPageType.QualityUp && screen.view.node_page_qualityUp,'献祭页面尚未加载');
    return {screen,page};
  }
  async function fodderMerge(pair) {
    const {cfg,defs,data}=config();
    const validate=async()=>{
      const pets=await fodderPets(),target=pets.find(p=>p.id===pair.target_id),material=pets.find(p=>p.id===pair.material_id);
      if(!target?.eligible || !material?.eligible || target.id===material.id || target.quality!==material.quality ||
         target.quality!==pair.quality || target.progress!==pair.target_progress || material.progress!==pair.material_progress)
        throw fail('献祭目标、材料或进度已变化，未执行合成','rejected');
      const legal=target.progress===0 && material.progress===0 || target.progress===1 && material.progress===1 ||
        target.progress>=3 && (target.progress===3 || target.progress>=7) && material.progress===3;
      if(!legal)throw fail('不符合狗粮合成进度策略','rejected');
      const {petHelper}=await g.System.import('chunks:///_virtual/pet-helper.ts');
      if(!petHelper.getQualityUpCanUsePets(target.id).includes(material.id))throw fail('材料不符合游戏献祭规则','rejected');
      return {target,material};
    };
    await validate();
    const {screen,page}=await fodderPage();
    const index=screen.petList.findIndex(p=>p.id===pair.target_id);
    if(index<0)throw fail('献祭目标不在当前鬼仆列表','rejected');
    if(screen.curSelectId!==pair.target_id)await h.click(await h.listNode(screen.view.list_pet,index));
    await h.wait(()=>screen.curSelectId===pair.target_id && page.curSelectPetId===pair.target_id,'献祭目标尚未选中');
    await h.click(page.node_unSelect.active?page.btn_openSelect:page.btn_openSelect2);
    await h.wait(()=>page.node_selectRoot.active,'献祭材料列表未展开');
    const mi=page.canUseInfos.findIndex(p=>p.type==='pet' && p.id===pair.material_id);
    if(mi<0)throw fail('指定鬼仆不在可献祭材料列表','rejected');
    const current=page.curUseInfos[page.curUseIndex];
    if(current?.type!=='pet' || current.id!==pair.material_id)await h.click(await h.listNode(page.list_selectItem,mi));
    const chosen=page.curUseInfos.filter(Boolean);
    if(chosen.length!==1 || chosen[0].type!=='pet' || chosen[0].id!==pair.material_id)throw fail('献祭材料选择未确认','rejected');
    await retryUI(()=>h.click(page.btn_closeSelect2),()=>!page.node_selectRoot.active,'献祭材料列表尚未关闭');
    const {target,material}=await validate();
    const minimum=Number(data.PetQualityCfg.getById(target.quality)?.minNum);
    if(!Number.isFinite(minimum) || minimum<=0)throw fail('献祭进阶配置未同步');
    const overflow=target.progress+material.progress>minimum;
    const result=await h.observe([defs.PetService.petMerge],async()=>{
      await h.click(page.btn_qualityUp,{waitCompletion:false});
      if(overflow){
        const dialog=await h.wait(()=>h.ui().findOpen(cfg.CommonConfirm),'献祭溢出确认未显示');
        if(!String(dialog.view.label_desc?.string || '').includes('燃魂灯亮度将会溢出'))
          throw fail('献祭出现未预期的确认弹窗，已停止','uncertain');
        await h.click(dialog.view.btn_confirm,{waitCompletion:false});
      }
    },()=>{
      const after=g.ROLE.pet.bag.get(target.id);
      return !g.ROLE.pet.bag.has(material.id) && after && (Number(after.quality)>target.quality || Number(after.mergerCount)!==target.progress);
    });
    const after=g.ROLE.pet.bag.get(target.id),advanced=Number(after.quality)>target.quality;
    if(advanced)await closeReward(cfg.UIPetQualityUp,'close');
    await h.dismissRewards((result.items || []).length>0);
    return {confirmed:true,advanced,quality:Number(after.quality),progress:Number(after.mergerCount)};
  }
  return {async dispatch(op,args) {
    if(op==='pet_fodder_state')return {pets:await fodderPets()};
    if(op==='pet_fodder_merge')return await fodderMerge(args);
    if(op==='free_summon_state')return await summonState();
    if(op==='free_summon')return await freeSummon();
    if(op==='pet_hatch_state')return await petState(args.item_ids);
    if(op==='pet_hatch_start')return await petStart(args.item_id);
    if(op==='pet_hatch_claim')return await petClaim(args.slot);
    if(op==='tomb_state')return await state(args.kind,args.counts_only);
    if(op==='tomb_collect')return await collect(args.kind);
    if(op==='tomb_start')return await start(args.kind);
    if(op==='tomb_recruit')return await recruit(args.kind);
    if(op==='tomb_targets')return await targets(args.kind,args.mode,args.refresh,args.minimum,args.exclude_ids,args.preferred_id);
    if(op==='tomb_fill')return await fill(args.kind,args.id);
    if(op==='tomb_raid')return await raid(args.kind,args.id);
    if(op==='arena_state')return await arenaState();
    if(op==='arena_refresh')return await arenaRefresh();
    if(op==='arena_challenge')return await arenaChallenge(args.id);
    throw fail('未知日常操作');
  }};
}
