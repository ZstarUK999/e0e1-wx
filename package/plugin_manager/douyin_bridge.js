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
  let lastAutomationAt = 0;
  function read(name) {
    try { return JSON.parse(fs.readFileSync(prefix + name + '.json', 'utf8')); }
    catch (_) { return null; }
  }
  function write(name, value) {
    const data = JSON.stringify(value);
    // Readers retry partial JSON. Use only the filesystem write API already
    // verified in the live game, without assuming overwrite semantics of rename.
    try { fs.writeFileSync(prefix + name + '.json', data, 'utf8'); }
    catch(e) {
      if (!String(e).includes('size limit exceeded') || stressFilling) throw e;
      if (releaseReserve()) {
        try { fs.writeFileSync(prefix + name + '.json', data, 'utf8'); return; }
        catch(retry) { if (!String(retry).includes('size limit exceeded')) throw retry; }
      }
      if (!reclaimStorage()) throw e;
      fs.writeFileSync(prefix + name + '.json', data, 'utf8');
    }
  }
  let storageCC = null, reclaiming = false, stressFilling = false;
  const storageCleanup = {files:0, bytes:0, last:[], error:''};
  const reservePath = prefix + 'reserve-' + runtime + '.bin';
  const storageReserve = {checked:false, bytes:0, target_bytes:32768, released:0, error:''};
  let reserveRetryAt = 0;
  function releaseReserve() {
    if(!storageReserve.bytes)return false;
    try {
      fs.unlinkSync(reservePath);storageReserve.bytes=0;storageReserve.released++;
      reserveRetryAt=Date.now()+30000;return true;
    }catch(e){storageReserve.error=errorText(e);return false;}
  }
  function allocateReserve(cleanup) {
    if(storageReserve.bytes || stopped)return;
    reserveRetryAt=Date.now()+30000;
    const data=(runtime+'|').padEnd(storageReserve.target_bytes,'r');
    try {
      try{fs.writeFileSync(reservePath,data,'utf8');}
      catch(e){
        if(!cleanup || !String(e).includes('size limit exceeded') || !reclaimStorage())throw e;
        fs.writeFileSync(reservePath,data,'utf8');
      }
      storageReserve.bytes=storageReserve.target_bytes;storageReserve.error='';
    }catch(e){storageReserve.error=errorText(e);}
  }
  async function checkStorage() {
    if(storageReserve.checked)return;
    try {
      storageCC=await g.System.import('cc');
      // A successful real allocation is the capacity check; no assumed quota.
      // Reclaim only our old reserve files left after abnormal termination.
      for(const name of fs.readdirSync(g.tt.env.USER_DATA_PATH)) {
        if(/^e0e1-plugin-reserve-[a-z0-9-]+\.bin$/.test(name))
          fs.unlinkSync(g.tt.env.USER_DATA_PATH+'/'+name);
      }
      storageReserve.checked=true;
      allocateReserve(true);
    }catch(e){storageReserve.error=errorText(e);}
  }
  function fileSize(path) {
    const result = fs.statSync(path);
    const stat = result.stats || result;
    return stat.isFile() ? stat.size : 0;
  }
  function reclaimStorage() {
    const manager = storageCC && storageCC.assetManager && storageCC.assetManager.cacheManager;
    if (reclaiming || !manager || !manager.cachedFiles || typeof manager.removeCache !== 'function') return false;
    reclaiming = true;
    let freed = 0;
    try {
      const root = g.tt.env.USER_DATA_PATH + '/gamecaches/';
      const indexed = new Set(), videos = [];
      manager.cachedFiles.forEach((entry,key)=>{
        if (!entry || typeof entry.url !== 'string') return;
        indexed.add(entry.url);
        if (/^https?:\/\//.test(key) && entry.url.startsWith(root) && !entry.url.includes('/../') &&
            /\.(mp4|webm|mov|avi|m4v)(?:[?#]|$)/i.test(entry.url))
          videos.push({key,path:entry.url,last:Number(entry.lastTime)||0});
      });
      videos.sort((a,b)=>a.last-b.last);
      // Delete bytes before the index rewrite: a completely full directory may
      // reject the index write itself. removeCache then updates the live index.
      for (const item of videos) {
        try {
          const size = fileSize(item.path); if (!size) continue;
          fs.unlinkSync(item.path); freed += size;
          storageCleanup.files++; storageCleanup.bytes += size;
          storageCleanup.last = [item.path];
          manager.removeCache(item.key);
          if (freed >= 32768) break;
        } catch(e) {storageCleanup.error=errorText(e);}
      }
      // Only unindexed regular files are eligible after videos, never the index,
      // configuration, or files still being written by the download queue.
      if (freed < 32768 && !Object.keys(manager.cacheQueue || {}).length) {
        const walk=(dir,depth)=>{
          if(depth>8 || freed>=32768)return;
          for(const name of fs.readdirSync(dir)) {
            if(typeof name!=='string'||name.includes('/')||name.includes('\\')||name==='.'||name==='..')continue;
            const path=dir+'/'+name;
            try {
              const result=fs.statSync(path), stat=result.stats||result;
              if(stat.isDirectory())walk(path,depth+1);
              else if(stat.isFile() && name!=='cacheList.json' && !indexed.has(path) &&
                      Date.now() - stat.lastModifiedTime > 60000) {
                fs.unlinkSync(path);freed+=stat.size;
                storageCleanup.files++;storageCleanup.bytes+=stat.size;storageCleanup.last=[path];
              }
            }catch(e){storageCleanup.error=errorText(e);}
            if(freed>=32768)break;
          }
        };
        walk(root.slice(0,-1),0);
      }
    } catch(e) {storageCleanup.error=errorText(e);}
    finally {reclaiming=false;}
    return freed>0;
  }
  // Only one bounded response file exists; acknowledgement releases it via the
  // platform API so its quota accounting stays consistent.
  let transfer = null;
  function clearResponse() {
    try { fs.unlinkSync(prefix + 'response.json'); } catch (_) {}
  }
  function sendPart() {
    const t = transfer;
    if (!t) return;
    let end = Math.min(t.offset + t.size, t.text.length);
    if (end < t.text.length && /[\uD800-\uDBFF]/.test(t.text[end - 1])) end--;
    const part = {token, runtime, id:t.id, chunked:true, index:t.index,
      final:end === t.text.length, data:t.text.slice(t.offset,end)};
    clearResponse();
    try { write('response', part); }
    catch (e) {
      if (String(e).includes('size limit exceeded') && t.size > 1024) {
        t.size = Math.max(1024, Math.floor(t.size / 2));
        return sendPart();
      }
      throw e;
    }
    t.end = end; t.at = Date.now();
  }
  function acknowledgeResponse() {
    const ack = read('response-ack');
    if (!ack || ack.token !== token || ack.runtime !== runtime) return;
    if (transfer && ack.id === transfer.id && ack.index === transfer.index) {
      if (transfer.end === transfer.text.length) { transfer = null; clearResponse(); }
      else { transfer.offset = transfer.end; transfer.index++; sendPart(); }
    } else if (!transfer) {
      const reply = read('response');
      if (reply && reply.id === ack.id && reply.runtime === runtime && reply.token === token) clearResponse();
    }
  }
  function publishResponse(response) {
    const text = JSON.stringify(response);
    clearResponse();
    if (text.length <= 16384) {
      try { write('response',response); return; }
      catch(e) { if (!String(e).includes('size limit exceeded')) throw e; }
    }
    transfer = {id:response.id, text, offset:0, index:0, size:65536, at:Date.now()};
    sendPart();
  }
  function errorText(e) { return String(e && (e.stack || e.message) || e).slice(0, 4000); }
  // Explicit, one-shot filesystem capability probe. Never changes transport.
  let storageProbe = null;
  const probeRequest = read('storage-probe-request');
  if (probeRequest && probeRequest.token === token && probeRequest.id &&
      Number.isFinite(probeRequest.at) && Date.now() - probeRequest.at >= 0 && Date.now() - probeRequest.at < 3600000) {
    const previous = read('storage-probe-result');
    if (!previous || previous.id !== probeRequest.id) {
      const path = 'ttfile://temp/e0e1-probe-' + runtime + '.txt';
      const content = 'e0e1 temporary storage probe';
      storageProbe = {id:probeRequest.id, runtime, path, write:false, read:false, removed:false};
      let created = false;
      try {
        fs.writeFileSync(path, content, 'utf8'); created = true; storageProbe.write = true;
        storageProbe.read = fs.readFileSync(path, 'utf8') === content;
      } catch(e) { storageProbe.error = errorText(e); }
      finally {
        if (created) {
          try { fs.unlinkSync(path); storageProbe.removed = true; }
          catch(e) { storageProbe.cleanup_error = errorText(e); }
        }
      }
      try { write('storage-probe-result', storageProbe); } catch(e) { storageProbe.result_error = errorText(e); }
    }
  }
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
      Promise.resolve().then(()=>g.System.import('cc')).then(value=>{cocos=value;storageCC=value;},e=>{keepAlive.error=errorText(e);}).finally(()=>{loadingCocos=false;});
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
  let shutdownHandled = false, cleanupPending = false, cleanupError = '';
  function residentPending() {
    const resident=g.__e0e1PluginRuntime,guard=g.__e0e1EnergyGuard;
    let season=null;
    try {if(g.e0e1Season && typeof g.e0e1Season.pendingState==='function')season=g.e0e1Season.pendingState();}
    catch(_){return true;}
    return !!(resident && resident.pending || guard && (guard.pending || guard.action_pending || guard.callback_count) ||
      season && (season.pending || season.uncertain || season.outstanding));
  }
  function reusableResident() {
    const resident=g.__e0e1PluginRuntime;
    return !!(resident && resident.stopped && !residentPending() && !busy && !transfer && !cleanupPending && !cleanupError);
  }
  function applyShutdown() {
    if(shutdownHandled)return;
    const request=read('shutdown'), resident=g.__e0e1PluginRuntime;
    if(!request || request.token!==token || request.runtime!==runtime || !resident || request.resident!==resident.id)return;
    shutdownHandled=true;stopped=true;resident.stopped=true;releaseReserve();
    releaseKeepAlive();
    if(g.__e0e1BattleAssist)g.__e0e1BattleAssist.destroy();
    if(g.__e0e1AutomationOverlay)g.__e0e1AutomationOverlay.destroy();
    cleanupPending=true;
    Promise.resolve().then(async()=>{
      if(g.e0e1Season && typeof g.e0e1Season.stop==='function')await g.e0e1Season.stop();
      if(typeof g.treasureMapOverlayOff==='function')g.treasureMapOverlayOff();
      if(g.e0e1Perf)g.e0e1Perf.stop();
      await stopDamage();
    }).catch(e=>{cleanupError=lastError=errorText(e);}).finally(()=>{cleanupPending=false;heartbeat();});
  }
  function heartbeat() {
    const perf=g.e0e1Perf;
    return perf ? perf.measure('douyin.heartbeat.sync',heartbeatBody,null,[]) : heartbeatBody();
  }
  function heartbeatBody() {
    applyShutdown();
    const control=read('automation'),overlay=g.__e0e1AutomationOverlay,resident=g.__e0e1PluginRuntime;
    if(!stopped && resident && control && control.token===token && control.runtime===runtime && control.resident===resident.id &&
       Number.isFinite(control.at) && Date.now()-control.at>=0 && Date.now()-control.at<5000 && control.at!==lastAutomationAt) {
      lastAutomationAt=control.at;
      const getOverlay=overlay?Promise.resolve(overlay):control.payload && control.payload.active && resident.ensure?
        resident.ensure('automation_overlay'):Promise.resolve(null);
      getOverlay.then(api=>{if(api && !stopped && !resident.stopped)return api.update(control.payload);}).catch(e=>{lastError=errorText(e);});
    }
    maintainKeepAlive();
    if(storageReserve.checked && !busy && !transfer && !storageReserve.bytes && Date.now()>=reserveRetryAt)
      allocateReserve(false);
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
        phase: stopped ? (cleanupPending || busy || residentPending() || transfer ? 'stopping' : 'stopped') : 'running',
        resident_stopped: !!(g.__e0e1PluginRuntime && g.__e0e1PluginRuntime.stopped),
        resident_pending: residentPending(), reusable: reusableResident(), cleanup_pending:cleanupPending, cleanup_error:cleanupError,
        protocol: 'static-v1', storage_reserve: storageReserve, storage_cleanup: storageCleanup, storage_probe: storageProbe, automation: g.__e0e1AutomationOverlay ? g.__e0e1AutomationOverlay.snapshot() : null, player_id: playerId, error: lastError, keep_alive: {...keepAlive}});
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
      case 'install': {
        if(resident && resident.id!==args.id) {
          // poll owns the queue while dispatching; busy is expected here.
          if(!resident.stopped || residentPending() || transfer || cleanupPending || cleanupError)
            throw Error('旧插件实例尚未安全停止，请等待收尾或完全退出小游戏后重新进入');
          if(g.__e0e1AutomationOverlay)g.__e0e1AutomationOverlay.destroy();
          delete g.__e0e1PluginRuntime;
        }
        stopped=false;shutdownHandled=false;cleanupError='';lastAutomationAt=0;
        const installed=await staticScripts.resident(args.id);
        await checkStorage();
        return installed;
      }
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
      case 'battle-assist-timing': return g.__e0e1BattleAssist ? g.__e0e1BattleAssist.timingPreview() : [];
      case 'dismiss-startup': return staticScripts.dismissStartup();
      case 'season-insight': {
        if(!['history','ranks','reports','replay','replay_status','statistics','legion_roster','guard_count'].includes(args.op))throw Error('未知血月数据操作');
        return staticScripts.seasonInsight(args.op,args.args || {});
      }
      case 'legion-read': return staticScripts.legionRead(args.id);
      case 'legion-boss-read': return staticScripts.legionBossRead();
      case 'flag-upgrade-read': return staticScripts.flagUpgradeRead();
      case 'legion-scan': return staticScripts.legionScan(args.op,args.value);
      case 'damage-status': return typeof g.damageCurveStatus === 'function' ? g.damageCurveStatus() : null;
      case 'damage-snapshot': return typeof g.damageCurveJson === 'function' ? g.damageCurveJson(args.cursor) : null;
      case 'damage-debug': return typeof g.damageCurveDebug === 'function' ? g.damageCurveDebug() : null;
      case 'damage-reset': return typeof g.damageCurveReset === 'function' ? String(g.damageCurveReset()) : '采集脚本尚未注入';
      case 'treasure-inject': return staticScripts.treasure();
      case 'treasure-dump': return typeof g.dumpTreasureMap === 'function' ? g.dumpTreasureMap() : null;
      case 'treasure-overlay': {
        if(args.on && typeof g.treasureMapOverlayOn!=='function')await staticScripts.treasureOverlay();
        const fn = args.on ? g.treasureMapOverlayOn : g.treasureMapOverlayOff;
        return typeof fn === 'function' ? String(fn()) : '摸金脚本尚未注入';
      }
      case 'treasure-status': return typeof g.treasureMapOverlayStatus === 'function' ? String(g.treasureMapOverlayStatus()) : '摸金脚本尚未注入';
      case 'season-inject': return staticScripts.season();
      case 'season-call': {
        const allowed = ['reset','diagnose','stop','marks','flags','march','speedUp','candidates','attack','automationConfigure','automationEvents'];
        if (!allowed.includes(args.name)) throw new Error('不支持的血月命令');
        const api = g.e0e1Season;
        return api && typeof api[args.name] === 'function' ? api[args.name](args.payload || {})
          : {ok:false,status:'unavailable',message:'血月脚本尚未注入'};
      }
      default: throw new Error('不支持的抖音结构化命令');
    }
  }
  async function poll() {
    try {
      acknowledgeResponse();
      if (transfer && Date.now() - transfer.at > 120000) {
        const id = transfer.id; transfer = null; clearResponse();
        write('response',{token,runtime,id,ok:false,error:'回执分块传输等待超时，操作不会重发'});
      }
    } catch(e) {
      const id = transfer && transfer.id; transfer = null; clearResponse();
      lastError = errorText(e);
      try { write('response',{token,runtime,id,ok:false,error:'回执传输失败（用户目录空间不足或文件写入异常），操作不会重发: '+lastError}); } catch(_) {}
    }
    if (busy || transfer) return;
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
      if(stopped && !['install','idle','damage-stop','perf-stop'].includes(command.action) &&
         !(command.action==='call' && ['stop','home','restore','inspect','capture'].includes((command.args || {}).op)))
        throw Error('插件已停止，拒绝新业务操作');
      response = {token, runtime, id: command.id, ok: true, value: await dispatch(command.action, command.args)};
    } catch (e) {
      response = {token, runtime, id: command.id, ok: false, error: errorText(e)};
    }
    try { publishResponse(response); }
    catch (e) {
      transfer = null; clearResponse();
      lastError = errorText(e);
      try { write('response', {token, runtime, id: command.id, ok: false, error: '回执序列化或写入失败: ' + lastError}); } catch (_) {}
    } finally { busy = false; heartbeat(); }
  }
  g.__e0e1DouyinBridge = {runtime, build, stop() { stopped = true;releaseReserve();transfer=null;clearResponse();releaseKeepAlive();if(g.__e0e1BattleAssist)g.__e0e1BattleAssist.destroy();if(g.__e0e1AutomationOverlay)g.__e0e1AutomationOverlay.destroy();
    try {if(typeof g.tt.offHide==='function')g.tt.offHide(onHide);if(typeof g.tt.offShow==='function')g.tt.offShow(onShow);
      if(screenWrapper && g.tt.setKeepScreenOn===screenWrapper)g.tt.setKeepScreenOn=screenOriginal;} catch (_) {}
    clearInterval(tick);clearInterval(transferPump);clearInterval(pulse);clearInterval(replay); }};
  const pulse = setInterval(heartbeat, 500);
  const tick = setInterval(function () {
    if (!busy) poll().catch(e => {lastError = errorText(e); heartbeat();});
  }, 100);
  // Large reports use a fast acknowledgement pump only while transferring.
  // Idle command polling stays at 100ms; no extra filesystem I/O when idle.
  const transferPump = setInterval(function () {
    if (transfer && !busy) poll().catch(e=>{lastError=errorText(e);heartbeat();});
  }, 10);
  let stressStarted = false;
  async function storageStress() {
    const request=read('storage-stress-request');
    if(stressStarted || !request || request.token!==token || !Number.isFinite(request.at) ||
       Date.now()-request.at<0 || Date.now()-request.at>3600000){busy=false;return;}
    stressStarted=true;
    const paths=[], report={id:request.id,runtime,target_bytes:200*1024*1024,filled_bytes:0,
      quota_reached:false,recovered:false,cleaned_files:0,remaining_files:[]};
    let size=256*1024;
    try {
      storageCC=await g.System.import('cc');
      if(!storageCC.assetManager || !storageCC.assetManager.cacheManager)throw Error('缓存管理器未就绪');
      // First remove only our own abandoned stress files from an earlier crash.
      for(const name of fs.readdirSync(g.tt.env.USER_DATA_PATH)) {
        if(/^e0e1-storage-stress-[a-z0-9-]+-\d+\.tmp$/.test(name)) {
          try{fs.unlinkSync(g.tt.env.USER_DATA_PATH+'/'+name);}catch(_){}
        }
      }
      const usage=(dir,depth)=>{
        if(depth>12)throw Error('测试目录层级过深');
        let total=0;
        for(const name of fs.readdirSync(dir)) {
          if(typeof name!=='string'||name.includes('/')||name.includes('\\')||name==='.'||name==='..')continue;
          const result=fs.statSync(dir+'/'+name), stat=result.stats||result;
          total+=stat.isDirectory()?usage(dir+'/'+name,depth+1):stat.size;
        }
        return total;
      };
      report.initial_bytes=usage(g.tt.env.USER_DATA_PATH,0);
      stressFilling=true;
      while(report.initial_bytes+report.filled_bytes<report.target_bytes) {
        size=Math.min(size,report.target_bytes-report.initial_bytes-report.filled_bytes);
        const path=g.tt.env.USER_DATA_PATH+'/e0e1-storage-stress-'+runtime+'-'+paths.length+'.tmp';
        paths.push(path);
        try {
          fs.writeFileSync(path,'x'.repeat(size),'utf8');report.filled_bytes+=size;
          await new Promise(resolve=>setTimeout(resolve,0));
        } catch(e) {
          if(!String(e).includes('size limit exceeded'))throw e;
          report.quota_reached=true;report.boundary_error=errorText(e);
          if(size>1024){size=Math.max(1024,Math.floor(size/2));continue;}
          break;
        }
      }
      stressFilling=false;
      const before=storageCleanup.bytes;
      // At most 1023 bytes remain: this write must exercise quota recovery.
      write('storage-stress-check',{id:request.id,payload:'x'.repeat(8192)});
      report.recovered=storageCleanup.bytes>before;
      report.reclaimed_bytes=storageCleanup.bytes-before;
      report.check_written=true;
    }catch(e){report.error=errorText(e);}
    finally {
      stressFilling=false;
      for(const path of paths){try{fs.unlinkSync(path);report.cleaned_files++;}catch(_){try{if(fileSize(path)>0)report.remaining_files.push(path);}catch(_) {}}}
      try{fs.unlinkSync(prefix+'storage-stress-check.json');}catch(_){}
      try{write('storage-stress-result',report);}catch(e){lastError=errorText(e);}
      busy=false;heartbeat();
    }
  }
  const replay = setInterval(function () {
    if (g.UIManager && g.System && !busy) {
      clearInterval(replay);
      busy = true;
      const stress=read('storage-stress-request');
      if(stress && stress.token===token && stress.id && (!read('storage-stress-result') || read('storage-stress-result').id!==stress.id)) {
        storageStress().catch(e=>{lastError=errorText(e);busy=false;});return;
      }
      const config = read('persistent');
      const replayDamage = config && config.token === token && config.damage === true;
      Promise.resolve(replayDamage ? enableDamage() : null).catch(e => {lastError = errorText(e);}).finally(() => {busy = false; heartbeat();});
    }
  }, 250);
  heartbeat();
})(globalThis);
