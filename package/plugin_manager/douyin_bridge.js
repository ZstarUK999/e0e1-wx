// Evaluated inside the game's module factory. All I/O uses the platform filesystem.
(function (g) {
  'use strict';
  const token = __BRIDGE_TOKEN__;
  const build = __BRIDGE_BUILD__;
  const staticScripts = __BRIDGE_STATIC_SCRIPTS__;
  if (g.__e0e1DouyinBridge) return;
  const fs = g.tt.getFileSystemManager();
  const prefix = g.tt.env.USER_DATA_PATH + '/e0e1-plugin-';
  const runtime = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  let lastSequence = 0;
  let busy = false, stopped = false, lastError = '';
  function read(name) {
    try { return JSON.parse(fs.readFileSync(prefix + name + '.json', 'utf8')); }
    catch (_) { return null; }
  }
  function write(name, value) {
    const data = JSON.stringify(value);
    // Readers retry partial JSON. Use only the filesystem write API already
    // verified in the live game, without assuming overwrite semantics of rename.
    fs.writeFileSync(prefix + name + '.json', data, 'utf8');
  }
  function errorText(e) { return String(e && (e.stack || e.message) || e).slice(0, 4000); }
  function heartbeat() {
    let hall = false;
    let playerId = '';
    const game = !!(g.UIManager && g.ROLE && g.System);
    try {
      const role = g.ROLE || {};
      playerId = role.id != null ? String(role.id) : role.heroId != null ? String(role.heroId) : '';
    } catch (_) {}
    try { hall = !!(game && g.CommonUICfgId && g.UIManager.ins.findOpen(g.CommonUICfgId.MainUI)); } catch (_) {}
    try {
      write('state', {token, build, runtime, appid: 'tt310e47b3ae06acc002', at: Date.now(),
        game, hall, busy, lastSequence, resident: g.__e0e1PluginRuntime && g.__e0e1PluginRuntime.id || null,
        protocol: 'static-v1', player_id: playerId, error: lastError});
    } catch (e) { lastError = errorText(e); }
  }
  function receipt(value) { return typeof value === 'string' ? JSON.parse(value) : value; }
  function rememberDamage(enabled) { write('persistent', {token, damage: enabled}); }
  async function stopDamage() {
    const result = receipt(await staticScripts.damageStop());
    if (!result.ok) throw new Error(result.error || '停止采集未确认');
    rememberDamage(false);
    return result;
  }
  async function enableDamage() {
    await stopDamage();
    const result = receipt(await staticScripts.damageEnable());
    if (!result.ok || !result.enabled) throw new Error(result.error || result.message || '伤害脚本未启用');
    rememberDamage(true);
    return result;
  }
  async function dispatch(action, args) {
    args = args || {};
    const resident = g.__e0e1PluginRuntime;
    switch (action) {
      case 'ping': return 2;
      case 'install': return staticScripts.resident(args.id);
      case 'call':
        return resident && resident.id === args.id ? resident.dispatch(args.op, args.payload || {})
          : {status: 'uncertain', message: '游戏会话身份已改变'};
      case 'idle': {
        const guard = g.__e0e1EnergyGuard;
        return !resident ? {gone:true} : {id:resident.id,pending:!!(resident.pending || guard && (guard.pending || guard.action_pending || guard.callback_count))};
      }
      case 'damage-inject': return enableDamage();
      case 'damage-stop': return stopDamage();
      case 'damage-status': return typeof g.damageCurveStatus === 'function' ? g.damageCurveStatus() : null;
      case 'damage-snapshot': return typeof g.damageCurveJson === 'function' ? g.damageCurveJson() : null;
      case 'damage-debug': return typeof g.damageCurveDebug === 'function' ? g.damageCurveDebug() : null;
      case 'damage-reset': return typeof g.damageCurveReset === 'function' ? String(g.damageCurveReset()) : '采集脚本尚未注入';
      case 'treasure-inject': return staticScripts.treasure();
      case 'treasure-dump': return typeof g.dumpTreasureMap === 'function' ? g.dumpTreasureMap() : null;
      case 'treasure-overlay': {
        const fn = args.on ? g.treasureMapOverlayOn : g.treasureMapOverlayOff;
        return typeof fn === 'function' ? String(fn()) : '摸金脚本尚未注入';
      }
      case 'treasure-status': return typeof g.treasureMapOverlayStatus === 'function' ? String(g.treasureMapOverlayStatus()) : '摸金脚本尚未注入';
      case 'season-inject': return staticScripts.season();
      case 'season-call': {
        const allowed = ['reset','diagnose','stop','marks','flags','march','speedUp','candidates','attack'];
        if (!allowed.includes(args.name)) throw new Error('不支持的血月命令');
        const api = g.e0e1Season;
        return api && typeof api[args.name] === 'function' ? api[args.name](args.payload || {})
          : {ok:false,status:'unavailable',message:'血月脚本尚未注入'};
      }
      default: throw new Error('不支持的抖音结构化命令');
    }
  }
  async function poll() {
    if (stopped || busy) return;
    const command = read('command');
    if (!command || command.token !== token || command.runtime !== runtime
        || typeof command.id !== 'string' || !Number.isSafeInteger(command.sequence)
        || command.sequence <= lastSequence) {
      // Persistent scripts replay only when a new game context starts.
      return;
    }
    lastSequence = command.sequence;
    busy = true;
    heartbeat();
    let response;
    try {
      if (Date.now() > command.deadline) throw new Error('命令已过期，未执行');
      if (typeof command.action !== 'string' || 'expression' in command) throw new Error('仅支持结构化命令');
      response = {token, runtime, id: command.id, ok: true, value: await dispatch(command.action, command.args)};
    } catch (e) {
      response = {token, runtime, id: command.id, ok: false, error: errorText(e)};
    }
    try { write('response', response); }
    catch (e) {
      lastError = errorText(e);
      try { write('response', {token, runtime, id: command.id, ok: false, error: '回执序列化或写入失败: ' + lastError}); } catch (_) {}
    } finally { busy = false; heartbeat(); }
  }
  g.__e0e1DouyinBridge = {runtime, build, stop() { stopped = true; clearInterval(tick); clearInterval(pulse); clearInterval(replay); }};
  const pulse = setInterval(heartbeat, 500);
  const tick = setInterval(function () {
    if (!busy) poll().catch(e => {lastError = errorText(e); heartbeat();});
  }, 100);
  const replay = setInterval(function () {
    if (g.UIManager && g.System && !busy) {
      clearInterval(replay);
      busy = true;
      const config = read('persistent');
      const replayDamage = config && config.token === token && config.damage === true;
      Promise.resolve(replayDamage ? enableDamage() : null).catch(e => {lastError = errorText(e);}).finally(() => {busy = false; heartbeat();});
    }
  }, 250);
  heartbeat();
})(globalThis);
