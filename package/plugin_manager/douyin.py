"""Douyin cache injection and a session-bound local filesystem transport.

The existing feature scripts/resident are reused. This is not a CDP endpoint.
Only the selected app's root game.js and our own mailbox files are changed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import time
import uuid

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from .transport import PluginTransport, ContextDestroyed
from package.js_injection.runtime_toggle import (
    build_runtime_toggle_disable_expression, build_runtime_toggle_enable_expression,
)
from package.daily_tasks.scheduler import ExecutionUncertain, RetryableTaskError

APPID = 'tt310e47b3ae06acc002'
MARKER = b'/* e0e1-douyin-plugin-bridge-v1 */'
LOG = logging.getLogger('plugin_manager.douyin')
ANCHOR = re.compile(rb'(__tt_define__\("game\.js",\(function\([^)]*\)\{"use strict";)')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    # A simultaneous platform read can briefly hold the destination on Windows.
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(.01)


def douyin_ready():
    for process in psutil.process_iter(['name']):
        try:
            if str(process.info['name']).lower() == 'douyin.exe':
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


class DouyinCache:
    def __init__(self, settings_dir, cache_root=None):
        self.settings = Path(settings_dir) / 'douyin-bridge'
        self.root = Path(cache_root) if cache_root else Path(os.environ['APPDATA']) / 'douyin/microGameCache'
        self.user = self.root / APPID / 'user'
        self.settings.mkdir(parents=True, exist_ok=True)
        token_path = self.settings / 'token.json'
        if token_path.exists():
            self.token = json.loads(token_path.read_text(encoding='utf-8'))['token']
        else:
            self.token = secrets.token_hex(32)
            atomic_json(token_path, {'token': self.token})
        self.build = ''
        self.version = ''
        self._last_status = None
        self._diagnostic_key = None
        self._next_diagnostic = 0.0

    def mailbox(self, name):
        return self.user / f'e0e1-plugin-{name}.json'

    def compiled_source(self):
        # Embed original scripts as literal functions; never compile JS at runtime.
        manager = Path(__file__).resolve().parent
        package = manager.parent
        scripts = package.parent / 'tools/js'
        core = '\n'.join((package/'daily_tasks'/name).read_text(encoding='utf-8-sig')
                         for name in ('daily_runtime.js','sweep_runtime.js'))
        core += '\n' + (manager/'desire_runtime.js').read_text(encoding='utf-8-sig')
        core += '\n' + (manager/'automation_overlay.js').read_text(encoding='utf-8-sig')
        core += '\n' + (manager/'pve_assist_overlay.js').read_text(encoding='utf-8-sig')
        core += '\n' + (manager/'battle_assist_runtime.js').read_text(encoding='utf-8-sig')
        resident = core + r'''
if (g.__e0e1PluginRuntime) return {resident_id:g.__e0e1PluginRuntime.id,capabilities:['energy']};
const api=createEnergyRuntime(g);
g.__e0e1AutomationOverlay=createAutomationOverlay(g);
g.__e0e1BattleAssist=createBattleAssistRuntime(g);
const resident={id,config:null,stopped:false,pending:false,async dispatch(op,args){
  if(op==='configure'){g.__e0e1GameOverlaysEnabled=!args.ui || args.ui.game_overlays!==false;await g.__e0e1BattleAssist.configure(args.battle_assist);this.config=args;return {status:'ok',value:true};}
  if(op==='stop'){g.__e0e1BattleAssist.destroy();g.__e0e1AutomationOverlay.destroy();this.stopped=true;return {status:'ok',value:true};}
  if(this.stopped&&!['inspect','capture','restore','home'].includes(op))return {status:'unavailable',message:'插件已停止'};
  if(this.pending)return {status:'uncertain',message:'上一条命令尚未结束'};
  this.pending=true;
  try{return await api.dispatch(op,args);}finally{this.pending=false;}
}};
g.__e0e1PluginRuntime=resident;
return {resident_id:id,capabilities:['energy']};
'''
        damage_path = scripts/'damage_curve_probe.js'
        script = {'id':hashlib.sha1(str(damage_path.resolve()).casefold().encode()).hexdigest(),
                  'name':damage_path.stem,'path':str(damage_path.resolve())}
        key = '__e0e1RuntimeToggle__'+script['id']
        damage = build_runtime_toggle_enable_expression(script, damage_path.read_text(encoding='utf-8-sig'),key)
        stop = build_runtime_toggle_disable_expression(key)
        def once(names):
            return 'async function(){' + '\n'.join('await (async function(){\n' +
                (scripts/name).read_text(encoding='utf-8-sig') + '\n})();' for name in names) + '\nreturn true;}'
        bundle = '{resident:function(id){\n'+resident+'\n},damageEnable:function(){return '+damage+'\n;},'+ \
                 'damageStop:function(){return '+stop+'\n;},perf:'+once(('runtime_perf_probe.js',))+',treasure:'+once(('treasure_map_dump.js','treasure_map_overlay.js'))+ \
                 ',season:'+once(('season_bloodmoon.js',))+',dismissStartup:function(){\n'+manager.joinpath('startup_cleanup.js').read_text(encoding='utf-8-sig')+'\nreturn dismissStartupPage(g);}}'
        template = manager.joinpath('douyin_bridge.js').read_text(encoding='utf-8')
        legion_source=manager.joinpath('legion_runtime.js').read_text(encoding='utf-8-sig')
        bundle=bundle[:-1]+',legionRead:async function(id){\n'+legion_source+'\nreturn readLegionPerspective(g,id);},legionScan:async function(op,value){\n'+legion_source+'\nif(op==="player")return scanLegionPlayer(g,value);if(op==="players")return scanLegionPlayers(g,value);if(op==="search")return searchScanLegion(g,value);throw Error("未知阴司扫描操作");}}'
        material = template.replace('__BRIDGE_STATIC_SCRIPTS__',bundle)
        self.build = sha((self.token+material).encode())
        return material.replace('__BRIDGE_TOKEN__',json.dumps(self.token)).replace('__BRIDGE_BUILD__',json.dumps(self.build))

    def prepare(self):
        packages = self.root / 'resource/packages' / APPID
        versions = [p for p in packages.iterdir() if p.is_dir() and re.fullmatch(r'\d+\.\d+\.\d+', p.name)] if packages.exists() else []
        if not versions:
            raise RuntimeError('未找到抖音游戏缓存，请先打开一次《遗弃之地》')
        folder = max(versions, key=lambda p: tuple(map(int, p.name.split('.'))))
        target = folder / 'game.js'
        # Resolve before write so a cache junction cannot redirect the patch elsewhere.
        if target.resolve().parent.parent != packages.resolve():
            raise RuntimeError('游戏缓存路径发生重定向，未写入')
        current = target.read_bytes()
        backup = self.settings / f'{folder.name}.original.js'
        receipt_path = self.settings / f'{folder.name}.patch.json'
        if MARKER in current:
            if not backup.exists() or not receipt_path.exists():
                raise RuntimeError('发现已有抖音补丁但缺少匹配备份，不覆盖')
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            original = backup.read_bytes()
            if sha(original) != receipt['original'] or sha(current) != receipt['patched']:
                raise RuntimeError('抖音缓存或备份已变化，不覆盖')
        else:
            if b'e0e1-douyin-factory-v1' in current:
                raise RuntimeError('请先恢复旧实验补丁，再使用插件管理器连接')
            original = current
        if len(ANCHOR.findall(original)) != 1:
            raise RuntimeError('游戏入口结构已变化，未注入；请更新适配')
        source = self.compiled_source()
        injection = MARKER + b'\n' + source.encode() + b'\n'
        patched = ANCHOR.sub(lambda match: match[1] + injection, original, count=1)
        changed = patched != current
        if changed:
            if backup.exists() and backup.read_bytes() != original:
                raise RuntimeError('该版本备份与当前原始文件不一致，不覆盖')
            backup.write_bytes(original)
            # Save recovery metadata first; after a failed write, verification refuses reuse.
            atomic_json(receipt_path, {'target': str(target), 'original': sha(original), 'patched': sha(patched)})
            target.write_bytes(patched)
            if sha(target.read_bytes()) != sha(patched):
                raise RuntimeError('抖音缓存写入后校验失败')
        previous_version = self.version
        self.version = folder.name
        if changed or previous_version != self.version:
            LOG.info('抖音缓存准备：版本=%s 修改=%s 入口=%s 备份=%s build=%s',
                     self.version,changed,target,backup,self.build[:12])
        return changed

    def status(self):
        try:
            value = json.loads(self.mailbox('state').read_text(encoding='utf-8-sig'))
            if (value.get('token') == self.token and value.get('build') == self.build
                    and value.get('appid') == APPID and value.get('protocol') == 'static-v1' and isinstance(value.get('runtime'), str)
                    and 0 <= time.time() * 1000 - value.get('at', 0) < 5000):
                self._last_status = value
                return value
        except (OSError, ValueError, TypeError):
            value = self._last_status
            if value and value.get('build') == self.build and 0 <= time.time() * 1000 - value.get('at', 0) < 5000:
                return value
        return None

    def log_diagnostics(self):
        """Read only allowlisted fields. Never log tokens, commands or battle data."""
        reason='ok';value={};path=self.mailbox('state')
        try:
            value=json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(value,dict):raise ValueError('state is not an object')
            age=time.time()*1000-float(value.get('at',0))
            if not math.isfinite(age):raise ValueError('invalid heartbeat timestamp')
            if value.get('token')!=self.token:reason='token_mismatch'
            elif value.get('build')!=self.build:reason='build_mismatch_need_reenter'
            elif value.get('appid')!=APPID:reason='appid_mismatch'
            elif value.get('protocol')!='static-v1':reason='protocol_mismatch'
            elif not 0<=age<5000:reason='stale_heartbeat'
        except (OSError,ValueError,TypeError) as exc:
            reason=type(exc).__name__;value={};age=None
        key=(reason,value.get('runtime'),value.get('resident'),value.get('phase'),value.get('game'),value.get('hall'))
        now=time.monotonic()
        if key==self._diagnostic_key and now<self._next_diagnostic:return
        self._diagnostic_key=key;self._next_diagnostic=now+60
        fields={k:value.get(k) for k in ('runtime','resident','phase','game','hall','busy','resident_stopped',
                'resident_pending','reusable','cleanup_pending','lastSequence')}
        fields.update(reason=reason,heartbeat_age_ms=round(age) if age is not None else None,
                      expected_build=self.build[:12],actual_build=str(value.get('build') or '')[:12],
                      cache_version=self.version,state_exists=path.exists())
        # Keep errors bounded; some SDK errors contain the full JS stack.
        fields['bridge_error']=str(value.get('error') or '')[:500]
        fields['cleanup_error']=str(value.get('cleanup_error') or '')[:300]
        fields['storage_reserve']=value.get('storage_reserve')
        fields['storage_cleanup']=value.get('storage_cleanup')
        LOG.info('抖音连接诊断：%s',json.dumps(fields,ensure_ascii=False))

    def restore(self):
        restored = []
        for path in self.settings.glob('*.patch.json'):
            receipt = json.loads(path.read_text(encoding='utf-8'))
            target = Path(receipt['target'])
            packages = (self.root / 'resource/packages' / APPID).resolve()
            if target.resolve().parent.parent != packages or target.name != 'game.js':
                raise RuntimeError('备份清单路径无效，不恢复')
            if not target.exists():
                continue  # The client may have removed an old version.
            original = path.with_name(path.name.replace('.patch.json', '.original.js')).read_bytes()
            current = sha(target.read_bytes())
            if sha(original) != receipt['original']:
                raise RuntimeError('原文件备份校验失败，不恢复')
            if current == receipt['original']:
                continue
            if current != receipt['patched']:
                raise RuntimeError('游戏文件已有其他修改，不恢复')
            target.write_bytes(original)
            if sha(target.read_bytes()) != receipt['original']:
                raise RuntimeError('恢复后校验失败')
            restored.append(str(target))
        return restored


class _LocalCommands:
    """Only adapt the existing expression builder's calls; no debugger is exposed."""
    def __init__(self, transport):
        self.transport = transport
        self.reconnect_task = None

    def on(self, *args):
        pass

    def is_connected(self):
        status = self.transport.cache.status()
        return bool(status and status['runtime'] == self.transport.runtime)

    async def connect(self, *args, **kwargs):
        await self.transport.connect(None)

    async def close(self):
        pass

    async def send(self, *args, **kwargs):
        raise RuntimeError('抖音使用结构化命令，不提供动态 JS / CDP 执行')


class DouyinTransport(PluginTransport):
    TARGET_APPID = APPID
    platform_name = '抖音 PC'
    shutdown_timeout = 4.0

    def __init__(self, cache):
        self.cache = cache
        self.runtime = None
        self._sequence = 0
        self._closing_requested = False
        self._detached = False
        self._pending_file = None
        self._file_lock = asyncio.Lock()
        self._logged_rpc = set()
        super().__init__(cdp=_LocalCommands(self))

    async def connect(self, port=None):
        status = self.cache.status()
        if not status:
            raise RuntimeError('等待抖音本地通道，请退出并重新进入小游戏')
        self.runtime = status['runtime']
        self.context_id = self.runtime
        self.connected = True

    async def _appid(self):
        return APPID if self.cdp.is_connected() else ''

    async def probe(self):
        status = self.cache.status()
        if not status:
            self.connected = False
            self.invalidate()
            return {'appid': '', 'ready': False, 'context_id': None, 'resident_id': None}
        if self.session_id and status.get('resident') == self.session_id and self.session_id in self._owned_ids:
            atomic_json(self.cache.mailbox('lease'), {'token': self.cache.token,
                        'runtime': status['runtime'], 'resident': self.session_id, 'at': time.time() * 1000})
        if self.runtime != status['runtime']:
            self.invalidate()
            self._logged_rpc.clear()
            self.runtime = status['runtime']
        self.connected = True
        self.context_id = self.runtime
        if status.get('resident') in self._owned_ids:
            self.session_id = status['resident']
        return {'appid': APPID, 'ready': bool(status.get('game') and status.get('hall')),
                'context_id': self.context_id, 'resident_id': status.get('resident'),
                'resident_stopped': status.get('resident_stopped'), 'reusable': status.get('reusable'),
                'message': '链路已连接，首次挂载请关闭游戏弹窗并返回大厅' if not status.get('hall') else ''}

    def begin_shutdown(self):
        """独立于命令队列通知游戏停止本实例；不重发或取消业务请求。"""
        self._closing_requested = True
        resident = self.session_id
        if not resident and self._pending_file and self._pending_file.get('action') == 'install':
            resident = self._pending_file.get('args', {}).get('id')
        if resident and self.runtime:
            atomic_json(self.cache.mailbox('shutdown'), {'token':self.cache.token, 'runtime':self.runtime, 'resident':resident})

    def detach_for_shutdown(self):
        """只停止本地等待，保留未确认命令记录，不代表远端操作已取消。"""
        self._detached = True
        self.connected = False
        self.invalidate()

    async def _reply(self, pending, timeout_ms=None):
        until = None if timeout_ms is None else time.monotonic() + timeout_ms / 1000
        next_notice = time.monotonic() + 5.0
        while True:
            if time.monotonic() >= next_notice:
                bridge=self.cache.status() or {}
                logging.getLogger('plugin_manager').warning(
                    '抖音命令仍在等待回执：action=%s id=%s bridge_phase=%s busy=%s cleanup=%s chunk=%s',
                    pending.get('action'),pending.get('id'),bridge.get('phase'),bridge.get('busy'),
                    bridge.get('cleanup_pending'),pending.get('_reply_ack'))
                next_notice = time.monotonic() + 10.0
            if self._detached:
                raise ContextDestroyed('插件已退出本地等待；远端操作结果未知，不重发')
            status = self.cache.status()
            if status and status['runtime'] != pending['runtime']:
                self._pending_file = None
                self._inflight = None
                self.invalidate()
                raise ContextDestroyed('抖音游戏上下文已重建，旧命令不重发')
            try:
                response = json.loads(self.cache.mailbox('response').read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                response = {}
            if (response.get('token') == self.cache.token and response.get('runtime') == pending['runtime']
                    and response.get('id') == pending['id']):
                if response.get('chunked') is True:
                    parts = pending.setdefault('_reply_parts', [])
                    index = response.get('index')
                    data = response.get('data')
                    if type(index) is not int or not isinstance(data, str) or index < 0 or index > len(parts):
                        raise RuntimeError('抖音回执分块序号无效，操作不会重发')
                    if index == len(parts):
                        parts.append(data)
                        pending['_reply_chars'] = pending.get('_reply_chars',0) + len(data)
                        # Timeout measures lack of progress, not total report size.
                        if timeout_ms is not None:
                            until = time.monotonic() + timeout_ms / 1000
                    elif parts[index] != data:
                        raise RuntimeError('抖音回执分块内容变化，操作不会重发')
                    if pending.get('_reply_ack') != index:
                        atomic_json(self.cache.mailbox('response-ack'), {
                            'token': self.cache.token, 'runtime': pending['runtime'],
                            'id': pending['id'], 'index': index})
                        pending['_reply_ack'] = index
                    if not response.get('final'):
                        if until is not None and time.monotonic() >= until:
                            raise asyncio.TimeoutError('抖音回执分块等待超时，操作不会重发')
                        await asyncio.sleep(.01)
                        continue
                    response = json.loads(''.join(parts))
                    if (response.get('token') != self.cache.token or response.get('runtime') != pending['runtime']
                            or response.get('id') != pending['id']):
                        raise RuntimeError('抖音分块回执身份不匹配，操作不会重发')
                    pending.pop('_reply_parts', None)
                    pending.pop('_reply_ack', None)
                else:
                    atomic_json(self.cache.mailbox('response-ack'), {
                        'token': self.cache.token, 'runtime': pending['runtime'], 'id': pending['id']})
                    pending.pop('_reply_parts', None)
                    pending.pop('_reply_ack', None)
                self._pending_file = None
                if not response.get('ok'):
                    raise RuntimeError(response.get('error') or '抖音脚本执行失败')
                return response.get('value')
            if until is not None and time.monotonic() >= until:
                raise asyncio.TimeoutError('抖音命令终态未确认，不会重发；请保持游戏运行')
            await asyncio.sleep(.05)

    async def automation_overlay(self, payload):
        # 与 heartbeat 共用状态文件，不进入可能正在等待业务回执的 _file_lock。
        status = self.cache.status()
        if not status or status.get('runtime') != self.runtime or status.get('resident') != self.session_id:
            return None
        atomic_json(self.cache.mailbox('automation'), {'token': self.cache.token,
                    'runtime': self.runtime, 'resident': self.session_id, 'at': time.time() * 1000, 'payload': payload})
        return status.get('automation')

    async def _evaluate(self, *args, **kwargs):
        raise RuntimeError('抖音静态通道不执行动态 JS')

    async def _rpc(self, action, args=None, timeout_ms=10000):
        async with self._file_lock:
            cleanup = action in ('idle', 'damage-stop', 'perf-stop') or (action == 'call' and (args or {}).get('op') == 'stop') or (action == 'season-call' and (args or {}).get('name') == 'stop')
            if self._detached or self._closing_requested and not cleanup:
                raise ContextDestroyed('插件正在退出，不再发送新操作')
            if self._pending_file:
                raise RuntimeError('前次抖音命令未确认，禁止发送新命令')
            if not self.cdp.is_connected():
                raise ContextDestroyed('抖音本地通道尚未连接或上下文已变化')
            self._sequence = max(self._sequence, (self.cache.status() or {}).get('lastSequence',0))+1
            command = {'token':self.cache.token,'runtime':self.runtime,'id':uuid.uuid4().hex,
                       'sequence':self._sequence,'action':action,'args':args or {},
                       'deadline':time.time()*1000+timeout_ms}
            key=(self.runtime,action,str((args or {}).get('op') or (args or {}).get('name') or ''))
            first=key not in self._logged_rpc
            self._logged_rpc.add(key)
            started=time.monotonic()
            if first:
                LOG.info('抖音命令开始：action=%s op=%s id=%s runtime=%s timeout_ms=%s',action,key[2],command['id'],self.runtime,timeout_ms)
            self._pending_file=command
            try:
                try:
                    atomic_json(self.cache.mailbox('command'),command)
                except (OSError,ValueError):
                    self._pending_file=None
                    raise
                result=await self._reply(command,timeout_ms)
                elapsed=time.monotonic()-started
                if first or elapsed>=1:
                    LOG.info('抖音命令完成：action=%s op=%s id=%s elapsed=%.3fs result_type=%s chunk_chars=%s',
                             action,key[2],command['id'],elapsed,type(result).__name__,command.get('_reply_chars',0))
                return result
            except Exception as exc:
                LOG.exception('抖音命令失败：action=%s op=%s id=%s elapsed=%.3fs error_type=%s',
                              action,key[2],command['id'],time.monotonic()-started,type(exc).__name__)
                self.cache.log_diagnostics()
                raise

    async def install(self):
        probe=await self.probe()
        if not probe['ready'] or probe['appid']!=APPID:
            raise RuntimeError('必须确认遗弃之地大厅就绪后才能注入')
        if probe['resident_id'] and probe['resident_id']!=self.session_id:
            if probe.get('reusable') is not True:
                raise RuntimeError('旧插件实例仍在运行或收尾，当前功能未就绪；请完全退出小游戏后重新进入')
            logging.getLogger('plugin_manager').info('旧抖音实例已停止且无在途操作，准备安全接管：%s',probe['resident_id'])
        async with self._lock:
            if self._inflight is not None:
                raise ExecutionUncertain('前次命令未确认，不安装新实例')
            generation=self._generation
            sid=self.session_id or uuid.uuid4().hex
            receipt=await self._rpc('install',{'id':sid})
            if await self._rpc('ping',timeout_ms=5000) != 2:
                raise RuntimeError('抖音插件挂载后健康检查无回执')
            if generation!=self._generation or not isinstance(receipt,dict) or receipt.get('resident_id')!=sid:
                raise RuntimeError('抖音驻留脚本安装回执不匹配')
            self.session_id=sid
            self._owned_ids.add(sid)
            await self.damage_stop()
            return sid

    async def call(self, op, payload=None):
        async with self._lock:
            if self._inflight is not None:
                raise ExecutionUncertain('上一条命令终态未经确认，禁止发送新命令')
            if not self.session_id or not self.cdp.is_connected():
                raise RuntimeError('当前抖音游戏会话尚未注入或已失效')
            generation=self._generation
            self._inflight={'id':self.session_id,'context':self.runtime}
            timeout=150000 if op in ('tomb_raid','tomb_targets','arena_challenge','free_summon') else (60000 if op.startswith('desire_compose_') or op=='pet_fodder_merge' else 30000)
            job=asyncio.create_task(self._rpc('call',{'id':self.session_id,'op':op,'payload':payload or {}},timeout))
            cancelled=False
            try:
                try:
                    receipt=await asyncio.shield(job)
                except asyncio.CancelledError:
                    cancelled=True
                    receipt=await asyncio.shield(job)
                if generation!=self._generation or not isinstance(receipt,dict):
                    raise ExecutionUncertain('抖音游戏回执失效，不重复操作')
                status=receipt.get('status')
                if status in ('ok','unavailable','rejected'):
                    self._inflight=None
                if status in ('unavailable','rejected'):
                    raise RetryableTaskError(receipt.get('message','游戏操作未获准'))
                if status!='ok':
                    raise ExecutionUncertain(receipt.get('message','游戏操作结果未知'))
                if cancelled:
                    raise asyncio.CancelledError
                return receipt.get('value')
            except (RuntimeError,asyncio.TimeoutError) as exc:
                if isinstance(exc,(ExecutionUncertain,RetryableTaskError)):
                    raise
                raise ExecutionUncertain(f'抖音命令已发出但未确认：{exc}') from exc

    async def wait_idle(self):
        if self._pending_file:
            try:
                await self._reply(self._pending_file)
            except ContextDestroyed:
                raise
            except RuntimeError:
                pass
        while self._inflight:
            pending=self._inflight
            state=await self._rpc('idle')
            if isinstance(state,dict) and (state.get('gone') or state.get('id')==pending['id'] and state.get('pending') is False):
                self._inflight=None
                return
            await asyncio.sleep(.2)

    async def damage_inject(self):
        result=await self._rpc('damage-inject',timeout_ms=20000)
        if not isinstance(result,dict) or not result.get('enabled'):
            raise RuntimeError('原伤害脚本未启用')
        self._damage_persistent='damage'
        return result

    async def damage_stop(self):
        result=await self._rpc('damage-stop')
        self._damage_persistent=''
        return result

    async def perf_start(self): return await self._rpc('perf-start')
    async def perf_snapshot(self): return await self._rpc('perf-status')
    async def perf_stop(self): return await self._rpc('perf-stop')
    async def battle_assist_timing(self): return await self._rpc('battle-assist-timing', timeout_ms=2000)
    async def dismiss_startup(self): return await self._rpc('dismiss-startup', timeout_ms=2000)
    async def legion_read(self, legion_id=None):
        return await self._rpc('legion-read', {'id':legion_id}, timeout_ms=8000)
    async def legion_scan_call(self, op, value=None):
        if op not in ('player','players','search'):raise ValueError('未知阴司扫描操作')
        return await self._rpc('legion-scan', {'op':op,'value':value}, timeout_ms=8000)

    async def damage_status(self): return await self._rpc('damage-status')
    async def damage_snapshot(self): return await self._rpc('damage-snapshot',timeout_ms=30000)
    async def damage_debug(self): return await self._rpc('damage-debug')
    async def damage_reset(self): return await self._rpc('damage-reset')
    async def treasure_inject(self): return await self._rpc('treasure-inject',timeout_ms=20000)
    async def treasure_dump(self): return await self._rpc('treasure-dump',timeout_ms=20000)
    async def treasure_overlay(self,on): return await self._rpc('treasure-overlay',{'on':bool(on)},timeout_ms=20000)
    async def treasure_status(self): return await self._rpc('treasure-status')
    async def season_inject(self): return await self._rpc('season-inject',timeout_ms=20000)
    async def season_call(self,name,payload=None): return await self._rpc('season-call',{'name':name,'payload':payload or {}},timeout_ms=30000)

    async def close(self):
        # Remove persistent damage registration and stop its current controller.
        if self._damage_persistent and self.connected and self.cdp.is_connected():
            await self.damage_stop()
        self.connected = False
        self.invalidate()


class DouyinService(QObject):
    state_changed = Signal(dict)
    player_id_changed = Signal(str)

    def __init__(self, cache, parent=None):
        super().__init__(parent)
        self.cache = cache
        self.error = ''
        self._next_prepare = 0
        self._last_player_id = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        if time.monotonic() >= self._next_prepare:
            try:
                self.cache.prepare()
                self.error = ''
            except Exception as exc:
                self.error = str(exc)
            self._next_prepare = time.monotonic() + 5
        self.cache.log_diagnostics()
        state = self.snapshot()
        self.state_changed.emit(state)
        player_id = str(state.get('player_id') or '')
        if player_id != self._last_player_id:
            self._last_player_id = player_id
            self.player_id_changed.emit(player_id)

    def snapshot(self):
        state = self.cache.status()
        return {'status': 'running' if state else 'waiting', 'owner_key': '1', 'miniapp': bool(state),
                'transport_ready': bool(state), 'transport_key': 'douyin-local', 'cdp_port': 0,
                'miniapp_epoch': state['runtime'] if state else None, 'error': self.error,
                'player_id': str(state.get('player_id') or '') if state else '',
                'message': self.error or ('抖音本地通道已连接' if state else '抖音缓存已准备，请退出并重新进入《遗弃之地》')}

    def start_debug(self, record):
        self._tick()
        self.timer.start()

    def shutdown(self, wait=False):
        self.timer.stop()

    def stop_debug(self):
        self.shutdown()
