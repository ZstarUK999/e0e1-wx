// ==UserScript==
// @name 血月战场·战旗探测／正常加速／正常挑战／水旗标注
// @description 只读战场同步数据（阴司成员战旗、行军、节点队列）；加速与挑战只点正常按钮，保留冷却、最小剩余时间、道具与状态限制；水旗标识只画在原本就可见的单位上。
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
//   · 加速/挑战一律点正常按钮，并旁观真实请求回执；请求没确认就报 uncertain，不重试。
//   · 不读取被游戏隐藏的敌方隐匿行军，隐匿目标不作为自动攻击的选敌来源。

(function () {
  var g = globalThis;
  if (g.e0e1Season) return;

  var lib = {};
  var state = {
    pending: false,        // 有动作在途，禁止并发
    uncertain: false,      // 上次动作结果未知，停止后续自动动作
    marks: [],             // 已挂的「隐身水旗」节点
    markTimer: null,
    speedTimes: 0,         // 本次行军已成功加速次数
    marchKey: '',          // 当前行军标识，变了就重置计数
    battles: 0             // 本轮自动攻击已发起场次
  };

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function log(m) { try { g.console.info('[plugin.ui]', String(m)); } catch (e) { } }
  function bad(message, status) { return { ok: false, status: status || 'unavailable', message: String(message) }; }
  function done(payload) { var out = { ok: true, status: 'ok' }; for (var k in (payload || {})) out[k] = payload[k]; return out; }
  function chunk(name) { return g.System.import('chunks:///_virtual/' + name); }

  async function libs() {
    if (!g.System || !g.UIManager || !g.ROLE) throw new Error('游戏尚未就绪');
    if (!lib.cc) lib.cc = await g.System.import('cc');
    if (!lib.defs) lib.defs = await chunk('define-index.ts');
    if (!lib.data) lib.data = await chunk('configs.ts');
    if (!lib.helper) lib.helper = (await chunk('role-helper.ts')).roleHelper;
    if (!lib.manager) lib.manager = (await chunk('service-manager.ts')).ServiceManager.ins;
    if (!lib.ButtonPlus) lib.ButtonPlus = (await chunk('button-plus.ts')).default;
    if (!lib.signalMod) lib.signalMod = await chunk('season-map-signal.ts');
    if (!lib.cellType) lib.cellType = (await chunk('season-queue-detail-role-cell.ts')).SeasonQueueDetailRoleCell;
    return lib;
  }

  function module_() { return g.seasonModule || null; }
  function mapData() {
    var m = module_();
    if (m && typeof m.getSeasonMapData === 'function') {
      try { var d = m.getSeasonMapData(); if (d) return d; } catch (e) { }
    }
    return g.SEASON_MAP || null;
  }
  function myRole() {
    var m = module_();
    if (m && typeof m.getSeasonMapMyRole === 'function') {
      try { var r = m.getSeasonMapMyRole(); if (r) return r; } catch (e) { }
    }
    return null;
  }
  function each(mapLike, fn) {
    if (!mapLike) return;
    if (typeof mapLike.forEach === 'function') { mapLike.forEach(fn); return; }
    for (var k in mapLike) { if (Object.prototype.hasOwnProperty.call(mapLike, k)) fn(mapLike[k], k); }
  }
  function num(v, d) { var n = Number(v); return isFinite(n) ? n : (d || 0); }

  async function serverNow() {
    try {
      var mod = await chunk('date-util.ts');
      var clock = mod && mod.default;
      if (clock && Number(clock.serverTime) > 0) return Number(clock.serverTime);
    } catch (e) { }
    return Date.now();
  }

  function flagConfig(id) {
    var m = module_();
    try {
      var data = m && m.seasonBattleFlagData;
      var cfg = data && typeof data.getFlagConfig === 'function' ? data.getFlagConfig(id) : null;
      return cfg || null;
    } catch (e) { return null; }
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
    } catch (e) { return false; }
  }
  function stateName(s) {
    return { 0: '未入场', 1: '待命', 2: '行军', 3: '战斗', 4: '阵亡', 5: '观战' }[num(s, 0)] || ('状态' + s);
  }
  function constants() {
    try { return (lib.data && lib.data.SeasonConstantCfg && lib.data.SeasonConstantCfg.config) || null; } catch (e) { return null; }
  }
  function openUI(id) { return g.UIManager && g.UIManager.ins ? g.UIManager.ins.findOpen(id) : null; }

  async function serviceCall(action) {
    // 旁观真实请求：把 ServiceManager.service 包一层，拿这次点击实际发出的请求回执。
    var manager = lib.manager, original = manager.service, calls = [];
    var wrapper = function (fn) {
      var args = Array.prototype.slice.call(arguments, 1);
      var promise = original.apply(this, [fn].concat(args));
      var record = { settled: false, error: '', value: null };
      calls.push(record);
      Promise.resolve(promise).then(function (v) { record.settled = true; record.value = v || null; },
        function (e) { record.settled = true; record.error = String((e && e.message) || e || ''); });
      return promise;
    };
    manager.service = wrapper;
    try { await action(); } finally {
      var end = Date.now() + 1000;
      while (Date.now() < end && (!calls.length || !calls[0].settled)) await sleep(50);
      manager.service = original;
    }
    if (!calls.length) return { called: false, error: '' };
    var first = calls[0];
    return { called: true, settled: first.settled, error: first.error, value: first.value };
  }

  function asButton(control) {
    if (!control) return null;
    if (control.Button_btn) return control.Button_btn;
    if (typeof control.getComponent === 'function') {
      try {
        var b = (lib.ButtonPlus && control.getComponent(lib.ButtonPlus)) || control.getComponent(lib.cc.Button);
        if (b) return b;
      } catch (e) { }
    }
    return control;
  }

  async function clickButton(control) {
    var button = asButton(control);
    var node = button && (button.node || button);
    if (!node || typeof node.emit !== 'function') throw new Error('按钮节点不可用');
    if (button.interactable === false || button.enabledInHierarchy === false || node.activeInHierarchy === false)
      throw new Error('按钮当前不可点击');
    var waited = 0;
    while (button.continuous || button.clickInteractable === false) {
      if (waited >= 3000) throw new Error('按钮仍在防连点/等待操作');
      await sleep(100); waited += 100;
    }
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
      try { v = predicate(); } catch (e) { v = null; }
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
      list.sort(function (a, b) { return num(b && b.power) - num(a && a.power); });
      var total = 0;
      var members = list.map(function (r) {
        total += num(r.power);
        return {
          roleId: num(r.id), name: r.name || '', power: num(r.power),
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
    var now = await serverNow();
    var move = null;
    try { move = (data && data.moveInfos && data.moveInfos.get) ? data.moveInfos.get(me.id) : null; } catch (e) { move = null; }
    var conf = constants() || {};
    var cd = num(conf.MarchSpeedUpCD, 0), minTime = num(conf.MarchSpeedUpMinTime, 0);
    var op = null, ui = openUI('SeasonMapUI');
    if (ui && ui.view) op = ui.view.op || null;
    var cooldownUntil = op ? num(op._speedCooldownUntil, 0) : 0;
    var remainMs = move && move.arrive ? num(move.arrive) - now : 0;
    var item = conf.MarchSpeedUpItem || null;
    var itemReady = true, itemNeed = '';
    if (Array.isArray(item) && item.length >= 2) {
      try { itemReady = num(lib.helper.getItemCount(item[0]), 0) >= num(item[1], 0); } catch (e) { itemReady = true; }
      itemNeed = item[0] + '×' + item[1];
    }
    var reasons = [];
    if (!constants()) reasons.push('加速配置未读取到，不自动点击');
    if (num(me.state) !== 2) reasons.push('自己不在行军中');
    if (!move) reasons.push('没有行军数据');
    if (cooldownUntil > now) reasons.push('加速冷却中（剩余' + Math.ceil((cooldownUntil - now) / 1000) + '秒）');
    if (move && minTime > 0 && remainMs < minTime * 1000) reasons.push('剩余时间不足' + minTime + '秒');
    if (!itemReady) reasons.push('加速道具不足（' + itemNeed + '）');
    if (op && op._speedUpDisabledReason) reasons.push(String(op._speedUpDisabledReason));
    if (!op) reasons.push('血月地图界面未打开');
    var key = move ? (num(move.arrive) + ':' + (move.to ? move.to.x + '_' + move.to.y : '')) : '';
    if (key !== state.marchKey) { state.marchKey = key; state.speedTimes = 0; }
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
    state.pending = true;
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
      if (!move || !move.to) return bad('当前没有正在进行的行军', 'rejected');
      if (num(me.state) !== 2) return bad('自己不在行军中', 'rejected');
      var sig = null, mod = lib.signalMod;
      if (mod && mod.buildingInteracted) sig = mod.buildingInteracted;
      else if (mod && mod.SeasonMapInnerSignal && mod.SeasonMapInnerSignal.buildingInteracted) sig = mod.SeasonMapInnerSignal.buildingInteracted;
      else { for (var k in mod || {}) { var v = mod[k]; if (v && v.buildingInteracted) { sig = v.buildingInteracted; break; } } }
      if (!sig) return bad('地图信号未解析，未点击');
      if (op._speedUpDisabledReason) return bad(String(op._speedUpDisabledReason), 'rejected');
      var now = await serverNow();
      if (num(op._speedCooldownUntil, 0) > now) return bad('加速冷却未结束', 'rejected');
      var conf = constants();
      if (!conf) return bad('加速配置未读取到，不点击');
      var marginMs = num(args.safety_margin_seconds, 0) * 1000;
      var minRemainMs = num(conf.MarchSpeedUpMinTime, 0) * 1000 + marginMs;
      if (num(move.arrive) - now < minRemainMs) return bad('剩余时间不足（含安全余量）', 'rejected');
      sig.emit({ buildingId: num(move.to.x) + '_' + num(move.to.y), x: num(move.to.x), y: num(move.to.y) });
      await waitFor(function () { return op.btn_speed_up && op.btn_speed_up.node && op.btn_speed_up.node.activeInHierarchy !== false; }, '加速按钮未出现', 3000);
      var receipt = await serviceCall(async function () {
        await clickButton(op.btn_speed_up);
      });
      if (!receipt.called) {
        // 没直接发请求通常是弹了确认框，按正常流程在确认框里点。
        var dialog = null;
        try { dialog = await waitFor(function () { return openUI('SeasonMarchSpeedUpUI'); }, '', 1500); } catch (e) { dialog = null; }
        if (!dialog) return bad('未观察到加速请求，也未弹出确认框，结果未知', 'uncertain');
        if (!dialog.view || !dialog.view.btn_speed_up) return bad('确认框按钮未核实，未点击');
        receipt = await serviceCall(async function () { await clickButton(dialog.view.btn_speed_up); });
      }
      if (!receipt.called) return bad('未观察到加速请求，结果未知', 'uncertain');
      if (receipt.error) return bad('加速请求出错：' + receipt.error, 'rejected');
      if (receipt.value && receipt.value.err) return bad('加速被拒绝：' + receipt.value.err, 'rejected');
      await sleep(600);
      state.speedTimes += 1;
      return done({ confirmed: true, times: state.speedTimes, error: '' });
    } catch (e) {
      if (e && e.status === 'uncertain') state.uncertain = true;
      return bad((e && e.message) || e, (e && e.status) || 'unavailable');
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
    try { snap = m.getBuildingOpSnapshot(x, y); } catch (e) { snap = null; }
    if (!snap) return bad('当前节点没有可用的队列快照');
    var data = mapData();
    var building = null;
    try { building = data && data.buildings ? data.buildings.get(x + '_' + y) : null; } catch (e) { building = null; }
    var inMembers = false;
    try { inMembers = !!(building && building.members && building.members.has && building.members.has(me.id)); } catch (e) { inMembers = false; }
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
        try { inBuilding = !!(building && building.members && building.members.has && building.members.has(role.id)); } catch (e) { inBuilding = false; }
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
    return done({
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
    state.pending = true;
    try {
      await libs();
      var m = module_();
      if (!m) return bad('血月模块尚未初始化');
      var me = myRole();
      if (!me) return bad('当前没有自己的战场角色');
      var x = num(me.position && me.position.x), y = num(me.position && me.position.y);
      var snap = null;
      try { snap = m.getBuildingOpSnapshot(x, y); } catch (e) { snap = null; }
      if (!snap) return bad('当前节点没有可用的队列快照', 'rejected');
      var data = mapData(), building = null;
      try { building = data && data.buildings ? data.buildings.get(x + '_' + y) : null; } catch (e) { building = null; }
      var hasMe = false, hasTarget = false;
      try { hasMe = !!(building && building.members && building.members.has(me.id)); } catch (e) { }
      try { hasTarget = !!(building && building.members && building.members.has(roleId)); } catch (e) { }
      if (!hasMe) return bad('自己不在此节点驻留，不发起挑战', 'rejected');
      if (!hasTarget) return bad('目标不在此节点驻留，不发起挑战', 'rejected');
      if (num(me.state) !== 1) return bad('自己不是待命状态（' + stateName(me.state) + '）', 'rejected');
      var target = null, tab = 0;
      [['attackQueue', 0], ['defenseQueue', 1]].forEach(function (pair) {
        if (target) return;
        ((snap[pair[0]] || [])).forEach(function (item) {
          if (target || !item || !item.role) return;
          if (num(item.role.id) === roleId) { target = item.role; tab = pair[1]; }
        });
      });
      if (!target) return bad('目标不在当前可见队列里，不发起挑战', 'rejected');
      var side = num(me.lId, 0);
      if (side > 0 && num(target.lId, 0) === side) return bad('目标与己方同阵营，不发起挑战', 'rejected');
      var ui = g.UIManager.ins;
      var existing = ui.findOpen('SeasonQueueDetailUI');
      if (existing) {
        try { await clickButton(existing.view.btn_close); } catch (e) { }
        await waitFor(function () { return !ui.findOpen('SeasonQueueDetailUI'); }, '队列界面未关闭', 3000);
      }
      ui.open('SeasonQueueDetailUI', { tab: tab, buildingX: x, buildingY: y });
      var screen = await waitFor(function () { return ui.findOpen('SeasonQueueDetailUI'); }, '节点队列界面未打开', 5000);
      await waitFor(function () { return (tab === 0 ? screen.attackEntries : screen.defenseEntries).length > 0; }, '队列列表尚未渲染', 5000);
      var entries = tab === 0 ? screen.attackEntries : screen.defenseEntries;
      var index = -1;
      for (var i = 0; i < entries.length; i++) { if (num(entries[i].roleId) === roleId) { index = i; break; } }
      if (index < 0) return bad('目标已不在队列里，不发起挑战', 'rejected');
      var list = tab === 0 ? screen.view.list_attack : screen.view.list_defense;
      if (!list || typeof list.getItemByListId !== 'function') return bad('队列列表不可用');
      if (!list.getItemByListId(index) && typeof list.scrollTo === 'function') list.scrollTo(index, 0);
      var node = await waitFor(function () { return list.getItemByListId(index); }, '目标行未渲染', 3000);
      var cell = lib.cellType ? node.getComponent(lib.cellType) : null;
      if (!cell || !cell.btn_attack) return bad('挑战按钮未核实，未点击');
      if (cell.btn_attack.node && cell.btn_attack.node.activeInHierarchy === false) return bad('挑战按钮当前不可见（不满足挑战条件）', 'rejected');
      var receipt = await serviceCall(async function () { await clickButton(cell.btn_attack); });
      if (!receipt.called) return bad('未观察到挑战请求，结果未知', 'uncertain');
      if (receipt.error) return bad('挑战请求出错：' + receipt.error, 'rejected');
      if (receipt.value && receipt.value.err) return bad('挑战被拒绝：' + receipt.value.err, 'rejected');
      state.battles += 1;
      return done({ confirmed: true, roleId: roleId, name: target.name || '', tab: tab, battles: state.battles });
    } catch (e) {
      if (e && e.status === 'uncertain') state.uncertain = true;
      return bad((e && e.message) || e, (e && e.status) || 'unavailable');
    } finally {
      state.pending = false;
    }
  }

  // ── 水旗标注：只标原本就可见的单位 ──

  function clearMarks() {
    state.marks.forEach(function (node) { try { if (node && node.isValid) node.destroy(); } catch (e) { } });
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
      if (!keep) { try { if (node && node.isValid) node.destroy(); } catch (e) { } }
      return keep;
    });
    var marked = 0;
    needed.forEach(function (node) { if (attachMark(node, '隐身水旗')) marked++; });
    return marked;
  }

  function markVisibleLists() {
    var pairs = [];
    var queue = openUI('SeasonQueueDetailUI');
    if (queue && queue.view) {
      pairs.push([queue.view.list_attack, queue.attackEntries]);
      pairs.push([queue.view.list_defense, queue.defenseEntries]);
    }
    var map = openUI('SeasonMapUI');
    var op = map && map.view ? map.view.op : null;
    if (op) {
      pairs.push([op.list_attack, op._attackEntries]);
      pairs.push([op.list_defense, op._defenseEntries]);
    }
    var needed = [];
    pairs.forEach(function (pair) {
      var list = pair[0], entries = pair[1] || [];
      if (!list || typeof list.getItemByListId !== 'function') return;
      for (var i = 0; i < entries.length; i++) {
        var entry = entries[i];
        if (!entry || !entry.role || !isStealth(entry.role)) continue;
        var node = list.getItemByListId(i);
        if (node && needed.indexOf(node) < 0) needed.push(node);
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
    state.markTimer = setInterval(function () { try { markVisibleLists(); } catch (e) { } }, 1000);
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
      pending: state.pending, uncertain: state.uncertain
    });
  }

  function stop() {
    if (state.markTimer) { clearInterval(state.markTimer); state.markTimer = null; }
    clearMarks();
    state.speedTimes = 0; state.marchKey = ''; state.battles = 0;
    return done({ stopped: true });
  }

  function reset() {
    state.uncertain = false; state.speedTimes = 0; state.marchKey = ''; state.battles = 0;
    return done({ reset: true });
  }

  g.e0e1Season = {
    ready: true, flags: flags, march: march, speedUp: speedUp, candidates: candidates,
    attack: attack, marks: marks, diagnose: diagnose, stop: stop, reset: reset
  };
  log('血月战场脚本已就绪：战旗探测/加速/挑战/水旗标注');
})();
