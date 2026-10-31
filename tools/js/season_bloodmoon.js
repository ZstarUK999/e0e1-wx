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
//   · 攻击按实时资格持续发送，回包独立记录；超时或异常不阻塞后续攻击。
//   · 仅显示客户端已同步数据，不改角色状态；提前窗口允许请求，由服务端判定开战资格。

await (async function () {
  var g = globalThis, VERSION = '2026-10-31-js-runtime-v24', restored = null;
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
    if(/^automationEvents\.(begin|end)$/.test(step))return;
    // Realtime detail is batched back to the file logger, never spammed through console events.
    if(automation && (automation.config || /^attack\.packet/.test(step))){
      automationEvent('debug_trace',{step:step,values:snapshot},/exception/.test(step)?'ERROR':'DEBUG');
      return;
    }
    if (!/^(candidates|march|flags|diagnose|automationEvents)\.(begin|end)$/.test(step)) {
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
        systemPresent: !!g.System, uiPresent: !!g.UIManager, rolePresent: !!g.ROLE,
        modulePresent: !!g.seasonModule, warId: g.seasonModule && g.seasonModule.enteredMapId });
      var result;
      try { result = await fn(args); }
      catch (e) {
        trace(name + '.exception', { message: String(e), stack: e && e.stack });
        result = bad(String(e), name === 'attack' ? 'unavailable' : (mutating ? 'uncertain' : 'unavailable'));
      }
      // Read results already cross the bridge once. Do not deep-copy the whole
      // queue/flag roster into its own trace on every high-frequency poll.
      trace(name + '.end', { id: id, result: mutating ? result : {
        ok: result.ok, status: result.status, message: result.message,
        attackCount: result.attack && result.attack.length,
        defenseCount: result.defense && result.defense.length,
        groupCount: result.groups && result.groups.length
      } });
      if (name === 'attack') result.request_sent = result.request_sent === true;
      else if (mutating) result.request_sent = !!state.dispatched;
      result.trace = ownTrace.slice();
      if (actionTrace === ownTrace) actionTrace = null;
      return result;
    };
  }
  var state = {
    lastSpeedAt: restored ? num(restored.lastSpeedAt) : 0,
    finalSpeedAttempted: restored ? !!restored.finalSpeedAttempted : false,
    lastAttackAt: restored ? num(restored.lastAttackAt) : 0,
    attackSeq: 0,
    attackWave: 0,
    attackScope: '',
    lastBattleIdentity: '',
    countedBattleKeys: {},
    attackRequests: [],
    attackLatencySamples: [],
    latestTargetRequest: {},
    lastAttackRejection: null,
    dispatched: false,
    markError: null,
    outstanding: 0,
    pending: false,        // 仅用于赶路动作；攻击在途请求不占用此锁。
    uncertain: false,      // 赶路结果未知标记；不阻止实时校验后的新攻击。
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

  // Packet responses never control the scanner. Real role/map state does.
  function detachBattleObserver() {}
  function bindBattleObserver() {}

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
      if(args._automation_epoch!==undefined && args._automation_epoch!==automation.epoch)return {ok:false,status:'waiting',request_sent:false,message:'已停止旧的自动加速循环'};
      if(!fresh.ok)return fresh;
      if(!fresh.speed_up.available)return Object.assign(bad(fresh.speed_up.reasons.join('；'),'waiting'),
        {wait_ms:Math.max(0,num(fresh.speed_up.cool_down_until)-num(fresh.server_now))});
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
      if(args._automation_epoch!==undefined)automationEvent('speed_sent',{message:'发起赶路',request_seq:++automation.speedSeq,
        march_key:state.marchKey,war_id:fresh.war_id,remaining_ms:remaining,interval_seconds:fresh.speed_up.interval_seconds});
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

  function battleTimerFor(m, me) {
    try { return num(me.state) === 3 && typeof m.getTimerByRole === 'function' ? m.getTimerByRole(me, null) : null; }
    catch (e) { traceException('battle.timer.exception', e); return null; }
  }
  function battleKey(m, me) {
    var timer = battleTimerFor(m, me);
    try {
      var battle=typeof m.seasonMapFindBattleByRoleId==='function' && m.seasonMapFindBattleByRoleId(me.id);
      if(battle && num(battle.startTime)>0)return num(battle.startTime)+':'+num(battle.tId);
    } catch(error){traceException('battle.identity.exception',error);}
    return timer && num(timer.startTime)>0 ? String(num(timer.startTime)) :
      (timer && num(timer.endTime)>0 ? 'end:'+num(timer.endTime) : '');
  }
  function latencyNow() {
    return g.performance && typeof g.performance.now==='function' ? g.performance.now() : Date.now();
  }
  function attackLatencyStats() {
    var now=latencyNow();
    state.attackLatencySamples=state.attackLatencySamples.filter(function(sample){return now-sample.at<10000;});
    var count=state.attackLatencySamples.length;
    var sum=state.attackLatencySamples.reduce(function(total,sample){return total+sample.rtt;},0);
    return {window_ms:10000,sample_count:count,mean_rtt_ms:count?sum/count:null,
      mean_one_way_ms:count?sum/count/2:null};
  }
  function effectiveAttackLead(args) {
    var configured=Math.max(0,Math.min(10000,num(args && args.lead_ms)));
    if(configured===0 || !args || args.dynamic_lead!==true)return configured;
    var stats=attackLatencyStats();
    return stats.sample_count ? Math.min(10000,Math.ceil(stats.mean_one_way_ms)) : configured;
  }
  function attackContext(m, me, args, now) {
    var lead = effectiveAttackLead(args), data = mapData();
    var phase = num(me.state), timer = battleTimerFor(m, me);
    var move = phase === 2 && data && data.moveInfos && data.moveInfos.get(me.id);
    var end = phase === 2 ? num(move && move.arrive) : num(timer && timer.endTime);
    var early = lead > 0 && now > 0 && end > 0 && end - now <= lead && (phase === 2 || phase === 3);
    var position = early && phase === 2 && move && move.to ? move.to : me.position;
    return {x:num(position && position.x), y:num(position && position.y), early:early, lead_ms:lead,
      kind:early ? (phase === 2 ? 'arrival' : 'battle') : '', end:end,
      battle_key:battleKey(m,me)};
  }

  async function candidates(args) {
    await libs();await serverNow(true);
    return candidateSnapshot(args || {});
  }
  function candidateSnapshot(args) {
    var m = module_();
    if (!m) return bad('血月模块尚未初始化');
    var me = myRole();
    if (!me) return bad('当前没有自己的战场角色');
    var clock = num(lib.clock && lib.clock.serverTime), context = attackContext(m, me, args, clock);
    var x = context.x, y = context.y;
    var snap = null;
    // Outside the lead window busy scans only need timing. Inside it build a
    // fresh queue at the destination/current node for every attempt.
    try { snap = args.compact && num(me.state) !== 1 && !context.early
      ? {attackQueue:[], defenseQueue:[]} : m.getBuildingOpSnapshot(x, y);
    } catch (e) { traceException('queue.snapshot.exception', e, {x:x,y:y}); snap = null; }
    if (!snap) return bad('当前节点没有可用的队列快照');
    var data = mapData();
    var building = null;
    try { building = data && data.buildings ? data.buildings.get(x + '_' + y) : null; } catch (e) { traceException('building.read.exception', e, {x:x,y:y}); building = null; }
    var inMembers = false;
    try { inMembers = !!(building && building.members && building.members.has && building.members.has(me.id)); } catch (e) { traceException('membership.self.exception', e, {roleId:me.id}); inMembers = false; }
    var mySide = typeof m.getSeasonMapMySideId==='function' ? num(m.getSeasonMapMySideId()) : num(me.lId);
    if (mySide<=0) mySide=num(me.lId);
    function rows(list) {
      var out = [];
      (list || []).forEach(function (item) {
        var role = item && item.role;
        if (!role) return;
        var targetMove = data && data.moveInfos && data.moveInfos.get(role.id);
        var targetLead = context.lead_ms;
        var approaching=clock>0 && num(role.state)===2 && targetMove && targetMove.to &&
          num(targetMove.to.x)===x && num(targetMove.to.y)===y && num(targetMove.arrive)>0;
        var incoming=targetLead>0 && approaching && num(targetMove.arrive)-clock<=targetLead;
        var arrivalWindow=targetLead>0 && approaching && num(role.id)!==num(me.id) &&
          !(mySide>0 && num(role.lId)===mySide)?Math.max(0,num(targetMove.arrive)-clock-targetLead):0;
        var reasons = [];
        if (num(role.id)<=0) reasons.push('无效玩家ID');
        if (num(role.id) === num(me.id)) reasons.push('自己');
        if (mySide > 0 && num(role.lId, 0) === mySide) reasons.push('同阵营');
        if (num(me.state) !== 1 && !context.early) reasons.push('自己不是待命状态');
        if (!inMembers && context.kind !== 'arrival') reasons.push('自己不在此节点驻留');
        var inBuilding = false;
        try { inBuilding = !!(building && building.members && building.members.has && building.members.has(role.id)); } catch (e) { traceException('membership.target.exception', e, {roleId:role.id}); inBuilding = false; }
        if (!inBuilding && !incoming) reasons.push('目标不在此节点驻留');
        if (!incoming && (num(role.state) === 2 || num(item.arriveAt) > clock)) reasons.push('目标正在行军');
        // 隐匿只作为展示信息：可见队列里的目标能不能打，仍按上面的公开资格判断。
        out.push({
          roleId: num(role.id), name: role.name || '', power: num(role.power),
          planPower: Array.isArray(role.planPower) ? num(role.planPower[0]) : 0,
          legionId: num(role.lId), flagId: num(role.flagId), flag: flagName(role.flagId),
          state: num(role.state), stateName: stateName(role.state), stealth: isStealth(role),
          arriveAt: num(item.arriveAt), attackable: reasons.length === 0, reasons: reasons,
          arrival_window_ms:arrivalWindow,incoming:!!incoming, retry_deferred:!!state.lastAttackRejection && state.lastAttackRejection.roleId===num(role.id)
        });
      });
      return out;
    }
    var battleTimer = battleTimerFor(m, me);
    var enteredBattle = observeAttackPhase(m, me, context);
    return done({
      server_now: clock, battle_end_time: battleTimer ? num(battleTimer.endTime) : 0,
      march_end_time:num(me.state)===2 ? context.end : 0, battle_key:context.battle_key,
      early_attack:context.early, early_kind:context.kind,
      effective_lead_ms:context.lead_ms, attack_latency:attackLatencyStats(),
      node: { x: x, y: y }, in_members: inMembers, self_state: num(me.state),
      self_state_name: stateName(me.state), self_power: num(me.power),
      self_plan_power: Array.isArray(me.planPower) ? num(me.planPower[0]) : 0,
      attack: rows(snap.attackQueue), defense: rows(snap.defenseQueue),
      battles: state.battles, entered_battle: enteredBattle, attack_wave: state.attackWave,
      latest_request_seq: state.attackSeq, attack_last_rejection: state.lastAttackRejection,
      attack_requests: state.attackRequests.slice(-16).map(function(row){return Object.assign({},row);})
    });
  }

  // ── 动作：正常挑战 ──

  function observeAttackPhase(m, me, context) {
    var identity = String(m.enteredMapId)+':'+num(me.id)+':'+context.x+'_'+context.y;
    var phase = num(me.state), scope = identity+':'+phase;
    if (phase===3) scope+=':'+context.battle_key;
    if (scope!==state.attackScope) {
      state.attackScope=scope;state.attackWave++;
      state.lastAttackRejection=null;
    }
    var key=phase===3 ? identity+':'+(context.battle_key || 'phase-'+state.attackWave) : '';
    var entered=!!key && key!==state.lastBattleIdentity;
    if (entered && !state.countedBattleKeys[key] && state.attackRequests.some(function(row){
      return row.warId===String(m.enteredMapId) && row.selfId===num(me.id);
    })) { state.countedBattleKeys[key]=true;state.battles++; }
    state.lastBattleIdentity=key;
    return entered;
  }

  function dispatchAttack(m, me, fresh, roleId) {
    var sentTick=latencyNow();
    var sequence=++state.attackSeq, wave=state.attackWave;
    state.lastAttackRejection=null;
    var record={request_id:String(m.enteredMapId)+':'+num(me.id)+':'+sequence,
      seq:sequence,wave:wave,warId:String(m.enteredMapId),selfId:num(me.id),roleId:roleId,
      node:fresh.node.x+'_'+fresh.node.y,sent_at:Date.now(),status:'sent',finished:false};
    state.attackRequests.push(record);
    if(state.attackRequests.length>128)state.attackRequests.shift();
    state.latestTargetRequest[roleId]=sequence;
    state.lastAttackAt=record.sent_at;
    state.outstanding++;
    var timer=setTimeout(function(){
      if(!record.finished){record.status='timeout';trace('attack.packetTimeout',record);
        if(automation && automation.config)automationEvent('challenge_timeout',{request_seq:record.seq,roleId:record.roleId,stopped:false},'WARNING');}
    },8000);
    function settle(value, error) {
      if(record.finished)return;
      record.finished=true;clearTimeout(timer);state.outstanding--;
      var late=record.status==='timeout';record.settled_at=Date.now();
      if(!error && value && Object.prototype.hasOwnProperty.call(value,'err') &&
          (value.err===null || value.err)){
        var receivedTick=latencyNow();
        record.rtt_ms=Math.max(0,receivedTick-sentTick);
        state.attackLatencySamples.push({at:receivedTick,rtt:record.rtt_ms});
        attackLatencyStats();
      }
      if(error){record.status='network_error';record.message=String(error);}
      else if(!value || !Object.prototype.hasOwnProperty.call(value,'err') || value.err===undefined){
        record.status='malformed';
      } else if(value.err){
        record.status=late?'late_rejected':'rejected';record.message=String(value.err.error || value.err.code || value.err);
        // A reply from an earlier wave/request cannot rewrite newer selection.
        if(wave===state.attackWave && sequence===state.attackSeq && state.latestTargetRequest[roleId]===sequence){
          if(sequence===state.attackSeq)state.lastAttackRejection={seq:sequence,wave:wave,roleId:roleId};
        }
      } else if(value.err===null)record.status=late?'late_accepted':'accepted';
      else record.status='malformed';
      trace('attack.packetReceipt',record);
      if(automation && automation.config && (record.status==='network_error' || record.status==='malformed'))
        automationEvent('challenge_error',{request_seq:record.seq,roleId:record.roleId,status:record.status,message:record.message,stopped:false},'ERROR');
    }
    try {
      Promise.resolve(m.startPVPBattle({targetId:roleId,warId:m.enteredMapId})).then(
        function(value){settle(value,null);},function(error){settle(null,error);});
    } catch(error){settle(null,error);}
    // This acknowledges dispatch only. It never awaits the game's response.
    return done({dispatched:true,request_sent:true,request_id:record.request_id,
      request_seq:sequence,attack_wave:wave,roleId:roleId,battles:state.battles});
  }

  async function attack(args) {
    args = args || {};
    var roleId = num(args.roleId, 0);
    if (roleId<=0) return bad('缺少有效目标 roleId', 'waiting');
    try {
      // The bridge may have taken time since Python selected the role. Read
      // one current local snapshot here; validation and dispatch below are synchronous.
      var fresh = await candidates({lead_ms:num(args.lead_ms),dynamic_lead:args.dynamic_lead===true});
      if (!fresh.ok) return fresh;
      if (fresh.entered_battle) return bad('已进入新战斗，结束本轮发送','battle_started');
      var m = module_(), me = myRole();
      if (!m || !me) return bad('当前没有可用的战场角色','waiting');
      if (typeof m.canAttack !== 'function' || typeof m.startPVPBattle !== 'function')
        return bad('原生挑战接口或资格函数不可用，未发送','unavailable');
      var x = fresh.node.x, y = fresh.node.y;
      var current = (fresh.attack || []).concat(fresh.defense || []).find(function (r) { return r.roleId === roleId; });
      var mine = num(fresh.self_plan_power) || num(fresh.self_power);
      var power = current && (num(current.planPower) || num(current.power));
      var ceiling = num(args.power_limit) > 0 ? Math.min(mine, num(args.power_limit)) : mine;
      var data = mapData(), role = data && data.roles && data.roles.get(roleId);
      if (!current || !current.attackable ||
          mine <= 0 || power <= 0 || power >= ceiling || !role || roleId===num(me.id) ||
          (fresh.early_kind !== 'arrival' && !current.incoming && !m.canAttack(x, y, role)))
        return bad('当前节点、目标资格或战力已变化，未发送', 'waiting');
      if (current.incoming && (fresh.attack || []).concat(fresh.defense || []).some(function(row){
        var p=num(row.planPower)||num(row.power);
        return !row.incoming && row.attackable && p>0 && p<ceiling;
      })) return bad('已有当前可攻击玩家，重新选敌，不锁定即将到达者', 'waiting');
      if (current.retry_deferred && (fresh.attack || []).concat(fresh.defense || []).some(function(row){
        var p=num(row.planPower)||num(row.power);
        return !row.retry_deferred && (!row.incoming || current.incoming) && row.attackable && p>0 && p<ceiling;
      })) return bad('优先尝试其他合格玩家，重新选敌', 'waiting');
      return dispatchAttack(m,me,fresh,roleId);
    } catch(error) {
      traceException('attack.preflightException',error,{roleId:roleId});
      return {ok:false,status:'unavailable',request_sent:false,message:String(error)};
    }
  }

  // Timers, selection and dispatch live entirely in the game context.
  var automation = {stream:VERSION+':'+Date.now()+':'+Math.random().toString(36).slice(2),epoch:0, revision:-1, controller:null, controllers:{}, config:null, attackTimer:null, speedTimer:null,
    lastAttack:-Infinity, wave:null, target:null, attackStatus:'未启用', speedStatus:'未启用',
    speedBusy:false, speedSeq:0, speedStopped:'', eventSeq:0, events:[], keys:{}, lastDebug:-Infinity};

  function automationEvent(kind, detail, level) {
    var key=JSON.stringify(detail || {});
    if(automation.keys[kind]===key)return;
    automation.keys[kind]=key;
    automation.events.push({seq:++automation.eventSeq,at:Date.now(),kind:kind,level:level || 'INFO',detail:detail || {}});
    if(automation.events.length>4096)automation.events.shift();
  }
  function automationStatus(channel, status) {
    automation[channel+'Status']=status;
    automationEvent(channel+'_state',{status:status},/等待|剩余|道具不足/.test(status)?'DEBUG':'INFO');
  }
  function stopAutomation(reason) {
    if(automation.config)automationEvent('automation_stopped',{reason:reason || '配置变更',attack:automation.config.attack.enabled,speed:automation.config.speed_up.enabled});
    automation.epoch++;
    if(automation.attackTimer!==null)clearTimeout(automation.attackTimer);
    if(automation.speedTimer!==null)clearTimeout(automation.speedTimer);
    automation.attackTimer=automation.speedTimer=null;
    automation.config=null;
    automation.target=null;
    automationStatus('attack','未启用');automationStatus('speed','未启用');
  }
  function automationEvents(args) {
    var after=args && args.stream_id && args.stream_id!==automation.stream?0:num(args && args.after_seq), config=automation.config;
    var batch=automation.events.filter(function(e){return e.seq>after;}).slice(0,512);
    return done({stream_id:automation.stream,revision:automation.revision, running:!!(config && (config.attack.enabled || config.speed_up.enabled)),
      events:batch, cursor:batch.length?batch[batch.length-1].seq:automation.eventSeq,
      dropped:automation.events.length?Math.max(0,automation.events[0].seq-after-1):0,
      attack_status:automation.attackStatus,speed_status:automation.speedStatus,
      battles:state.battles, speed_times:state.speedTimes,
      attack_latency:attackLatencyStats(),effective_lead_ms:config?effectiveAttackLead(config.attack):0});
  }
  function pickAttackTarget(snapshot, args) {
    var mine=num(snapshot.self_plan_power)||num(snapshot.self_power), limit=num(args.power_limit);
    var ceiling=limit>0?Math.min(mine,limit):mine;
    if(mine<=0)return null;
    var m=module_(), data=mapData(), best=null, bestRank=null;
    if(!m || typeof m.canAttack!=='function' || typeof m.startPVPBattle!=='function')return null;
    (snapshot.attack || []).concat(snapshot.defense || []).forEach(function(row){
      var power=num(row.planPower)||num(row.power),role=data && data.roles && data.roles.get(row.roleId);
      if(!row.attackable || power<=0 || power>=ceiling || !role)return;
      try {if(snapshot.early_kind!=='arrival' && !row.incoming && !m.canAttack(snapshot.node.x,snapshot.node.y,role))return;}
      catch(error){automationEvent('eligibility_error',{roleId:row.roleId,message:String(error)},'ERROR');return;}
      var rank=[row.incoming?1:0,row.retry_deferred?1:0,args.lowest_power_first?power:-power];
      if(!bestRank || rank[0]<bestRank[0] || (rank[0]===bestRank[0] &&
          (rank[1]<bestRank[1] || (rank[1]===bestRank[1] && rank[2]<bestRank[2])))){
        best=row;bestRank=rank;
      }
    });
    return best;
  }
  function attackTick(epoch) {
    if(epoch!==automation.epoch || !automation.config || !automation.config.attack.enabled)return;
    automation.attackTimer=null;
    var args=automation.config.attack, delay=Math.min(100,args.interval_ms);
    try {
      // One synchronous local snapshot, selection and dispatch: no bridge or await.
      var snapshot=candidateSnapshot(Object.assign({compact:true},args));
      if(!snapshot.ok){automationStatus('attack','等待战场数据');return;}
      if(latencyNow()-automation.lastDebug>=1000){
        automation.lastDebug=latencyNow();
        var rows=(snapshot.attack || []).concat(snapshot.defense || []);
        automationEvent('attack_scan',{node:snapshot.node,self_state:snapshot.self_state,lead_ms:snapshot.effective_lead_ms,
          self_power:num(snapshot.self_plan_power)||num(snapshot.self_power),count:rows.length,
          sample:rows.slice(0,32).map(function(r){return {roleId:r.roleId,power:r.planPower||r.power,
            incoming:r.incoming,attackable:r.attackable,reasons:r.reasons};})},'DEBUG');
      }
      if(automation.wave!==snapshot.attack_wave){
        automation.wave=snapshot.attack_wave;automation.lastAttack=-Infinity;automation.target=null;
      }
      if(snapshot.entered_battle){
        automationEvent('battle_entered',{battles:state.battles,battle_key:snapshot.battle_key});
        automationStatus('attack','已进入战斗');return;
      }
      if(snapshot.self_state!==1 && !snapshot.early_attack){
        var end=num(snapshot.battle_end_time)||num(snapshot.march_end_time);
        var remaining=end-num(snapshot.server_now)-snapshot.effective_lead_ms;
        if(remaining>0)delay=Math.min(delay,remaining);
        automationStatus('attack','等待'+(snapshot.self_state_name || '状态变化')+'的提前窗口');return;
      }
      if(args.max_battles>0 && state.battles>=args.max_battles){
        automationStatus('attack','已达单轮上限 '+args.max_battles+' 场');return;
      }
      var now=latencyNow(), due=automation.lastAttack+args.interval_ms-now;
      if(due>0){delay=Math.min(delay,due);return;}
      var target=pickAttackTarget(snapshot,args);
      if(!target){
        var mine=num(snapshot.self_plan_power)||num(snapshot.self_power);
        var cap=args.power_limit>0?Math.min(mine,args.power_limit):mine;
        (snapshot.attack || []).concat(snapshot.defense || []).forEach(function(r){
          var power=num(r.planPower)||num(r.power);
          if(r.arrival_window_ms>0 && power>0 && power<cap)delay=Math.min(delay,r.arrival_window_ms);
        });
      }
      if(!target){automation.target=null;automationStatus('attack','当前没有合法目标，持续扫描');return;}
      if(automation.target!==target.roleId){
        automation.target=target.roleId;
        automationEvent('target_changed',{roleId:target.roleId,name:target.name,incoming:target.incoming});
      }
      var receipt=dispatchAttack(module_(),myRole(),snapshot,target.roleId);
      automation.lastAttack=now;
      automationEvent('challenge_sent',{message:'发起挑战',request_seq:receipt.request_seq,roleId:target.roleId,
        name:target.name,power:target.planPower||target.power,node:snapshot.node,incoming:target.incoming,
        early_kind:snapshot.early_kind,lead_ms:snapshot.effective_lead_ms,interval_ms:args.interval_ms});
      automationStatus('attack','持续挑战 '+target.roleId+'；间隔 '+args.interval_ms+'ms');
      delay=Math.min(100,args.interval_ms);
    } catch(error){automationStatus('attack','扫描异常，继续重试');automationEvent('attack_error',{message:String(error),stack:error && error.stack,stopped:false},'ERROR');}
    finally {
      if(epoch===automation.epoch && automation.config && automation.config.attack.enabled)
        automation.attackTimer=setTimeout(function(){attackTick(epoch);},Math.max(1,Math.ceil(delay)));
    }
  }
  async function speedTick(epoch) {
    if(epoch!==automation.epoch || !automation.config || !automation.config.speed_up.enabled)return;
    automation.speedTimer=null;
    if(automation.speedBusy){automation.speedTimer=setTimeout(function(){speedTick(epoch);},100);return;}
    automation.speedBusy=true;
    var delay=100;
    try {
      if(automation.speedStopped){automationStatus('speed','已停止：'+automation.speedStopped);return;}
      var args=automation.config.speed_up;
      // The native action reads local march state once; no Python call or extra preflight.
      var result=await speedUp(Object.assign({_automation_epoch:epoch},args));
      if(epoch!==automation.epoch)return;
      if(result.wait_ms>0)delay=Math.min(100,result.wait_ms);
      if(result.confirmed){automationEvent('speed_succeeded',{times:state.speedTimes,march_key:state.marchKey});automationStatus('speed','已加速 '+state.speedTimes+' 次');}
      else if(!result.ok && result.status!=='waiting' && result.status!=='retry_later' &&
          !(result.status==='unavailable' && !state.dispatched)){
        automation.speedStopped=result.message || result.status;
        automationEvent('speed_stopped',{reason:automation.speedStopped,march_key:state.marchKey,times:state.speedTimes,stopped:true},'ERROR');
      } else automationStatus('speed',result.message || '等待赶路条件');
    } catch(error){automationEvent('speed_error',{message:String(error),stack:error && error.stack,stopped:false},'ERROR');}
    finally {
      automation.speedBusy=false;
      if(epoch===automation.epoch && automation.config && automation.config.speed_up.enabled)
        automation.speedTimer=setTimeout(function(){speedTick(epoch);},Math.max(1,Math.ceil(delay)));
    }
  }
  async function automationConfigure(args) {
    args=args || {};
    var controller=String(args.controller || 'local');
    if(controller!==automation.controller){
      if(automation.controllers[controller])return automationEvents(args);
      automation.controllers[controller]=true;automation.controller=controller;automation.revision=-1;
    }
    if(num(args.revision)<automation.revision)return automationEvents(args);
    var a=args.attack || {},s=args.speed_up || {};
    var config={attack:{enabled:!!args.enabled && !!a.enabled,lead_ms:num(a.lead_ms,400),
      dynamic_lead:a.dynamic_lead===true,interval_ms:Math.max(1,Math.min(10000,num(a.interval_ms,200))),
      power_limit:num(a.power_limit),max_battles:num(a.max_battles),lowest_power_first:a.lowest_power_first===true},
      speed_up:{enabled:!!args.enabled && !!s.enabled,max_times:num(s.max_times),interval_seconds:num(s.interval_seconds)}};
    automation.revision=num(args.revision);
    if(JSON.stringify(config)===JSON.stringify(automation.config))return automationEvents(args);
    var previousLast=automation.lastAttack;
    stopAutomation();
    var epoch=automation.epoch;
    automation.config=config;automation.lastAttack=previousLast;
    automationEvent('configured',{attack:config.attack,speed_up:config.speed_up});
    if(!config.attack.enabled && !config.speed_up.enabled)return automationEvents(args);
    try {await libs();await serverNow(true);}
    catch(error){if(epoch===automation.epoch){automationEvent('initialization_error',{message:String(error),stopped:true},'ERROR');stopAutomation('初始化异常');}throw error;}
    if(epoch!==automation.epoch)return automationEvents(args);
    if(config.attack.enabled)attackTick(epoch);
    if(config.speed_up.enabled)speedTick(epoch);
    return automationEvents(args);
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
      attack_latency:attackLatencyStats(),
      marks_enabled: !!state.markTimer, mark_count: state.marks.length,
      routes_enabled: !!revealHelper && revealHelper.shouldHideStealthMarch === revealHideMarch,
      rendered_marches: marchScene && marchScene._flyFishManager && marchScene._flyFishManager._flyFishMap
        ? marchScene._flyFishManager._flyFishMap.size : 0,
      mark_error: state.markError, script_version: VERSION
    });
  }

  function stop() {
    stopAutomation('用户停用或会话关闭');
    state.attackWave++;state.attackScope='';state.lastAttackRejection=null;
    ++marksEpoch;
    if (state.markTimer) { clearInterval(state.markTimer); state.markTimer = null; }
    clearMarks();
    disableMarchReveal();
    return done({ stopped: true });
  }

  function reset() {
    if (state.pending || state.outstanding) return bad('仍有操作或请求在途，不能复位', 'uncertain');
    state.uncertain = false; state.speedTimes = 0; state.marchKey = ''; state.battles = 0; state.finalSpeedAttempted = false;
    state.attackWave++;state.attackScope='';state.lastBattleIdentity='';
    state.countedBattleKeys={};state.lastAttackRejection=null;
    automation.speedStopped='';automation.lastAttack=-Infinity;
    detachBattleObserver();
    return done({ reset: true });
  }

  g.e0e1Season = { ready: true, version: VERSION, detachBattleObserver: detachBattleObserver, pendingState: function(){return {pending:state.pending,uncertain:state.uncertain,outstanding:state.outstanding};} };
  var methods = { flags: flags, march: march, speedUp: speedUp, candidates: candidates,
    automationConfigure:automationConfigure, automationEvents:automationEvents,
    attack: attack, marks: marks, diagnose: diagnose, stop: stop, reset: reset };
  Object.keys(methods).forEach(function (name) { g.e0e1Season[name] = exportCall(name, methods[name]); });
  log('血月战场脚本已就绪：战旗探测/加速/挑战/隐匿状态标注');
})();
