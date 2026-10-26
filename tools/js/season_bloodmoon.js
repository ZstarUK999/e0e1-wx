// ==UserScript==
// @name 血月战场·战旗探测／赶路／挑战／隐匿行军显示
// @description 读取已同步的旗帜、行军和队列数据；显示隐匿玩家头像及原生行军路线；赶路与挑战直接调用游戏接口。
// @match *
// @run-at document-start
// @e0e1-mode runtime_toggle
// ==/UserScript//

// 说明：本脚本以语句形式直接执行（e0e1 的注入包装是 async 函数，可直接使用 await）。
// 用法：GUI 血月战场页点「启用」；CLI 用
//   python tools/cdp_inject.py --port 62000 --toggle tools/js/season_bloodmoon.js
//
// 边界（与 血月调查与插件设计.md 一致）：
//   · 只读：不改写角色状态；赶路按配置间隔请求，剩余低于8秒停止。
//   · 赶路和挑战走游戏原有请求接口，并确认真实回执；请求没确认就报 uncertain，不重试。
//   · 仅显示客户端已同步的行军数据，保留角色真实状态及原生挑战资格。

await (async function () {
  var g = globalThis, VERSION = '2026-10-24-routes-v17', restored = null;
  if (g.e0e1Season) {
    if (g.e0e1Season.version === VERSION) return;
    var previous = await g.e0e1Season.diagnose();
    if (!previous.ok || previous.pending || previous.outstanding || previous.uncertain)
      throw new Error('旧血月脚本仍有在途操作或结果未知，暂不升级，请等待完成或核实后复位');
    var begin = (previous.trace || []).find(function (row) { return row.step === 'diagnose.begin'; });
    if (!begin || !begin.values) throw new Error('旧血月计数无法核实，不重置次数，请重新进入游戏后加载');
    restored = begin.values;
    await g.e0e1Season.stop();
    if (g.e0e1Season.detachBattleObserver) g.e0e1Season.detachBattleObserver();
  }

  var lib = {};
  var actionTrace = null, serial = 0;
  function trace(step, values) {
    // Freeze before awaiting: later map sync must not rewrite earlier evidence.
    var snapshot;
    try { snapshot = JSON.parse(JSON.stringify(values || {})); }
    catch (e) { snapshot = { serializationError: String(e), fields: Object.keys(values || {}) }; }
    var row = { step: step, at: Date.now(), values: snapshot };
    if (actionTrace) actionTrace.push(row);
    // 高频只读扫描保留结构化回执，不重复写入游戏控制台。
    if (!/^(candidates|march|flags|diagnose)\.(begin|end)$/.test(step)) {
      try { g.console.info('[bloodmoon]', JSON.stringify(row)); } catch (e) { }
    }
  }
  function traceException(step, error, values) {
    trace(step, { error: String(error), stack: error && error.stack, context: values || {} });
  }
  function exportCall(name, fn) {
    return async function (args) {
      var mutating = name === 'speedUp' || name === 'attack';
      var ownTrace = [], id = ++serial;
      // A concurrent read must not replace the in-flight action's trace.
      if (!actionTrace) actionTrace = ownTrace;
      trace(name + '.begin', { id: id, args: args || {}, pending: state.pending,
        uncertain: state.uncertain, outstanding: state.outstanding,
        lastAttackAt: state.lastAttackAt, marchKey: state.marchKey, speedTimes: state.speedTimes, battles: state.battles,
        lastSpeedAt: state.lastSpeedAt, finalSpeedAttempted: state.finalSpeedAttempted,
        attackObservation: state.attackObservation,
        systemPresent: !!g.System, uiPresent: !!g.UIManager, rolePresent: !!g.ROLE,
        modulePresent: !!g.seasonModule, warId: g.seasonModule && g.seasonModule.enteredMapId });
      var result;
      try { result = await fn(args); }
      catch (e) {
        trace(name + '.exception', { message: String(e), stack: e && e.stack });
        result = bad(String(e), mutating ? 'uncertain' : 'unavailable');
      }
      // Read results already cross the bridge once. Do not deep-copy the whole
      // queue/flag roster into its own trace on every high-frequency poll.
      trace(name + '.end', { id: id, result: mutating ? result : {
        ok: result.ok, status: result.status, message: result.message,
        attackCount: result.attack && result.attack.length,
        defenseCount: result.defense && result.defense.length,
        groupCount: result.groups && result.groups.length
      } });
      if (mutating) result.request_sent = !!state.dispatched;
      result.trace = ownTrace.slice();
      if (actionTrace === ownTrace) actionTrace = null;
      return result;
    };
  }
  var state = {
    lastSpeedAt: restored ? num(restored.lastSpeedAt) : 0,
    finalSpeedAttempted: restored ? !!restored.finalSpeedAttempted : false,
    attackObservation: restored ? restored.attackObservation || null : null,
    lastAttackAt: restored ? num(restored.lastAttackAt) : 0,
    dispatched: false,
    markError: null,
    outstanding: 0,
    pending: false,        // 有动作在途，禁止并发
    uncertain: false,      // 上次动作结果未知，停止后续自动动作
    marks: [],             // 已挂的「隐匿中」节点
    markTimer: null,
    speedTimes: restored ? num(restored.speedTimes) : 0,         // 本次行军已成功加速次数
    marchKey: restored ? String(restored.marchKey || '') : '',          // 当前行军标识，变了就重置计数
    battles: restored ? num(restored.battles) : 0             // 本轮自动攻击已发起场次
  };

  function log(m) { try { g.console.info('[plugin.ui]', String(m)); } catch (e) { } }
  function bad(message, status) { if (status === 'uncertain') state.uncertain = true; trace('branch.stop', {status: status || 'unavailable', message: String(message)}); return { ok: false, status: status || 'unavailable', message: String(message) }; }
  function done(payload) { var out = { ok: true, status: 'ok' }; for (var k in (payload || {})) out[k] = payload[k]; return out; }
  function chunk(name) { return g.System.import('chunks:///_virtual/' + name); }

  async function libs() {
    if (!g.System || !g.ROLE) throw new Error('游戏尚未就绪');
    if (!lib.cc) lib.cc = await g.System.import('cc');
    if (!lib.defs) lib.defs = await chunk('define-index.ts');
    if (!lib.data) lib.data = await chunk('configs.ts');
    if (!lib.helper) lib.helper = (await chunk('role-helper.ts')).roleHelper;
    if (!lib.uiConfig) lib.uiConfig = (await chunk('ui-common-cfg.ts')).CommonUICfgId;
    if (!lib.uiConfig || typeof lib.helper.getItemCount !== 'function') throw new Error('游戏UI配置或道具接口未就绪');
    if (!lib.manager) lib.manager = (await chunk('service-manager.ts')).ServiceManager.ins;
    if (!lib.signalMod) lib.signalMod = await chunk('season-map-signal.ts');
    bindBattleObserver();
    if (!lib.cellType) lib.cellType = (await chunk('season-queue-detail-role-cell.ts')).SeasonQueueDetailRoleCell;
    if (!lib.opCellType) lib.opCellType = (await chunk('season-op-queue-cell.ts')).SeasonOpQueueCell;
    return lib;
  }

  // The native PvP end notification can arrive between two polling snapshots.
  // Match our own accepted challenge, never infer completion from elapsed time.
  var battleSignal = null;
  function detachBattleObserver() {
    if (battleSignal) battleSignal.off(onBattleExit, state);
    battleSignal = null;
  }
  function onBattleExit(event) {
    var observation = state.attackObservation, m = module_(), me = myRole();
    if (!observation || !event || event.isRobot !== false || event.isMeAtk !== true ||
        !m || !me || String(m.enteredMapId) !== observation.warId ||
        num(me.id) !== observation.selfId || num(event.other) !== observation.targetId ||
        String(event.buildingId) !== observation.buildingId) return;
    observation.completed = true;
    detachBattleObserver();
  }
  function bindBattleObserver() {
    if (battleSignal || !state.attackObservation || state.attackObservation.completed) return;
    var signals = lib.signalMod && lib.signalMod.SeasonMapInnerSignal;
    var signal = signals && signals.mySeasonRoleExitedBattle;
    if (signal && typeof signal.on === 'function' && typeof signal.off === 'function') {
      signal.on(onBattleExit, state);
      battleSignal = signal;
    }
  }

  function module_() { return g.seasonModule || null; }
  function mapData() {
    var m = module_();
    if (m && typeof m.getSeasonMapData === 'function') {
      try { var d = m.getSeasonMapData(); if (d) return d; } catch (e) { traceException('mapData.exception', e); }
    }
    return g.SEASON_MAP || null;
  }
  function myRole() {
    var m = module_();
    if (m && typeof m.getSeasonMapMyRole === 'function') {
      try { var r = m.getSeasonMapMyRole(); if (r) return r; } catch (e) { traceException('myRole.exception', e); }
    }
    return null;
  }
  function each(mapLike, fn) {
    if (!mapLike) return;
    if (typeof mapLike.forEach === 'function') { mapLike.forEach(fn); return; }
    for (var k in mapLike) { if (Object.prototype.hasOwnProperty.call(mapLike, k)) fn(mapLike[k], k); }
  }
  function num(v, d) { var n = Number(v); return isFinite(n) ? n : (d || 0); }

  async function serverNow(strict) {
    try {
      if (!lib.clock) lib.clock = (await chunk('date-util.ts')).default;
      var clock = lib.clock;
      if (clock && Number(clock.serverTime) > 0) return Number(clock.serverTime);
    } catch (e) { trace('clock.exception', { strict: !!strict, message: String(e), stack: e && e.stack }); }
    if (strict) return 0;
    return Date.now();
  }

  function flagConfig(id) {
    var m = module_();
    try {
      var data = m && m.seasonBattleFlagData;
      var cfg = data && typeof data.getFlagConfig === 'function' ? data.getFlagConfig(id) : null;
      return cfg || null;
    } catch (e) { traceException('flagConfig.exception', e, {flagId:id}); return null; }
  }
  function flagName(id) {
    var cfg = flagConfig(id);
    if (cfg && cfg.name) return String(cfg.name);
    if (!num(id)) return '';
    return '#' + id;
  }
  function flagNote(id) {
    var cfg = flagConfig(id);
    if (!cfg) return '';
    var bits = [];
    if (cfg.restraint) bits.push('克' + flagName(cfg.restraint));
    if (cfg.beRestraint) bits.push('弱' + flagName(cfg.beRestraint));
    return bits.join(' ');
  }
  function isStealth(role) {
    try {
      var ext = role && role.ext;
      var v = ext && typeof ext.get === 'function' ? ext.get(4) : (ext ? ext[4] : 0);
      return parseInt(v, 10) > 0;
    } catch (e) { traceException('stealth.exception', e, {roleId:role && role.id}); return false; }
  }
  function stateName(s) {
    return { 0: '未入场', 1: '待命', 2: '行军', 3: '战斗', 4: '阵亡', 5: '观战' }[num(s, 0)] || ('状态' + s);
  }
  function constants() {
    try { return (lib.data && lib.data.SeasonConstantCfg && lib.data.SeasonConstantCfg.config) || null; } catch (e) { traceException('constants.exception', e); return null; }
  }
  function openUI(id) {
    var cfg = lib.uiConfig && lib.uiConfig[id];
    return cfg && g.UIManager && g.UIManager.ins ? g.UIManager.ins.findOpen(cfg) : null;
  }

  async function directRequest(name, params) {
    var fn = lib.defs.SeasonService && lib.defs.SeasonService[name];
    if (typeof fn !== 'function' || !lib.manager || typeof lib.manager.service !== 'function')
      throw new Error('游戏请求接口尚未就绪：' + name);
    state.dispatched = true; state.outstanding++;
    trace('rpc.sent', {method:name, params:params});
    var pending;
    try { pending = Promise.resolve(lib.manager.service(fn, params)); }
    catch (e) { state.outstanding--; throw e; }
    var settled = pending.then(function(value){state.outstanding--;return value;},
      function(error){state.outstanding--;throw error;});
    var value = await new Promise(function(resolve,reject){
      var timer=setTimeout(function(){reject(new Error('请求超时，结果未知'));},8000);
      settled.then(function(value){clearTimeout(timer);resolve(value);},
        function(error){clearTimeout(timer);reject(error);});
    });
    trace('rpc.settled', {method:name, value:value});
    return {called:true,settled:true,count:1,error:'',value:value};
  }

  function checkReceipt(receipt, label) {
    if (!receipt.called || !receipt.settled || receipt.count !== 1 || receipt.error)
      return bad(label + '请求没有唯一明确回执：' + JSON.stringify(receipt), 'uncertain');
    var value = receipt.value;
    if (!value || !Object.prototype.hasOwnProperty.call(value, 'err'))
      return bad(label + '回执格式未核实', 'uncertain');
    if (value.err) return bad(label + '被拒绝：' + JSON.stringify(value.err), 'rejected');
    if (value.err !== null) return bad(label + '成功标志未核实', 'uncertain');
    return null;
  }

  function marchIdentity(m, me, move) {
    if (!me || num(me.state) !== 2) return '';
    if (!move) return state.marchKey;
    // arrive changes after speed-up; start may also be supplied by a later sync.
    // Retain the budget until an idle state or a different route is observed.
    return [m.enteredMapId, me.id, move.to && move.to.x, move.to && move.to.y].join(':');
  }
  function syncMarch(m, me, move) {
    var key = marchIdentity(m, me, move);
    if (key !== state.marchKey) {
      trace('march.budget', { previous: state.marchKey, next: key, previousTimes: state.speedTimes,
        start: move && move.start, arrive: move && move.arrive });
      state.marchKey = key; state.speedTimes = 0; state.finalSpeedAttempted = false;
    }
    return key;
  }

  // ── 只读：战旗探测 ──

  function groupsFromMap(data) {
    var roles = data && data.roles, legions = data && data.legions, byLegion = new Map();
    each(roles, function (role) {
      if (!role) return;
      var key = num(role.lId, 0);
      if (!byLegion.has(key)) byLegion.set(key, []);
      byLegion.get(key).push(role);
    });
    var groups = [];
    byLegion.forEach(function (list, lid) {
      var legion = legions && typeof legions.get === 'function' ? legions.get(lid) : null;
      list.sort(function (a, b) { return num(b && b.planPower && b.planPower[0]) - num(a && a.planPower && a.planPower[0]); });
      var total = 0;
      var members = list.map(function (r) {
        total += num(r.power);
        return {
          roleId: num(r.id), name: r.name || '',
          power: Array.isArray(r.planPower) && r.planPower.length ? num(r.planPower[0]) : null,
          season_power: Array.isArray(r.planPower) && r.planPower.length > 1 ? num(r.planPower[1]) : null,
          total_power: num(r.power),
          flagId: num(r.flagId), flag: flagName(r.flagId), flagLv: num(r.flagLv),
          skillLv: num(r.flagSkillLv), state: num(r.state), stateName: stateName(r.state),
          stealth: isStealth(r), note: flagNote(r.flagId)
        };
      });
      groups.push({
        legionId: lid,
        title: (legion && (legion.name || legion.img)) || (lid > 0 ? '阴司#' + lid : '未分配'),
        power: num(legion && legion.power) || total,
        members: members
      });
    });
    groups.sort(function (a, b) { return b.power - a.power; });
    return groups;
  }

  function groupsFromPreview(m) {
    // 入场前只有报名名单（成员 roleId），没有战旗字段：如实标成「战旗未下发」。
    var preview = m && m.season_preview;
    var infos = preview && preview.legionSeason ? preview.legionSeason.bTimeInfos : null;
    if (!infos || !infos.size) return null;
    var groups = [];
    each(infos, function (info, bTimeId) {
      var ids = (info && info.members) || [];
      var members = ids.map(function (id) {
        return { roleId: num(id), name: '#' + id, power: 0, flagId: 0, flag: '未下发',
                 flagLv: 0, skillLv: 0, state: 0, stateName: '', stealth: false, note: '战旗未下发' };
      });
      groups.push({ legionId: num(bTimeId), title: '本阴司报名（bTime ' + bTimeId + '）', power: 0, members: members });
    });
    return groups;
  }

  async function flags() {
    await libs();
    var m = module_();
    if (!m) return bad('血月模块尚未初始化（未进入赛季界面）');
    var data = mapData();
    var now = await serverNow();
    var source = 'none', groups = [];
    if (data && data.roles && data.roles.size) { source = 'season_map'; groups = groupsFromMap(data); }
    else {
      var preview = groupsFromPreview(m);
      if (preview) { source = 'preview_signup'; groups = preview; }
    }
    var me = myRole();
    return done({
      source: source, server_now: now, war_id: (m && m.enteredMapId) || '',
      self: me ? { roleId: num(me.id), name: me.name || '', power: num(me.power),
                   flagId: num(me.flagId), flag: flagName(me.flagId), state: num(me.state),
                   stateName: stateName(me.state), stealth: isStealth(me) } : null,
      groups: groups
    });
  }

  // ── 只读：行军与加速可用性 ──

  async function march(args) {
    args = args || {};
    await libs();
    var m=module_(), me=myRole(), data=mapData();
    if (!m || !me) return bad('当前没有自己的战场角色（可能还未入场）');
    var move=data && data.moveInfos && data.moveInfos.get(me.id);
    var now=await serverNow(true), conf=constants() || {};
    syncMarch(m,me,move);
    var configured=num(args.interval_seconds), cd=Number(conf.MarchSpeedUpCD);
    var interval=configured>0?configured:cd;
    var remainMs=move?num(move.arrive)-now:0;
    var finalWindow=remainMs>=8000 && remainMs<=10000;
    var cooldownUntil=state.lastSpeedAt ? state.lastSpeedAt+interval*1000 : 0;
    var item=conf.MarchSpeedUpItem, itemReady=false, itemNeed='';
    if(Array.isArray(item) && item.length>=2){
      try {itemReady=num(lib.helper.getItemCount(item[0]),-1)>=num(item[1]);}catch(e){traceException('item.exception',e);}
      itemNeed=item[0]+'×'+item[1];
    }
    var reasons=[];
    if(!now)reasons.push('服务器时钟未就绪');
    if(!isFinite(interval) || interval<0)reasons.push('加速间隔配置未就绪');
    if(num(me.state)!==2 || !move || !move.to)reasons.push('当前没有正在进行的行军');
    if(remainMs<8000)reasons.push('剩余不足8秒，不再赶路');
    if(cooldownUntil>now)reasons.push('等待赶路间隔（剩余'+Math.ceil((cooldownUntil-now)/1000)+'秒）');
    if(!itemReady)reasons.push('赶路道具不足（'+itemNeed+'）');
    if(finalWindow && state.finalSpeedAttempted)reasons.push('本次行军已尝试最后一次赶路');
    return done({war_id:m.enteredMapId,march_key:state.marchKey,server_now:now,
      self:{roleId:num(me.id),name:me.name||'',state:num(me.state),stateName:stateName(me.state)},
      move:move?{from:move.from,to:move.to,start:num(move.start),arrive:num(move.arrive),remain_ms:remainMs}:null,
      speed_up:{available:reasons.length===0,reasons:reasons,times:state.speedTimes,
        cool_down_until:cooldownUntil,interval_seconds:interval,min_remain_seconds:8,
        final_window:finalWindow,final_attempted:state.finalSpeedAttempted,item_ready:itemReady,item_need:itemNeed},
      constants:{MarchSpeedUpCD:cd,MarchSpeedUpMinTime:num(conf.MarchSpeedUpMinTime)}});
  }

  // Direct native service request; UI selection and UI's 10-second cutoff are not used.
  async function speedUp(args) {
    args=args || {};
    if(state.pending)return bad('上一条命令尚未结束','waiting');
    if(state.uncertain)return bad('前次操作结果未知，已停止自动操作','uncertain');
    state.pending=true;state.dispatched=false;
    try {
      var fresh=await march(args);
      if(!fresh.ok)return fresh;
      if(!fresh.speed_up.available)return bad(fresh.speed_up.reasons.join('；'),'waiting');
      var limit=num(args.max_times);
      if(limit>0 && state.speedTimes>=limit)return bad('本次行军赶路已达上限','waiting');
      var fn=lib.defs.SeasonService && lib.defs.SeasonService.moveSpeedUp;
      if(typeof fn!=='function' || !lib.manager || typeof lib.manager.service!=='function')
        return bad('赶路请求接口未就绪','unavailable');
      // No await between the final state check and dispatch.
      var me=myRole(),data=mapData(),move=data && data.moveInfos && me && data.moveInfos.get(me.id);
      var now=Number(lib.clock.serverTime),remaining=move?num(move.arrive)-now:0;
      if(!me || num(me.state)!==2 || !move || !move.to || !isFinite(now) || now<=0 || remaining<8000 ||
          String(module_().enteredMapId)!==String(fresh.war_id) ||
          marchIdentity(module_(),me,move)!==fresh.march_key)return bad('发送前行军状态已变化','waiting');
      var finalAttempt=remaining<=10000;
      if(finalAttempt && state.finalSpeedAttempted)return bad('本次行军已尝试最后一次赶路','waiting');
      if(finalAttempt)state.finalSpeedAttempted=true;
      state.lastSpeedAt=now;
      trace('speed.preflight',{warId:fresh.war_id,remaining:remaining,finalAttempt:finalAttempt,
        intervalSeconds:fresh.speed_up.interval_seconds,times:state.speedTimes,limit:limit});
      var receipt=await directRequest('moveSpeedUp',{warId:fresh.war_id});
      var failure=checkReceipt(receipt,'赶路');
      if(failure){
        // A definite rejection consumed no successful speed-up. Recheck after
        // the configured interval; the final-window attempt is never repeated.
        if(failure.status==='rejected')return {ok:false,status:'retry_later',message:failure.message};
        return failure;
      }
      state.speedTimes++;
      return done({confirmed:true,times:state.speedTimes,mode:'direct',final_attempt:finalAttempt});
    }catch(e){return bad((e && e.message)||e,state.dispatched?'uncertain':'unavailable');}
    finally{state.pending=false;}
  }

  // ── 只读：当前节点候选 ──

  async function candidates(args) {
    await libs();
    var m = module_();
    if (!m) return bad('血月模块尚未初始化');
    var me = myRole();
    if (!me) return bad('当前没有自己的战场角色');
    var x = num(me.position && me.position.x), y = num(me.position && me.position.y);
    var snap = null;
    // Automation only needs state/timing while marching or fighting. Keep the
    // full queue path for standby selection, diagnostics and final attack guards.
    try { snap = args && args.compact && num(me.state) !== 1
      ? {attackQueue:[], defenseQueue:[]} : m.getBuildingOpSnapshot(x, y);
    } catch (e) { traceException('queue.snapshot.exception', e, {x:x,y:y}); snap = null; }
    if (!snap) return bad('当前节点没有可用的队列快照');
    var data = mapData();
    var building = null;
    try { building = data && data.buildings ? data.buildings.get(x + '_' + y) : null; } catch (e) { traceException('building.read.exception', e, {x:x,y:y}); building = null; }
    var inMembers = false;
    try { inMembers = !!(building && building.members && building.members.has && building.members.has(me.id)); } catch (e) { traceException('membership.self.exception', e, {roleId:me.id}); inMembers = false; }
    var mySide = num(me.lId, 0);
    function rows(list) {
      var out = [];
      (list || []).forEach(function (item) {
        var role = item && item.role;
        if (!role) return;
        var reasons = [];
        if (num(role.id) === num(me.id)) reasons.push('自己');
        if (mySide > 0 && num(role.lId, 0) === mySide) reasons.push('同阵营');
        if (num(me.state) !== 1) reasons.push('自己不是待命状态');
        if (!inMembers) reasons.push('自己不在此节点驻留');
        var inBuilding = false;
        try { inBuilding = !!(building && building.members && building.members.has && building.members.has(role.id)); } catch (e) { traceException('membership.target.exception', e, {roleId:role.id}); inBuilding = false; }
        if (!inBuilding) reasons.push('目标不在此节点驻留');
        if (num(role.state) === 2 || num(item.arriveAt) > 0) reasons.push('目标正在行军');
        // 隐匿只作为展示信息：可见队列里的目标能不能打，仍按上面的公开资格判断。
        out.push({
          roleId: num(role.id), name: role.name || '', power: num(role.power),
          planPower: Array.isArray(role.planPower) ? num(role.planPower[0]) : 0,
          legionId: num(role.lId), flagId: num(role.flagId), flag: flagName(role.flagId),
          state: num(role.state), stateName: stateName(role.state), stealth: isStealth(role),
          arriveAt: num(item.arriveAt), attackable: reasons.length === 0, reasons: reasons
        });
      });
      return out;
    }
    var battleTimer = null;
    if (num(me.state) === 3 && typeof m.getTimerByRole === 'function') {
      try { battleTimer = m.getTimerByRole(me, null); } catch (e) { traceException('battle.timer.exception',e); }
    }
    var observation=state.attackObservation;
    if(observation && observation.accepted && !observation.completed &&
        String(m.enteredMapId)===observation.warId && num(me.id)===observation.selfId){
      if(num(me.state)===3)observation.seenBattle=true;
      if(observation.seenBattle && num(me.state)===1){observation.completed=true;detachBattleObserver();}
    }
    var clock = await serverNow(true);
    return done({
      server_now: clock, battle_end_time: battleTimer ? num(battleTimer.endTime) : 0,
      node: { x: x, y: y }, in_members: inMembers, self_state: num(me.state),
      self_state_name: stateName(me.state), self_power: num(me.power),
      self_plan_power: Array.isArray(me.planPower) ? num(me.planPower[0]) : 0,
      attack: rows(snap.attackQueue), defense: rows(snap.defenseQueue),
      battles: state.battles, attack_observation: state.attackObservation
    });
  }

  // ── 动作：正常挑战 ──

  async function attack(args) {
    args = args || {};
    var roleId = num(args.roleId, 0);
    if (state.pending) return bad('上一条命令尚未结束', 'uncertain');
    if (state.uncertain) return bad('前次操作结果未知，已停止自动操作', 'uncertain');
    if (!roleId) return bad('缺少目标 roleId', 'rejected');
    state.pending = true; state.dispatched = false;
    try {
      await libs();
      var m = module_();
      if (!m) return bad('血月模块尚未初始化');
      var me = myRole();
      if (!me) return bad('当前没有自己的战场角色');
      var warId = m.enteredMapId;
      var x = num(me.position && me.position.x), y = num(me.position && me.position.y);
      var snap = null;
      try { snap = m.getBuildingOpSnapshot(x, y); } catch (e) { traceException('queue.snapshot.exception', e, {x:x,y:y}); snap = null; }
      if (!snap) return bad('当前节点没有可用的队列快照', 'waiting');
      var data = mapData(), building = null;
      try { building = data && data.buildings ? data.buildings.get(x + '_' + y) : null; } catch (e) { traceException('building.read.exception', e, {x:x,y:y}); building = null; }
      var hasMe = false, hasTarget = false;
      try { hasMe = !!(building && building.members && building.members.has(me.id)); } catch (e) { traceException('membership.self.exception', e, {roleId:me.id}); }
      try { hasTarget = !!(building && building.members && building.members.has(roleId)); } catch (e) { traceException('membership.target.exception', e, {roleId:roleId}); }
      if (!hasMe) return bad('自己不在此节点驻留，不发起挑战', 'waiting');
      if (!hasTarget) return bad('目标不在此节点驻留，不发起挑战', 'waiting');
      if (num(me.state) !== 1) return bad('自己不是待命状态（' + stateName(me.state) + '）', 'waiting');
      var target = null, tab = 0;
      [['attackQueue', 0], ['defenseQueue', 1]].forEach(function (pair) {
        if (target) return;
        ((snap[pair[0]] || [])).forEach(function (item) {
          if (target || !item || !item.role) return;
          if (num(item.role.id) === roleId) { target = item.role; tab = pair[1]; }
        });
      });
      if (!target) return bad('目标不在当前可见队列里，不发起挑战', 'waiting');
      var side = num(me.lId, 0);
      if (side > 0 && num(target.lId, 0) === side) return bad('目标与己方同阵营，不发起挑战', 'waiting');
      trace('attack.preflight', { roleId: roleId, args: args, warId: m.enteredMapId, me: me, target: target, hasMe: hasMe, hasTarget: hasTarget, side: side, tab: tab });
      // Use the game module's eligibility method; no queue UI module or instance.
      if (typeof m.canAttack !== 'function' || typeof m.startPVPBattle !== 'function')
        return bad('原生挑战接口或资格函数不可用，未发送', 'unavailable');
      var fresh = await candidates();
      var current = (fresh.attack || []).concat(fresh.defense || []).find(function (r) { return r.roleId === roleId; });
      var mine = num(fresh.self_plan_power) || num(fresh.self_power);
      var power = current && (num(current.planPower) || num(current.power));
      var ceiling = num(args.power_limit) > 0 ? Math.min(mine, num(args.power_limit)) : mine;
      var role = mapData() && mapData().roles && mapData().roles.get(roleId);
      if (!fresh.ok || !fresh.node || fresh.node.x !== x || fresh.node.y !== y ||
          String(m.enteredMapId) !== String(warId) || !current || !current.attackable ||
          mine <= 0 || power <= 0 || power >= ceiling || !role || !m.canAttack(x, y, role))
        return bad('当前节点、目标资格或战力已变化，未发送', 'waiting');
      if (state.attackObservation && state.attackObservation.accepted && !state.attackObservation.completed)
        return bad('上一场挑战尚未确认结束', 'waiting');
      var params = {targetId:roleId, warId:warId};
      state.lastAttackAt = Date.now();
      detachBattleObserver();
      state.attackObservation = { token: String(state.lastAttackAt) + ':' + String(state.battles + 1),
        warId: String(warId), selfId: num(me.id), targetId: roleId,
        buildingId: x + '_' + y, completed: false };
      bindBattleObserver();
      state.dispatched = true; state.outstanding++;
      trace('attack.directRequest', {params:params});
      var pending;
      try { pending = Promise.resolve(m.startPVPBattle(params)); }
      catch (e) { state.outstanding--; throw e; }
      var settled = pending.then(function (value) { state.outstanding--; return value; },
        function (error) { state.outstanding--; throw error; });
      var response = await new Promise(function (resolve, reject) {
        var timer = setTimeout(function () { reject(new Error('挑战请求超时，结果未知')); },8000);
        settled.then(function(value){clearTimeout(timer);resolve(value);},
          function(error){clearTimeout(timer);reject(error);});
      });
      trace('attack.directReceipt', {response:response});
      var error = response && response.err;
      var code = error && (num(error.code) || num(error._raw && error._raw.code));
      if (code === 350018) return {ok:false,status:'target_unavailable',roleId:roleId,
        retry_after_ms:1000,message:'目标正在行军，暂缓此目标并继续扫描当前节点'};
      var failure = checkReceipt({called:true,settled:true,count:1,error:'',value:response}, '挑战');
      if (failure) {
        if (failure.status === 'rejected') return {ok:false,status:'retry_later',roleId:roleId,
          retry_after_ms:1000,message:failure.message};
        return failure;
      }
      state.attackObservation.accepted = true;
      state.battles += 1;
      return done({ confirmed: true, roleId: roleId, name: target.name || '', tab: tab, battles: state.battles, mode:'direct',
        attack_token: state.attackObservation.token });
    } catch (e) {
      trace('action.exception', {message: String(e), stack: e && e.stack, outstanding: state.outstanding});
      return bad((e && e.message) || e, (e && e.status) || (state.dispatched ? 'uncertain' : 'unavailable'));
    } finally {
      state.pending = false;
    }
  }

  // ── 隐匿显示：原生队列头像、行军路线及状态标注 ──

  var revealHelper = null, originalHideMarch = null, revealHideMarch = null, revealedScene = null;
  function currentMarchScene() {
    // The native getter dereferences Canvas/season_map and throws in the hall.
    try {
      var m = module_(), scene = m && typeof m.getSeasonMap === 'function' ? m.getSeasonMap() : null;
      return scene && (!scene.node || scene.node.isValid !== false) ? scene : null;
    } catch (e) { return null; }
  }
  function refreshMarchDisplay(force) {
    var scene = currentMarchScene();
    if (scene && scene.sourceMap && (force || scene !== revealedScene)) {
      // Native lateUpdate rebuilds the fly-fish and dashed route layers together.
      scene._dirtyMarch = true;
      revealedScene = scene;
      force = true;
    }
    if (!scene) revealedScene = null;
    if (!force) return;
    var map = openUI('SeasonMapUI'), op = map && map.view && map.view.op;
    var queue = openUI('SeasonQueueDetailUI');
    [op, queue].forEach(function(view){
      if (view && typeof view._markDirty === 'function') view._markDirty();
    });
  }
  function enableMarchReveal(helper) {
    if (revealHelper) return;
    if (!helper || typeof helper.shouldHideStealthMarch !== 'function')
      throw new Error('隐匿行军显示接口未就绪');
    originalHideMarch = helper.shouldHideStealthMarch;
    var original = originalHideMarch;
    revealHideMarch = function(role) {
      // Only the display filter changes. isStealth, moveInfos and role state stay intact.
      return revealHelper === helper && role && isStealth(role) ? false : original.apply(this, arguments);
    };
    revealHelper = helper;
    helper.shouldHideStealthMarch = revealHideMarch;
    refreshMarchDisplay(true);
  }
  function disableMarchReveal() {
    if (revealHelper && revealHelper.shouldHideStealthMarch === revealHideMarch)
      revealHelper.shouldHideStealthMarch = originalHideMarch;
    var wasEnabled = !!revealHelper;
    revealHelper = originalHideMarch = revealHideMarch = null;
    revealedScene = null;
    if (wasEnabled) refreshMarchDisplay(true);
  }

  function clearMarks() {
    state.marks.forEach(function (node) { try { if (node && node.isValid) node.destroy(); } catch (e) { traceException('marks.destroy.exception', e); } });
    state.marks = [];
  }

  function attachMark(node, text) {
    if (!node || !node.isValid) return false;
    for (var i = 0; i < state.marks.length; i++) {
      if (state.marks[i] && state.marks[i].parent === node) return false;
    }
    var cc = lib.cc;
    var child = new cc.Node('e0e1_stealth_mark');
    var label = child.addComponent(cc.Label);
    label.string = text;
    label.fontSize = 20;
    label.lineHeight = 22;
    label.color = new cc.Color(120, 220, 255, 255);
    child.setPosition(0, 26, 0);
    node.addChild(child);
    state.marks.push(child);
    return true;
  }

  function syncMarks(needed) {
    // 先摘掉不再需要的（列表复用行会让目标换人），再补上新的。
    state.marks = state.marks.filter(function (node) {
      var keep = node && node.isValid && needed.indexOf(node.parent) >= 0;
      if (!keep) { try { if (node && node.isValid) node.destroy(); } catch (e) { traceException('marks.destroy.exception', e); } }
      return keep;
    });
    var marked = 0;
    needed.forEach(function (node) { if (attachMark(node, '隐匿中')) marked++; });
    return marked;
  }

  function markVisibleLists() {
    refreshMarchDisplay(false);
    var pairs = [];
    var queue = openUI('SeasonQueueDetailUI');
    if (queue && queue.view) {
      pairs.push([queue.view.list_attack, queue.attackEntries, lib.cellType]);
      pairs.push([queue.view.list_defense, queue.defenseEntries, lib.cellType]);
    }
    var map = openUI('SeasonMapUI');
    var op = map && map.view ? map.view.op : null;
    if (op) {
      pairs.push([op.list_attack, op._attackEntries, lib.opCellType]);
      pairs.push([op.list_defense, op._defenseEntries, lib.opCellType]);
    }
    var needed = [];
    pairs.forEach(function (pair) {
      var list = pair[0], entries = pair[1] || [];
      if (!list || typeof list.getItemByListId !== 'function') return;
      for (var i = 0; i < entries.length; i++) {
        var entry = entries[i];
        if (!entry || !entry.role || !isStealth(entry.role)) continue;
        var node = list.getItemByListId(i);
        if (!node || node.activeInHierarchy === false || node.isValid === false) continue;
        var cell = pair[2] && node.getComponent ? node.getComponent(pair[2]) : null;
        if (!cell) continue;
        if (pair[2] === lib.opCellType) {
          // 地图侧栏没有姓名标签，以原生已渲染的隐匿标识核实，避免列表回收时误标。
          var head = cell.head && cell.head.node;
          var nativeMark = head && head.getChildByName && head.getChildByName('nd_sneath');
          if (!nativeMark || !nativeMark.active) continue;
        } else if (!cell.lab_name || cell.lab_name.string !== String(entry.role.name || '')) continue;
        if (needed.indexOf(node) < 0) needed.push(node);
      }
    });
    return syncMarks(needed);
  }

  var marksEpoch = 0;
  async function marks(args) {
    var epoch = ++marksEpoch;
    args = args || {};
    await libs();
    if (epoch !== marksEpoch) return done({ marked: 0 });
    var on = args.on !== false;
    if (state.markTimer) { clearInterval(state.markTimer); state.markTimer = null; }
    clearMarks();
    if (!on) { disableMarchReveal(); return done({ marked: 0, routes_enabled: false }); }
    var helper = (await chunk('season-helper.ts')).seasonHelper;
    if (epoch !== marksEpoch) return done({ marked: 0, routes_enabled: !!revealHelper });
    enableMarchReveal(helper);
    state.markError = null;
    state.markTimer = setInterval(function () {
      try { var perf=g.e0e1Perf;if(perf)perf.measure('season.marks.sync',markVisibleLists,null,[]);else markVisibleLists(); }
      catch (e) {
        state.markError = { at: Date.now(), message: String(e), stack: e && e.stack };
        trace('marks.tick.exception', state.markError);
      }
    }, 1000);
    return done({ marked: markVisibleLists(), routes_enabled: true });
  }

  async function diagnose() {
    try { await libs(); } catch (e) { return bad('游戏尚未就绪：' + ((e && e.message) || e)); }
    var m = module_(), data = mapData(), me = myRole();
    var marchScene = currentMarchScene();
    var conf = constants() || {};
    var preview = m && m.season_preview;
    var bTimes = preview && preview.legionSeason && preview.legionSeason.bTimeInfos ? preview.legionSeason.bTimeInfos.size : 0;
    return done({
      module: !!m, map_ui: !!openUI('SeasonMapUI'), queue_ui: !!openUI('SeasonQueueDetailUI'),
      war_id: (m && m.enteredMapId) || '',
      roles: data && data.roles ? data.roles.size : 0,
      legions: data && data.legions ? data.legions.size : 0,
      buildings: data && data.buildings ? data.buildings.size : 0,
      move_infos: data && data.moveInfos ? data.moveInfos.size : 0,
      preview_btime_count: bTimes,
      self: me ? { roleId: num(me.id), name: me.name || '', state: num(me.state), stateName: stateName(me.state),
                   flagId: num(me.flagId), flag: flagName(me.flagId), stealth: isStealth(me),
                   position: me.position ? { x: num(me.position.x), y: num(me.position.y) } : null } : null,
      constants: { MarchSpeed: num(conf.MarchSpeed, 0), MarchSpeedUpCD: num(conf.MarchSpeedUpCD, 0),
                   MarchSpeedUpMinTime: num(conf.MarchSpeedUpMinTime, 0),
                   MarchSpeedUpItem: conf.MarchSpeedUpItem || null, PreEnterMinutes: num(conf.PreEnterMinutes, 0) },
      pending: state.pending, uncertain: state.uncertain, outstanding: state.outstanding,
      marks_enabled: !!state.markTimer, mark_count: state.marks.length,
      routes_enabled: !!revealHelper && revealHelper.shouldHideStealthMarch === revealHideMarch,
      rendered_marches: marchScene && marchScene._flyFishManager && marchScene._flyFishManager._flyFishMap
        ? marchScene._flyFishManager._flyFishMap.size : 0,
      mark_error: state.markError, script_version: VERSION
    });
  }

  function stop() {
    ++marksEpoch;
    if (state.markTimer) { clearInterval(state.markTimer); state.markTimer = null; }
    clearMarks();
    disableMarchReveal();
    return done({ stopped: true });
  }

  function reset() {
    if (state.pending || state.outstanding) return bad('仍有操作或请求在途，不能复位', 'uncertain');
    state.uncertain = false; state.speedTimes = 0; state.marchKey = ''; state.battles = 0; state.finalSpeedAttempted = false;
    detachBattleObserver(); state.attackObservation = null;
    return done({ reset: true });
  }

  g.e0e1Season = { ready: true, version: VERSION, detachBattleObserver: detachBattleObserver, pendingState: function(){return {pending:state.pending,uncertain:state.uncertain,outstanding:state.outstanding};} };
  var methods = { flags: flags, march: march, speedUp: speedUp, candidates: candidates,
    attack: attack, marks: marks, diagnose: diagnose, stop: stop, reset: reset };
  Object.keys(methods).forEach(function (name) { g.e0e1Season[name] = exportCall(name, methods[name]); });
  log('血月战场脚本已就绪：战旗探测/加速/挑战/隐匿状态标注');
})();
