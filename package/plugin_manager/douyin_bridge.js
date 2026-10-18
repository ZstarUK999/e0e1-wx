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
  // Douyin-only background protection. A fresh manager lease is required;
  // no synthetic input, network flags, automatic login or business-command replay.
  const keepAlive = {active:false, background:false, resumes:0, error:''};
  let cocos = null, loadingCocos = false, nextCocosTry = 0, resumedInBackground = false;
  let keepScreenRequested = false, nativeKeepScreen = null;
  const screenOriginal = g.tt.setKeepScreenOn;
  let screenWrapper = null;
  if (typeof screenOriginal === 'function') {
    screenWrapper = function(options) {
      if (options && typeof options.keepScreenOn === 'boolean') nativeKeepScreen = options.keepScreenOn;
      return screenOriginal.apply(this, arguments);
    };
    try { g.tt.setKeepScreenOn = screenWrapper; } catch (_) { screenWrapper = null; }
  }
  function releaseKeepAlive() {
    if (resumedInBackground && keepAlive.background && cocos) {
      try { cocos.director.pause(); cocos.game.pause(); } catch (e) {keepAlive.error = errorText(e);}
    }
    resumedInBackground = false;
    if (keepScreenRequested && typeof nativeKeepScreen === 'boolean') {
      try {screenOriginal.call(g.tt,{keepScreenOn:nativeKeepScreen,fail:e=>{keepAlive.error=errorText(e);}});} catch(e){keepAlive.error=errorText(e);}
    }
    keepScreenRequested = false;keepAlive.active = false;
  }
  function maintainKeepAlive() {
    const lease = read('lease'), resident = g.__e0e1PluginRuntime;
    const age = lease ? Date.now() - lease.at : Infinity;
    const active = !stopped && lease && lease.token === token && lease.runtime === runtime && resident &&
      lease.resident === resident.id && age >= 0 && age < 15000;
    if (!active) {if (keepAlive.active) releaseKeepAlive();return;}
    keepAlive.active = true;
    if (!keepScreenRequested && typeof screenOriginal === 'function') {
      keepScreenRequested = true;
      try {screenOriginal.call(g.tt,{keepScreenOn:true,fail:e=>{keepAlive.error=errorText(e);}});} catch(e){keepAlive.error=errorText(e);}
    }
    if (!cocos && !loadingCocos && g.System && typeof g.System.import === 'function' && Date.now() >= nextCocosTry) {
      loadingCocos = true;nextCocosTry = Date.now() + 30000;
      Promise.resolve().then(()=>g.System.import('cc')).then(value=>{cocos=value;},e=>{keepAlive.error=errorText(e);}).finally(()=>{loadingCocos=false;});
    }
    if (keepAlive.background && cocos) {
      try {
        let resumed = false;
        if (cocos.game && typeof cocos.game.isPaused === 'function' && cocos.game.isPaused()) {cocos.game.resume();resumed=true;}
        if (cocos.director && typeof cocos.director.isPaused === 'function' && cocos.director.isPaused()) {cocos.director.resume();resumed=true;}
        if(resumed){resumedInBackground=true;keepAlive.resumes++;}
      } catch(e) {keepAlive.error=errorText(e);}
    }
  }
  const onHide = function(){keepAlive.background=true;keepScreenRequested=false;};
  const onShow = function(){keepAlive.background=false;resumedInBackground=false;keepScreenRequested=false;};
  try {if(typeof g.tt.onHide==='function')g.tt.onHide(onHide);if(typeof g.tt.onShow==='function')g.tt.onShow(onShow);} catch(e){keepAlive.error=errorText(e);}
  let shutdownHandled = false;
  function applyShutdown() {
    if(shutdownHandled)return;
    const request=read('shutdown'), resident=g.__e0e1PluginRuntime;
    if(!request || request.token!==token || request.runtime!==runtime || !resident || request.resident!==resident.id)return;
    shutdownHandled=true;stopped=true;resident.stopped=true;
    releaseKeepAlive();
    try {if(g.e0e1Season && typeof g.e0e1Season.stop==='function')Promise.resolve(g.e0e1Season.stop()).catch(e=>{lastError=errorText(e);});}catch(e){lastError=errorText(e);}
    try {if(typeof g.treasureMapOverlayOff==='function')g.treasureMapOverlayOff();if(g.e0e1Perf)g.e0e1Perf.stop();}catch(e){lastError=errorText(e);}
    Promise.resolve().then(()=>stopDamage()).catch(e=>{lastError=errorText(e);});
  }
  function heartbeat() {
    const perf=g.e0e1Perf;
    return perf ? perf.measure('douyin.heartbeat.sync',heartbeatBody,null,[]) : heartbeatBody();
  }
  function heartbeatBody() {
    applyShutdown();
    maintainKeepAlive();
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
        protocol: 'static-v1', player_id: playerId, error: lastError, keep_alive: {...keepAlive}});
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
      case 'perf-start': return staticScripts.perf();
      case 'perf-status': return g.e0e1Perf ? g.e0e1Perf.snapshot() : null;
      case 'perf-stop': return g.e0e1Perf ? g.e0e1Perf.stop() : null;
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
  g.__e0e1DouyinBridge = {runtime, build, stop() { stopped = true;releaseKeepAlive();
    try {if(typeof g.tt.offHide==='function')g.tt.offHide(onHide);if(typeof g.tt.offShow==='function')g.tt.offShow(onShow);
      if(screenWrapper && g.tt.setKeepScreenOn===screenWrapper)g.tt.setKeepScreenOn=screenOriginal;} catch (_) {}
    clearInterval(tick);clearInterval(pulse);clearInterval(replay); }};
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
