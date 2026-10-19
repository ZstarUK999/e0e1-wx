// 已核对的日常UI链路。只读自身计数和公开列表，动作仅h.click触发正常事件。
function createDailyRuntime(g,h) {
  const fail=(message,status)=>Object.assign(new Error(message),{status:status||'unavailable'});
  const config=()=>h.configuration();
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
    if (root._mineType!==index) await h.click(index===0?root.view.btn_sanshi:root.view.btn_magic_artifact);
    const page=index===0?root.view.mine_sanshi:root.view.mine_magic_artifact;
    await h.wait(()=>root._mineType===index && page && page.node.activeInHierarchy!==false,'墓藏页面未就绪');
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
    await h.click(button);
    if (view.waitAfterClose) await h.bounded(view.waitAfterClose,'页面关闭未完成');
    await h.wait(()=>!h.ui().findOpen(which),'页面关闭未完成');
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
    node.emit(type,{type});
    try {
      await h.wait(()=>!h.ui().findOpen(which),'结算页点击空白处未关闭');
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
    if (control) await h.click(control);
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
  return {async dispatch(op,args) {
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
