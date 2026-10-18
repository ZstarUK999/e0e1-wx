// ==UserScript==
// @name 血月战场·战旗探测／正常加速／正常挑战／隐匿状态标注
// @description 只读战场同步数据（阴司成员战旗、行军、节点队列）；加速点击原按钮，挑战调用原模块方法，保留冷却、最小剩余时间、道具与状态限制；隐匿标识只画在原本就可见的单位上。
// @match *
// @run-at document-start
// @e0e1-mode runtime_toggle
// ==/UserScript//

// 说明：本脚本以语句形式直接执行（e0e1 的注入包装是 async 函数，可直接使用 await）。
// 用法：GUI 血月战场页点「启用」；CLI 用
//   python tools/cdp_inject.py --port 62000 --toggle tools/js/season_bloodmoon.js
//
// 边界（与 血月调查与插件设计.md 一致）：
//   · 只读：不拼协议、不改写角色状态、不绕过冷却与最小剩余时间。
//   · 加速点原按钮，挑战走原模块请求，并确认真实回执；请求没确认就报 uncertain，不重试。
//   · 不读取被游戏隐藏的敌方隐匿行军，隐匿目标不作为自动攻击的选敌来源。

await (async function () {
  var g = globalThis, VERSION = '2026-10-18-perf-v13', restored = null;
  if (g.e0e1Season) {
    if (g.e0e1Season.version === VERSION) return;
    var previous = await g.e0e1Season.diagnose();
    if (!previous.ok || previous.pending || previous.outstanding || previous.uncertain)
      throw new Error('旧血月脚本仍有在途操作或结果未知，暂不升级，请等待完成或核实后复位');
    var begin = (previous.trace || []).find(function (row) { return row.step === 'diagnose.begin'; });
    if (!begin || !begin.values) throw new Error('旧血月计数无法核实，不重置次数，请重新进入游戏后加载');
    restored = begin.values;
    await g.e0e1Season.stop();
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
        systemPresent: !!g.System, uiPresent: !!g.UIManager, rolePresent: !!g.ROLE,
        modulePresent: !!g.seasonModule, warId: g.seasonModule && g.seasonModule.enteredMapId });
      var result;
      try { result = await fn(args); }
      catch (e) {
        trace(name + '.exception', { message: String(e), stack: e && e.stack });
        result = bad(String(e), mutating ? 'uncertain' : 'unavailable');
      }
      trace(name + '.end', { id: id, result: result });
      if (mutating) result.request_sent = !!state.dispatched;
      result.trace = ownTrace.slice();
      if (actionTrace === ownTrace) actionTrace = null;
      return result;
    };
  }
  var state = {
    lastAttackAt: restored ? num(restored.lastAttackAt) : 0,
    captureRequest: false,
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

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function log(m) { try { g.console.info('[plugin.ui]', String(m)); } catch (e) { } }
  function bad(message, status) { if (status === 'uncertain') state.uncertain = true; trace('branch.stop', {status: status || 'unavailable', message: String(message)}); return { ok: false, status: status || 'unavailable', message: String(message) }; }
  function done(payload) { var out = { ok: true, status: 'ok' }; for (var k in (payload || {})) out[k] = payload[k]; return out; }
  function chunk(name) { return g.System.import('chunks:///_virtual/' + name); }

  async function libs() {
    if (!g.System || !g.UIManager || !g.ROLE) throw new Error('游戏尚未就绪');
    if (!lib.cc) lib.cc = await g.System.import('cc');
    if (!lib.defs) lib.defs = await chunk('define-index.ts');
    if (!lib.data) lib.data = await chunk('configs.ts');
    if (!lib.helper) lib.helper = (await chunk('role-helper.ts')).roleHelper;
    if (!lib.uiConfig) lib.uiConfig = (await chunk('ui-common-cfg.ts')).CommonUICfgId;
    if (!lib.uiConfig || typeof lib.helper.getItemCount !== 'function') throw new Error('游戏UI配置或道具接口未就绪');
    if (!lib.manager) lib.manager = (await chunk('service-manager.ts')).ServiceManager.ins;
    if (!lib.ButtonPlus) lib.ButtonPlus = (await chunk('button-plus.ts')).default;
    if (!lib.signalMod) lib.signalMod = await chunk('season-map-signal.ts');
    if (!lib.cellType) lib.cellType = (await chunk('season-queue-detail-role-cell.ts')).SeasonQueueDetailRoleCell;
    if (!lib.opCellType) lib.opCellType = (await chunk('season-op-queue-cell.ts')).SeasonOpQueueCell;
    return lib;
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
      var mod = await chunk('date-util.ts');
      var clock = mod && mod.default;
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

  async function serviceCall(action, name, expected) {
    var manager = lib.manager, original = manager.service, calls = [];
    var fnExpected = lib.defs.SeasonService && lib.defs.SeasonService[name];
    if (typeof fnExpected !== 'function') throw new Error('请求方法未核实：' + name);
    var wrapper = function (fn) {
      var args = Array.prototype.slice.call(arguments, 1), params = args[0] || {};
      var matches = state.captureRequest && fn === fnExpected && Object.keys(expected).every(function (key) {
        return String(params[key]) === String(expected[key]);
      });
      if (!matches) {
        trace('rpc.ignored', { expected: name, sameMethod: fn === fnExpected,
          warId: params.warId, targetId: params.targetId });
        return original.apply(this, [fn].concat(args));
      }
      var record = { settled: false, error: '', value: null };
      calls.push(record); state.outstanding++; state.dispatched = true;
      trace('rpc.sent', { method: name, params: expected, matchedCalls: calls.length });
      var promise;
      try { promise = original.apply(this, [fn].concat(args)); }
      catch (e) { state.outstanding--; record.settled = true; record.error = String(e); throw e; }
      Promise.resolve(promise).then(function (v) {
        record.settled = true; record.value = v; state.outstanding--;
        trace('rpc.settled', { method: name, value: v });
      }, function (e) {
        record.settled = true; record.error = String((e && e.message) || e); state.outstanding--;
        trace('rpc.exception', { method: name, error: record.error, stack: e && e.stack });
      });
      return promise;
    };
    manager.service = wrapper;
    state.captureRequest = false;
    try {
      await action();
      // One bounded observation window; an expired request is never replayed.
      var end = Date.now() + 1500;
      while (Date.now() < end && !calls.length) await sleep(50);
      end = Date.now() + 8000;
      while (Date.now() < end && calls.length && !calls[0].settled) await sleep(50);
    } finally { state.captureRequest = false; if (manager.service === wrapper) manager.service = original; }
    var first = calls[0];
    var out = { called: !!first, settled: !!(first && first.settled),
      error: first ? first.error : '', value: first ? first.value : null, count: calls.length };
    trace('rpc.observed', { method: name, expected: expected, receipt: out });
    return out;
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
      state.marchKey = key; state.speedTimes = 0;
    }
    return key;
  }

  function asButton(control) {
    if (!control) return null;
    if (control.Button_btn) return control.Button_btn;
    if (typeof control.getComponent === 'function') {
      try {
        var b = (lib.ButtonPlus && control.getComponent(lib.ButtonPlus)) || control.getComponent(lib.cc.Button);
        if (b) return b;
      } catch (e) { traceException('button.component.exception', e); }
    }
    return control;
  }

  async function clickButton(control, guard) {
    var button = asButton(control);
    var node = button && (button.node || button);
    trace('button.preflight', { control: !!control, button: !!button, node: !!node,
      name: node && node.name, emit: !!(node && typeof node.emit === 'function'),
      interactable: button && button.interactable, enabled: button && button.enabledInHierarchy,
      active: node && node.activeInHierarchy, continuous: button && button.continuous,
      clickInteractable: button && button.clickInteractable });
    if (!node || typeof node.emit !== 'function') throw new Error('按钮节点不可用');
    if (button.interactable === false || button.enabledInHierarchy === false || node.activeInHierarchy === false)
      throw new Error('按钮当前不可点击');
    var waited = 0;
    while (button.continuous || button.clickInteractable === false) {
      if (waited >= 3000) {
        trace('button.waitTimeout', { waited: waited, continuous: button.continuous, clickInteractable: button.clickInteractable });
        throw new Error('按钮仍在防连点/等待操作');
      }
      await sleep(100); waited += 100;
    }
    if (button.interactable === false || button.enabledInHierarchy === false || node.activeInHierarchy === false)
      throw new Error('等待后按钮已不可点击');
    var finalGuard = guard ? await guard() : null;
    if (typeof finalGuard === 'function') finalGuard();
    // 异步检查期间 UI 可能已变化，发触摸事件前重新核对。
    if (button.interactable === false || button.enabledInHierarchy === false ||
        node.activeInHierarchy === false || button.continuous || button.clickInteractable === false)
      throw new Error('点击前按钮状态已变化，未点击');
    trace('button.click', { name: node.name || '', interactable: button.interactable,
      enabled: button.enabledInHierarchy, active: node.activeInHierarchy,
      continuous: button.continuous, clickInteractable: button.clickInteractable });
    // 只有通过全部UI检查、即将发出触摸事件时，才开始归属本次操作的回执。
    state.captureRequest = true;
    for (var i = 0; i < 2; i++) {
      var type = i === 0 ? lib.cc.Node.EventType.TOUCH_START : lib.cc.Node.EventType.TOUCH_END;
      var ev = lib.cc.EventTouch ? new lib.cc.EventTouch([], true, type) : { type: type };
      ev.target = node;
      node.emit(type, ev);
    }
    return true;
  }

  async function waitFor(predicate, message, ms) {
    var end = Date.now() + (ms || 5000);
    while (Date.now() < end) {
      var v = null;
      try { v = predicate(); } catch (e) { traceException('wait.predicate.exception', e, {message:message, timeoutMs:ms}); v = null; }
      if (v) return v;
      await sleep(100);
    }
    throw new Error(message || '等待超时');
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

  async function march() {
    await libs();
    var m = module_();
    if (!m) return bad('血月模块尚未初始化');
    var data = mapData(), me = myRole();
    if (!me) return bad('当前没有自己的战场角色（可能还未入场）');
    var now = await serverNow(true);
    var move = null;
    try { move = (data && data.moveInfos && data.moveInfos.get) ? data.moveInfos.get(me.id) : null; } catch (e) { traceException('march.read.exception', e, {roleId:me.id}); move = null; }
    var conf = constants() || {};
    var cd = num(conf.MarchSpeedUpCD, 0), minTime = num(conf.MarchSpeedUpMinTime, 0);
    var op = null, ui = openUI('SeasonMapUI');
    if (ui && ui.view) op = ui.view.op || null;
    var cooldownUntil = op ? num(op._speedCooldownUntil, 0) : 0;
    var remainMs = move && move.arrive ? num(move.arrive) - now : 0;
    var item = conf.MarchSpeedUpItem || null;
    var itemReady = false, itemNeed = '';
    if (Array.isArray(item) && item.length >= 2) {
      try { itemReady = num(lib.helper.getItemCount(item[0]), 0) >= num(item[1], 0); } catch (e) { itemReady = false; trace('item.exception', {message: String(e)}); }
      itemNeed = item[0] + '×' + item[1];
    }
    var reasons = [];
    if (!now) reasons.push('服务器时钟未就绪');
    if (!constants()) reasons.push('加速配置未读取到，不自动点击');
    if (num(me.state) !== 2) reasons.push('自己不在行军中');
    if (!move) reasons.push('没有行军数据');
    if (cooldownUntil > now) reasons.push('加速冷却中（剩余' + Math.ceil((cooldownUntil - now) / 1000) + '秒）');
    if (move && minTime > 0 && remainMs < minTime * 1000) reasons.push('剩余时间不足' + minTime + '秒');
    if (!itemReady) reasons.push('加速道具不足（' + itemNeed + '）');
    if (!op || typeof op.getSpeedUpDisabledReason !== 'function') reasons.push('原生UI加速资格无法核实');
    else {
      try { var nativeReason = op.getSpeedUpDisabledReason(!!move && num(me.state) === 2); if (nativeReason) reasons.push(String(nativeReason)); }
      catch (e) { reasons.push('原生UI加速检查失败'); }
    }
    // 当前面板可能选中了其他建筑，不能用它缓存的按钮禁用原因阻止选中行军目标。
    if (!op) reasons.push('血月地图界面未打开');
    syncMarch(m, me, move);
    return done({
      war_id: m.enteredMapId || '', server_now: now,
      self: { roleId: num(me.id), name: me.name || '', power: num(me.power), state: num(me.state),
              stateName: stateName(me.state), flagId: num(me.flagId), flag: flagName(me.flagId),
              position: me.position ? { x: num(me.position.x), y: num(me.position.y) } : null },
      move: move ? { from: move.from ? { x: num(move.from.x), y: num(move.from.y) } : null,
                     to: move.to ? { x: num(move.to.x), y: num(move.to.y) } : null,
                     start: num(move.start), arrive: num(move.arrive), remain_ms: remainMs } : null,
      speed_up: { available: reasons.length === 0, reasons: reasons, cool_down_until: cooldownUntil,
                  min_remain_seconds: minTime, item_need: itemNeed, item_ready: itemReady,
                  times: state.speedTimes },
      constants: { MarchSpeed: num(conf.MarchSpeed, 0), MarchSpeedUpCD: cd,
                   MarchSpeedUpMinTime: minTime, MarchSpeedUp: num(conf.MarchSpeedUp, 0),
                   PreEnterMinutes: num(conf.PreEnterMinutes, 0) }
    });
  }

  // ── 动作：正常点击加速 ──

  async function speedUp(args) {
    args = args || {};
    if (state.pending) return bad('上一条命令尚未结束', 'uncertain');
    if (state.uncertain) return bad('前次操作结果未知，已停止自动操作', 'uncertain');
    state.pending = true; state.dispatched = false;
    try {
      await libs();
      var m = module_();
      if (!m) return bad('血月模块尚未初始化');
      var ui = openUI('SeasonMapUI');
      if (!ui) return bad('血月地图界面未打开');
      var op = ui.view && ui.view.op;
      if (!op) return bad('地图操作面板未就绪');
      var me = myRole();
      var data = mapData();
      var move = (data && data.moveInfos && data.moveInfos.get && me) ? data.moveInfos.get(me.id) : null;
      trace('speed.context', { module: !!m, ui: !!ui, op: !!op, me: me, move: move,
        conf: constants(), cooldownUntil: op._speedCooldownUntil, disabledReason: op._speedUpDisabledReason,
        itemCountAvailable: typeof lib.helper.getItemCount === 'function' });
      if (!move || !move.to) return bad('当前没有正在进行的行军', 'rejected');
      if (num(me.state) !== 2) return bad('自己不在行军中', 'rejected');
      var sig = null, mod = lib.signalMod;
      if (mod && mod.buildingInteracted) sig = mod.buildingInteracted;
      else if (mod && mod.SeasonMapInnerSignal && mod.SeasonMapInnerSignal.buildingInteracted) sig = mod.SeasonMapInnerSignal.buildingInteracted;
      else { for (var k in mod || {}) { var v = mod[k]; if (v && v.buildingInteracted) { sig = v.buildingInteracted; break; } } }
      if (!sig) return bad('地图信号未解析，未点击');
      if (typeof op.getSpeedUpDisabledReason !== 'function') return bad('原生UI加速资格无法核实，未点击', 'rejected');
      var nativeReason = op.getSpeedUpDisabledReason(!!move && num(me.state) === 2);
      if (nativeReason) return bad(String(nativeReason), 'waiting');
      var now = await serverNow(true);
      if (!now) return bad('服务器时钟未就绪，不点击', 'rejected');
      if (num(op._speedCooldownUntil, 0) > now) return bad('加速冷却未结束', 'waiting');
      var conf = constants();
      if (!conf) return bad('加速配置未读取到，不点击');
      syncMarch(m, me, move);
      var limit = num(args.max_times, 0);
      if (limit > 0 && state.speedTimes >= limit) return bad('本次行军加速已达上限', 'rejected');
      var item = conf.MarchSpeedUpItem;
      var itemCount = Array.isArray(item) ? num(lib.helper.getItemCount(item[0]), -1) : -1;
      trace('speed.preflight', { warId: m.enteredMapId, selfState: me.state, move: move,
        now: now, cooldownUntil: op._speedCooldownUntil, disabledReason: op._speedUpDisabledReason,
        conf: conf, itemCount: itemCount, times: state.speedTimes, limit: limit, args: args });
      if (!Array.isArray(item) || item.length < 2 || itemCount < num(item[1]))
        return bad('加速道具配置或数量不足', 'rejected');
      if (!isFinite(Number(conf.MarchSpeedUpMinTime)) || !isFinite(Number(conf.MarchSpeedUpCD)))
        return bad('加速时间配置未核实', 'rejected');
      var marginMs = Math.max(0, num(args.safety_margin_seconds, 0)) * 1000;
      var minRemainMs = num(conf.MarchSpeedUpMinTime, 0) * 1000 + marginMs;
      if (num(move.arrive) - now < minRemainMs) return bad('剩余时间不足（含安全余量）', 'waiting');
      sig.emit({ buildingId: num(move.to.x) + '_' + num(move.to.y), x: num(move.to.x), y: num(move.to.y) });
      await waitFor(function () {
        return op._bx === move.to.x && op._by === move.to.y &&
          op.btn_speed_up && op.btn_speed_up.node && op.btn_speed_up.node.activeInHierarchy !== false &&
          !op._speedUpDisabledReason && !op.getSpeedUpDisabledReason(true);
      }, '已选中行军目的地，等待原生加速按钮可操作', 3000);
      var expected = { warId: m.enteredMapId }, marchKey = state.marchKey;
      async function guardSpeed() {
        var fresh = await march();
        if (!fresh.move || !fresh.move.to || op._bx !== fresh.move.to.x || op._by !== fresh.move.to.y)
          throw new Error('当前地图选中建筑不是行军目标，未点击');
        var reason = op.getSpeedUpDisabledReason(true);
        if (reason) throw new Error(String(reason));
        trace('speed.clickGuard', { snapshot: fresh, expectedKey: marchKey, actualKey: state.marchKey });
        if (!fresh.ok || !fresh.speed_up.available || state.marchKey !== marchKey ||
            fresh.move.remain_ms < minRemainMs) throw new Error('点击前行军条件已变化，未点击');
      }
      var receipt = await serviceCall(async function () {
        await clickButton(op.btn_speed_up, guardSpeed);
      }, 'moveSpeedUp', expected);
      if (!receipt.called) {
        // 没直接发请求通常是弹了确认框，按正常流程在确认框里点。
        var dialog = null;
        try { dialog = await waitFor(function () { return openUI('SeasonMarchSpeedUpUI'); }, '', 1500); } catch (e) { traceException('speed.dialog.exception', e); dialog = null; }
        if (!dialog) return bad('未观察到加速请求，也未弹出确认框，结果未知', 'uncertain');
        if (!dialog.view || !dialog.view.btn_speed_up) return bad('确认框按钮未核实，未点击');
        receipt = await serviceCall(async function () { await clickButton(dialog.view.btn_speed_up, guardSpeed); }, 'moveSpeedUp', expected);
      }
      var failure = checkReceipt(receipt, '加速');
      if (failure) return failure;
      state.speedTimes += 1;
      return done({ confirmed: true, times: state.speedTimes, error: '' });
    } catch (e) {
      trace('action.exception', {message: String(e), stack: e && e.stack, outstanding: state.outstanding});
      return bad((e && e.message) || e, (e && e.status) || (state.dispatched ? 'uncertain' : 'unavailable'));
    } finally {
      state.pending = false;
    }
  }

  // ── 只读：当前节点候选 ──

  async function candidates() {
    await libs();
    var m = module_();
    if (!m) return bad('血月模块尚未初始化');
    var me = myRole();
    if (!me) return bad('当前没有自己的战场角色');
    var x = num(me.position && me.position.x), y = num(me.position && me.position.y);
    var snap = null;
    try { snap = m.getBuildingOpSnapshot(x, y); } catch (e) { traceException('queue.snapshot.exception', e, {x:x,y:y}); snap = null; }
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
    var clock = await serverNow(true);
    return done({
      server_now: clock, battle_end_time: battleTimer ? num(battleTimer.endTime) : 0,
      node: { x: x, y: y }, in_members: inMembers, self_state: num(me.state),
      self_state_name: stateName(me.state), self_power: num(me.power),
      self_plan_power: Array.isArray(me.planPower) ? num(me.planPower[0]) : 0,
      attack: rows(snap.attackQueue), defense: rows(snap.defenseQueue),
      battles: state.battles
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
      // 不打开队列UI；调用原UI资格函数，保留它的同节点、阵营与待命规则。
      var queueModule = await chunk('ui-season-queue-detail.ts');
      var proto = queueModule.UISeasonQueueDetail && queueModule.UISeasonQueueDetail.prototype;
      if (!proto || typeof proto.canAttack !== 'function' || typeof m.startPVPBattle !== 'function')
        return bad('原生挑战接口或资格函数不可用，未发送', 'unavailable');
      var fresh = await candidates();
      var current = (fresh.attack || []).concat(fresh.defense || []).find(function (r) { return r.roleId === roleId; });
      var mine = num(fresh.self_plan_power) || num(fresh.self_power);
      var power = current && (num(current.planPower) || num(current.power));
      var ceiling = num(args.power_limit) > 0 ? Math.min(mine, num(args.power_limit)) : mine;
      var role = mapData() && mapData().roles && mapData().roles.get(roleId);
      var eligibilityView = {module: m, buildingX:x, buildingY:y, isSameLegion:proto.isSameLegion};
      if (!fresh.ok || !fresh.node || fresh.node.x !== x || fresh.node.y !== y ||
          String(m.enteredMapId) !== String(warId) || !current || !current.attackable ||
          mine <= 0 || power <= 0 || power >= ceiling || !role || !proto.canAttack.call(eligibilityView, role))
        return bad('当前节点、目标资格或战力已变化，未发送', 'waiting');
      if (state.lastAttackAt && Date.now() - state.lastAttackAt < 1000)
        return bad('等待挑战发送间隔', 'waiting');
      var params = {targetId:roleId, warId:warId};
      state.lastAttackAt = Date.now();
      state.dispatched = true; state.outstanding++;
      trace('attack.directRequest', {params:params, minIntervalMs:1000});
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
      if (failure) return failure;
      state.battles += 1;
      return done({ confirmed: true, roleId: roleId, name: target.name || '', tab: tab, battles: state.battles, mode:'direct' });
    } catch (e) {
      trace('action.exception', {message: String(e), stack: e && e.stack, outstanding: state.outstanding});
      return bad((e && e.message) || e, (e && e.status) || (state.dispatched ? 'uncertain' : 'unavailable'));
    } finally {
      state.pending = false;
    }
  }

  // ── 隐匿状态标注：只标原本就可见的单位 ──

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

  async function marks(args) {
    args = args || {};
    await libs();
    var on = args.on !== false;
    if (state.markTimer) { clearInterval(state.markTimer); state.markTimer = null; }
    clearMarks();
    if (!on) return done({ marked: 0 });
    state.markError = null;
    state.markTimer = setInterval(function () {
      try { var perf=g.e0e1Perf;if(perf)perf.measure('season.marks.sync',markVisibleLists,null,[]);else markVisibleLists(); }
      catch (e) {
        state.markError = { at: Date.now(), message: String(e), stack: e && e.stack };
        trace('marks.tick.exception', state.markError);
      }
    }, 1000);
    return done({ marked: markVisibleLists() });
  }

  async function diagnose() {
    try { await libs(); } catch (e) { return bad('游戏尚未就绪：' + ((e && e.message) || e)); }
    var m = module_(), data = mapData(), me = myRole();
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
      mark_error: state.markError, script_version: VERSION
    });
  }

  function stop() {
    if (state.markTimer) { clearInterval(state.markTimer); state.markTimer = null; }
    clearMarks();
    return done({ stopped: true });
  }

  function reset() {
    if (state.pending || state.outstanding) return bad('仍有操作或请求在途，不能复位', 'uncertain');
    state.uncertain = false; state.speedTimes = 0; state.marchKey = ''; state.battles = 0;
    return done({ reset: true });
  }

  g.e0e1Season = { ready: true, version: VERSION };
  var methods = { flags: flags, march: march, speedUp: speedUp, candidates: candidates,
    attack: attack, marks: marks, diagnose: diagnose, stop: stop, reset: reset };
  Object.keys(methods).forEach(function (name) { g.e0e1Season[name] = exportCall(name, methods[name]); });
  log('血月战场脚本已就绪：战旗探测/加速/挑战/隐匿状态标注');
})();
