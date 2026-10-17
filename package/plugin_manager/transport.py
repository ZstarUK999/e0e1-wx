"""正式插件内部CDP客户端，复用本机Devtools服务；没有HTTP调试桥。"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import uuid
from pathlib import Path

from package.mcp_control.cdp_client import LocalCdpClient
from package.daily_tasks.scheduler import ExecutionUncertain, RetryableTaskError
from package.js_injection.runtime_toggle import (
    disable_runtime_js_file,
    enable_runtime_js_file,
    remove_runtime_toggle_persistent_script,
)

LOG = logging.getLogger('plugin_manager.actions')
TARGET_APPID = 'wx6d5e82c174635a48'
LOCATION_PROBE = 'String(globalThis.location && globalThis.location.href || "")'
GAME_PROBE = '''(() => ({game: typeof UIManager !== 'undefined' && typeof ROLE !== 'undefined' && typeof System !== 'undefined', hall: !!(globalThis.UIManager && globalThis.CommonUICfgId && UIManager.ins.findOpen(CommonUICfgId.MainUI)), resident_id: globalThis.__e0e1PluginRuntime ? globalThis.__e0e1PluginRuntime.id : null}))()'''


class SessionCdpClient(LocalCdpClient):
    def _schedule_reconnect(self):
        # 正式插件由新会话判活驱动重连，不跨断线等待/重播未决操作。
        self.transient_disconnected = False
        self._fail_all_pending(RuntimeError('游戏CDP连接断开'))


class ContextDestroyed(RuntimeError):
    """CDP明确确认指定执行上下文不存在，而不是普通通信错误。"""


class _CdpBridge:
    """把 LocalCdpClient 适配成 runtime_toggle 需要的 bridge 接口。"""

    def __init__(self, cdp):
        self.cdp = cdp

    async def send_cdp_command(self, method, params=None, timeout=5.0):
        return await self.cdp.send(method, params or {}, timeout_ms=timeout * 1000)


class PluginTransport:
    TARGET_APPID = TARGET_APPID

    def __init__(self, cdp=None):
        self.cdp = cdp or SessionCdpClient(max_events=50)
        self.contexts = {}
        self.context_id = None
        self.session_id = None
        self._owned_ids = set()
        self._inflight = None
        self.port = None
        self.connected = False
        self._generation = 0
        self._damage_persistent = ""
        self._lock = asyncio.Lock()
        self.cdp.on('Runtime.executionContextCreated', self._created)
        self.cdp.on('Runtime.executionContextDestroyed', self._destroyed)
        self.cdp.on('Runtime.executionContextsCleared', self._cleared)
        self.cdp.on('Runtime.consoleAPICalled', self._console)

    def _console(self,event):
        params=event.get('params',{})
        if params.get('executionContextId') != self.context_id: return
        values=[arg.get('value') for arg in params.get('args',[]) if isinstance(arg,dict)]
        if not values or values[0] not in ('[plugin.ui]','[plugin.error]'): return
        text=' '.join(str(value) for value in values[1:])
        if values[0]=='[plugin.error]': LOG.error('%s',text)
        else: LOG.info('%s',text)

    def _created(self, event):
        ctx = event.get('params', {}).get('context', {})
        if type(ctx.get('id')) is int:
            self.contexts[ctx['id']] = ctx

    def _cleared(self, event):
        self._inflight = None
        self.invalidate()

    def _destroyed(self, event):
        cid = event.get('params', {}).get('executionContextId')
        if self._inflight and self._inflight['context'] == cid:
            self._inflight = None
        self.contexts.pop(cid, None)
        if cid == self.context_id:
            self.invalidate()

    def invalidate(self):
        self._generation += 1
        self.context_id = self.session_id = None
        self.contexts.clear()

    async def connect(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('CDP端口无效')
        await self.cdp.connect(f'ws://127.0.0.1:{port}', timeout_ms=3000)
        self.port = port
        self.connected = True
        await self.cdp.send('Runtime.enable', timeout_ms=2000)

    async def _evaluate(self, expression, context_id=None, timeout_ms=3000):
        params = {'expression': expression, 'returnByValue': True, 'awaitPromise': True}
        if context_id is not None:
            params['contextId'] = context_id
        try:
            response = await self.cdp.send('Runtime.evaluate', params, timeout_ms=timeout_ms)
        except RuntimeError as exc:
            try: details=json.loads(str(exc))
            except (ValueError,TypeError): details={}
            if details.get('code')==-32000 and details.get('message') in ('Cannot find context with specified id','Execution context was destroyed.'):
                raise ContextDestroyed(str(exc)) from exc
            raise
        root = response.get('result', {})
        if root.get('exceptionDetails'):
            raise RuntimeError(root['exceptionDetails'].get('text', '游戏JS执行异常'))
        return root.get('result', {}).get('value')

    async def _appid(self):
        href = await self._evaluate(LOCATION_PROBE)
        match = re.fullmatch(r'https://servicewechat\.com/(wx[0-9a-f]{16})/[^/?#]+/page-frame\.html(?:[?#].*)?', str(href))
        return match[1] if match else ''

    async def probe(self):
        async with self._lock:
            if not self.connected or not self.cdp.is_connected():
                self.connected = False
                self.invalidate()
                return {'appid': '', 'ready': False, 'context_id': None, 'resident_id': None}
            appid = await self._appid()
            if appid != TARGET_APPID:
                self.invalidate()
                return {'appid': appid, 'ready': False, 'context_id': None, 'resident_id': None}
            candidates = ([self.context_id] if self.context_id is not None else []) + list(self.contexts)
            if not self.contexts:
                candidates += list(range(1, 65))
            for cid in dict.fromkeys(candidates):
                try:
                    data = await self._evaluate(GAME_PROBE, cid, timeout_ms=200)
                except (RuntimeError, asyncio.TimeoutError):
                    if not self.cdp.is_connected():
                        raise
                    continue
                if isinstance(data, dict) and data.get('game'):
                    if self.context_id is not None and self.context_id != cid:
                        self.invalidate()
                    self.context_id = cid
                    if data.get('resident_id') in self._owned_ids:
                        self.session_id = data['resident_id']
                    return {'appid': appid, 'ready': bool(data.get('hall')), 'context_id': cid, 'resident_id': data.get('resident_id')}
            self.invalidate()
            return {'appid': appid, 'ready': False, 'context_id': None, 'resident_id': None}

    async def install(self):
        probe = await self.probe()
        if not probe['ready'] or probe['appid'] != TARGET_APPID:
            raise RuntimeError('必须确认遗弃之地大厅就绪后才能注入')
        if probe['resident_id'] and probe['resident_id'] != self.session_id:
            raise RuntimeError('此游戏上下文已有其他插件实例；请关闭旧实例并重启游戏')
        async with self._lock:
            if self.context_id is None or self.context_id != probe['context_id'] or not self.connected:
                raise RuntimeError('大厅探测后游戏上下文已失效，不注入')
            if self._inflight is not None:
                raise RuntimeError('前次JS终态未确认，不注入新实例')
            generation = self._generation
            sid = self.session_id or uuid.uuid4().hex
            scripts = Path(__file__).resolve().parents[1] / 'daily_tasks'
            desire_script = Path(__file__).resolve().parent / 'desire_runtime.js'
            source = (scripts.joinpath('daily_runtime.js').read_text(encoding='utf-8') + '\n'
                      + scripts.joinpath('sweep_runtime.js').read_text(encoding='utf-8') + '\n'
                      + desire_script.read_text(encoding='utf-8'))
            expression = f'''(() => {{
{source}
const id = {json.dumps(sid)};
if (globalThis.__e0e1PluginRuntime) return {{resident_id: globalThis.__e0e1PluginRuntime.id, capabilities:['energy']}};
const api = createEnergyRuntime(globalThis);
const resident = {{id, config: null, stopped:false, pending:false, async dispatch(op, args) {{
  if (op === 'configure') {{ this.config = args; return {{status:'ok', value:true}}; }}
  if (op === 'stop') {{ this.stopped = true; return {{status:'ok', value:true}}; }}
  if (this.stopped && !['inspect','capture','restore','home'].includes(op)) return {{status:'unavailable',message:'插件已停止'}};
  if (this.pending) return {{status:'uncertain',message:'上一条命令尚未结束'}};
  this.pending = true;
  try {{ return await api.dispatch(op, args); }} finally {{ this.pending=false; }}
}}}};
globalThis.__e0e1PluginRuntime = resident;
return {{resident_id:id, capabilities:['energy']}};
}})()'''
            receipt = await self._evaluate(expression, self.context_id, timeout_ms=5000)
            if generation != self._generation:
                raise RuntimeError('注入时游戏上下文发生变化，回执已丢弃')
            if not isinstance(receipt, dict) or receipt.get('resident_id') != sid:
                raise RuntimeError('自动注入回执不匹配')
            self.session_id = sid
            self._owned_ids.add(sid)
            return sid

    QUALITY_NAMES = {1: '白', 2: '蓝', 3: '紫', 4: '橙', 5: '红', 6: '黑金', 7: '幻彩', 8: '轮回'}
    TYPE_NAMES = {1: '贪·心', 2: '嗔·心', 3: '痴·心', 4: '贪·凡', 5: '嗔·凡', 6: '痴·凡'}

    @classmethod
    def _op_brief(cls, op, payload) -> str:
        """把请求参数压成一眼能读的几个字，别把整包 JSON 打进日志。"""
        payload = payload or {}
        if op == 'desire_compose_once':
            return (f"{cls.TYPE_NAMES.get(int(payload.get('type') or 0), '?')}·"
                    f"{cls.QUALITY_NAMES.get(int(payload.get('quality') or 0), '?')}")
        return ''

    @classmethod
    def _result_brief(cls, op, value) -> str:
        if not isinstance(value, dict):
            return ''
        if op == 'desire_compose_once':
            if value.get('success') is True:
                return '合成成功'
            if value.get('success') is False:
                return '合成失败'
            return '结果不明'
        if op == 'desire_bag_stats':
            return f"可合成分组 {len(value.get('groups') or [])} 项"
        if value.get('confirmed') is True:
            return '已确认'
        return ''

    async def call(self, op, payload=None):
        async with self._lock:
            if self._inflight is not None:
                raise ExecutionUncertain('上一条命令终态未经确认，禁止发送新命令')
            if not self.session_id or self.context_id is None or not self.connected:
                raise RuntimeError('当前游戏会话尚未注入或已经失效')
            generation = self._generation
            # 每次动作先核对实际目标；只读探针可以重试，用户动作绝不重发。
            if await self._appid() != TARGET_APPID:
                self.invalidate()
                raise RuntimeError('实际目标已变化，不执行插件命令')
            if generation != self._generation or self.context_id is None or self.session_id is None:
                raise RuntimeError('目标检查期间游戏上下文已失效，未发送操作')
            expression = ('globalThis.__e0e1PluginRuntime && (globalThis.__e0e1PluginRuntime.id === '
                          + json.dumps(self.session_id) + ' ? globalThis.__e0e1PluginRuntime.dispatch('
                          + json.dumps(op) + ', ' + json.dumps(payload or {}, ensure_ascii=False, allow_nan=False)
                          + ') : {status:"uncertain", message:"会话身份已改变"})')
            # 开始只在排查卡死时有用，放到 debug；完成那行带上结果，一次操作一行日志。
            LOG.debug('UI操作开始：%s %s',op,payload or {})
            self._inflight = {'id': self.session_id, 'context': self.context_id}
            # 盗掠扫描包含多轮列表刷新，与战斗同属长操作。
            # 三尸合成要等 spine 动画 + 确认框 + 奖励弹窗，30 秒会被误判成超时。
            if op in ('tomb_raid','tomb_targets','arena_challenge'):
                timeout=150000
            elif op in ('desire_compose_once','desire_compose_open','desire_compose_close'):
                timeout=60000
            else:
                timeout=30000
            job = asyncio.create_task(self._evaluate(expression, self.context_id, timeout_ms=timeout))
            cancelled = False
            try:
                try:
                    receipt = await asyncio.shield(job)
                except asyncio.CancelledError:
                    cancelled = True
                    receipt = await asyncio.shield(job)
                if generation != self._generation:
                    raise ExecutionUncertain('旧游戏上下文回执已失效，不应用到新会话')
                if not isinstance(receipt, dict):
                    raise ExecutionUncertain('插件回执缺失，不重复命令')
                status = receipt.get('status')
                if status in ('ok', 'unavailable', 'rejected'):
                    self._inflight = None
                if status in ('unavailable', 'rejected'):
                    LOG.error('UI操作未获准：%s，%s',op,receipt.get('message'))
                    raise RetryableTaskError(receipt.get('message', '操作未获准'))
                if status != 'ok':
                    LOG.error('UI操作结果未知：%s，%s',op,receipt.get('message'))
                    raise ExecutionUncertain(receipt.get('message', '操作结果未知'))
                if cancelled:
                    raise asyncio.CancelledError
                # 只读查询不进操作日志：它不产生副作用，按秒刷时只会淹没真正的信息。
                if op not in ('inspect','capture','quote','player_information','configure','identity',
                              'desire_bag_stats','desire_compose_probe'):
                    LOG.info('UI操作：%s %s → %s',op,self._op_brief(op,payload),self._result_brief(op,receipt.get('value')))
                return receipt.get('value')
            except (RuntimeError, asyncio.TimeoutError) as exc:
                LOG.error('UI命令错误：%s，%s',op,exc)
                if isinstance(exc, (ExecutionUncertain, RetryableTaskError)):
                    raise
                raise ExecutionUncertain(f'命令已发出但未确认：{exc}') from exc

    async def wait_idle(self):
        """只读等在途JS终态，不把CDP超时当作JS取消；未确认前不关服务。"""
        while self._inflight:
            pending = self._inflight
            if not self.cdp.is_connected() and self.port:
                # 只重连读取终态，不重放用户命令。
                try:
                    await self.cdp.connect(f'ws://127.0.0.1:{self.port}', timeout_ms=1000)
                    self.connected = True
                    await self.cdp.send('Runtime.enable',timeout_ms=1000)
                except Exception:
                    await asyncio.sleep(0.2)
                    continue
            expression = ('(() => {const r=globalThis.__e0e1PluginRuntime; const g=globalThis.__e0e1EnergyGuard;'
                          'return !r ? {gone:true} : {id:r.id,pending:!!(r.pending || g && (g.pending || g.action_pending || g.callback_count))};})()')
            try:
                state = await self._evaluate(expression, pending['context'], timeout_ms=1000)
                if isinstance(state, dict) and (state.get('gone') or state.get('id') == pending['id'] and state.get('pending') is False):
                    self._inflight = None
                    return
            except ContextDestroyed:
                if self._inflight is pending:
                    self._inflight = None
                return
            except (RuntimeError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(0.2)

    # ── 摸金地图：注入 tools/js 里已核对的脚本，并调用它们暴露的函数 ──
    TREASURE_SCRIPTS = ("treasure_map_dump.js", "treasure_map_overlay.js")

    async def treasure_inject(self):
        folder = Path(__file__).resolve().parents[2] / "tools" / "js"
        for name in self.TREASURE_SCRIPTS:
            source = folder.joinpath(name).read_text(encoding="utf-8")
            await self._evaluate(f"(async () => {{\n{source}\n}})()", self.context_id, timeout_ms=20000)
        return True

    async def treasure_dump(self):
        return await self._evaluate(
            '(() => {const fn = globalThis.dumpTreasureMap; '
            'return typeof fn === "function" ? fn() : null;})()', self.context_id, timeout_ms=20000)

    async def treasure_overlay(self, on: bool):
        name = "treasureMapOverlayOn" if on else "treasureMapOverlayOff"
        return await self._evaluate(
            f'(() => {{const g = globalThis; return typeof g.{name} === "function" ? String(g.{name}()) : "摸金脚本尚未注入";}})()',
            self.context_id, timeout_ms=20000)

    async def treasure_status(self):
        return await self._evaluate(
            '(() => {const g = globalThis; return typeof g.treasureMapOverlayStatus === "function" '
            '? String(g.treasureMapOverlayStatus()) : "摸金脚本尚未注入";})()', self.context_id, timeout_ms=10000)

    # ── 伤害曲线：持久注入 tools/js 里的采集脚本，并调用它暴露的函数 ──
    DAMAGE_SCRIPT = "damage_curve_probe.js"

    def _damage_script(self) -> dict:
        path = Path(__file__).resolve().parents[2] / "tools" / "js" / self.DAMAGE_SCRIPT
        return {
            "id": hashlib.sha1(str(path.resolve()).casefold().encode("utf-8")).hexdigest(),
            "name": path.stem,
            "path": str(path.resolve()),
        }

    async def damage_inject(self):
        """持久注入（每个新 document 自动重注）+ 立即在当前页启用。

        走的是 tools/cdp_inject.py --toggle 同一条路径，脚本自己每 500ms 找战斗 World 重挂，
        所以进战斗后即使 JS 上下文被重建也能重新采上。
        """
        bridge = _CdpBridge(self.cdp)
        result = await enable_runtime_js_file(bridge, self._damage_script())
        self._damage_persistent = result.get("persistent_identifier") or ""
        return result

    async def damage_stop(self):
        """取消长期脚本并清理后续页面的自动注册。"""
        bridge = _CdpBridge(self.cdp)
        try:
            result = await disable_runtime_js_file(bridge, self._damage_script(),
                                                   persistent_identifier=self._damage_persistent)
        except Exception:
            result = {"ok": True, "message": "已取消", "enabled": False}
        self._damage_persistent = ""
        return result

    async def damage_status(self):
        return await self._evaluate(
            '(() => {const g = globalThis; return typeof g.damageCurveStatus === "function" '
            '? g.damageCurveStatus() : "采集脚本尚未注入";})()', self.context_id, timeout_ms=10000)

    async def damage_snapshot(self):
        return await self._evaluate(
            '(() => {const g = globalThis; return typeof g.damageCurveJson === "function" '
            '? g.damageCurveJson() : null;})()', self.context_id, timeout_ms=30000)

    async def damage_debug(self):
        return await self._evaluate(
            '(() => {const g = globalThis; return typeof g.damageCurveDebug === "function" '
            '? g.damageCurveDebug() : null;})()', self.context_id, timeout_ms=10000)

    # ── 血月战场：注入 tools/js 里的只读/正常操作脚本，并调用它暴露的函数 ──
    SEASON_SCRIPTS = ("season_bloodmoon.js",)

    async def season_inject(self):
        folder = Path(__file__).resolve().parents[2] / "tools" / "js"
        for name in self.SEASON_SCRIPTS:
            source = folder.joinpath(name).read_text(encoding="utf-8")
            await self._evaluate(f"(async () => {{\n{source}\n}})()", self.context_id, timeout_ms=20000)
        return True

    async def season_call(self, name: str, payload: dict | None = None):
        """调用血月脚本里的函数；脚本没注入时返回统一的不可用回执。"""
        args = json.dumps(payload or {}, ensure_ascii=False, allow_nan=False)
        return await self._evaluate(
            '(() => {const a = globalThis.e0e1Season; if (!a || typeof a.' + name + ' !== "function") '
            'return {ok:false, status:"unavailable", message:"血月脚本尚未注入"}; '
            'return a.' + name + '(' + args + ');})()', self.context_id, timeout_ms=30000)

    async def damage_reset(self):
        return await self._evaluate(
            '(() => {const g = globalThis; return typeof g.damageCurveReset === "function" '
            '? String(g.damageCurveReset()) : "采集脚本尚未注入";})()', self.context_id, timeout_ms=10000)

    async def close(self):
        self.connected = False
        self.invalidate()
        task = getattr(self.cdp, 'reconnect_task', None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.cdp.close()
