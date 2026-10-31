"""血月战场：战旗探测、自动赶路、自动挑战、隐匿头像与行军路线显示。

当前运行规则：
  1. 赶路与挑战直接调用游戏接口；赶路间隔可调，剩余低于8秒停止；
  2. JS自主执行攻击与赶路循环；Python仅下发配置和读取低频摘要；
  3. 旧攻击的超时、拒绝、异常独立记录，不停止后续扫描或挑战；
  4. 隐匿显示使用客户端已同步数据；提前窗口允许请求，由服务端判定开战资格。
"""

from __future__ import annotations

import asyncio
import logging
import json
import time
import uuid
from datetime import datetime

LOG = logging.getLogger('plugin_manager')
_DECISION_LOG = {}


def _decision(name: str, payload: dict) -> None:
    """常规采样仅 DEBUG 且每类最多30秒一条；重要决策只在依据变化时记 INFO。"""
    routine = name in {'poll', 'marks', 'speed', 'attack', 'flags_snapshot',
                       'march_snapshot', 'candidate_snapshot'} or (
        name.startswith('target_') and name not in {'target_selected', 'target_threshold'})
    level = logging.DEBUG if routine else logging.INFO
    if not LOG.isEnabledFor(level):
        return
    now = time.monotonic()
    previous = _DECISION_LOG.get(name)
    if routine and previous is not None and now - previous[1] < 30:
        return
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    if routine or previous is None or previous[0] != encoded:
        LOG.log(level, '血月决策 %s %s', name, encoded)
        _DECISION_LOG[name] = (encoded, now)

SOURCE_TEXT = {
    'season_map': '战场同步数据（含战旗）',
    'preview_signup': '入场前报名名单（战旗未下发）',
    'none': '暂无可用数据源',
}


class SeasonFeature:
    def __init__(self, transport, state, panel, store):
        self.transport = transport
        self.state = state
        self.panel = panel
        self.store = store
        self._injected = False
        self._probing = False
        self._next_probe = 0.0
        self.scan_interval_ms = 1000
        self._marks = None
        self._next_mark_check = 0.0
        self._lock = asyncio.Lock()
        self._automation_lock = asyncio.Lock()
        self._automation_config = None
        self._controller_id = uuid.uuid4().hex
        self._event_stream = None
        self._event_cursor = 0
        self._next_events = 0.0
        self._config_task = None
        self._battles = 0
        self._snapshot = None
        self._config_epoch = 0
        self.store.changed.connect(self._configuration_changed)

    def _configuration_changed(self, _state) -> None:
        self._config_epoch += 1
        if self._injected and self.state.installed and not self.state.closing:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            if self._config_task is None or self._config_task.done():
                self._config_task = loop.create_task(self._push_configuration())

    async def _push_configuration(self) -> None:
        try:
            while self._injected and self.state.installed and not self.state.closing:
                epoch = self._config_epoch
                await self._sync_automation(self.store.snapshot().get('bloodmoon') or {})
                if epoch == self._config_epoch:
                    return
        except Exception as exc:
            LOG.warning('血月配置下发失败，下次重试：%s', exc)

    # ── 面板入口 ──

    def request(self, op: str, args: dict | None = None) -> None:
        if self.state.closing or not self.state.installed:
            self.panel.set_message('血月功能需要游戏与插件就绪')
            return
        asyncio.create_task(self.handle(op, args or {}))

    async def handle(self, op: str, args: dict) -> None:
        LOG.info('血月面板操作：op=%s args=%r injected=%s battles=%s', op,args,self._injected,self._battles)
        if op == 'probe' and args.get('on') and not (self.store.snapshot().get('bloodmoon') or {}).get('enabled'):
            LOG.info('血月探测未启动：总开关关闭 op=%s args=%r', op, args)
            self.panel.set_message('请先开启血月总开关，再开始战旗探测')
            return
        if op == 'reset':
            # 与动作共用锁；远端没有明确复位成功时保留停止标记。
            async with self._lock:
                try:
                    result = await self.transport.season_call('reset')
                    LOG.info('血月远程复位回执：%r', result)
                    if not isinstance(result, dict) or result.get('ok') is not True:
                        raise RuntimeError('未取得成功复位回执')
                except Exception as exc:
                    LOG.exception('复位血月脚本失败，保留停止状态：%s', exc)
                    self.panel.set_message(f'复位失败，保留停止状态：{exc}')
                    return
                self._reset_local()
                LOG.info('血月远程与本地复位成功')
                self.panel.set_message('已复位：清除结果未知状态与计数')
            return
        try:
            await self._ensure_injected()
            if op == 'probe':
                self.set_probing(bool(args.get('on')))
                if self._probing:
                    await self.probe_once()
            elif op == 'diagnose':
                info = await self.transport.season_call('diagnose')
                LOG.info('血月完整诊断：%r', info)
                self.panel.set_message(self._describe(info))
                LOG.info('血月诊断：%s', self._describe(info))
        except Exception as exc:
            LOG.exception('血月操作失败：op=%s，%s', op, exc)
            self.panel.set_message(f'血月操作失败：{exc}')

    def _reset_local(self) -> None:
        self._battles = 0
        self._automation_config = None
        self._next_events = 0.0

    def set_probing(self, on: bool) -> None:
        self._probing = bool(on)
        self.panel.set_probe_running(self._probing)
        if not self._probing:
            self._next_probe = 0.0

    async def _ensure_injected(self) -> None:
        if self._injected:
            return
        LOG.info('开始注入血月脚本')
        await self.transport.season_inject()
        self._injected = True
        LOG.info('血月脚本已注入：战旗探测/加速/挑战/隐匿状态标注可用')

    async def wait_operation(self) -> None:
        """关闭前等当前这一步走完，不打断在途的加速/挑战。"""
        async with self._lock:
            return

    def reset(self) -> None:
        """会话结束后丢弃注入标记与运行态。"""
        self._injected = False
        self._probing = False
        self._marks = None
        self._automation_config = None
        self._event_stream = None
        self._event_cursor = 0
        self._next_events = 0.0
        self._battles = 0
        self._snapshot = None
        self.panel.set_probe_running(False)

    # ── 每秒轮询 ──

    async def poll(self, config: dict) -> None:
        config_epoch = self._config_epoch
        bloodmoon = config.get('bloodmoon') or {}
        ready = self.state.installed and not self.state.closing
        _decision('poll', {'config': bloodmoon, 'installed': bool(self.state.installed), 'closing': self.state.closing, 'injected': self._injected, 'probing': self._probing, 'probe_due': time.monotonic() >= self._next_probe})
        self.panel.set_ready(ready)
        if not ready or not bloodmoon.get('enabled'):
            if not bloodmoon.get('enabled') and self._probing:
                LOG.info('血月总开关关闭：停止战旗探测，保留子功能设置')
                self.set_probing(False)
            if self._injected and not bloodmoon.get('enabled'):
                # 总开关关掉就顺手停掉标注，不在页面里继续跑
                try:
                    result = await self.transport.season_call('stop')
                    if not isinstance(result,dict) or result.get('ok') is not True:
                        raise RuntimeError('JS停止未确认')
                    LOG.info('血月JS循环及反隐已停止：总开关关闭')
                except Exception as exc:
                    LOG.exception('停止血月脚本失败：%s', exc)
                    return  # Retry cleanup while the switch remains off.
                self._injected = False
                self._automation_config = None
                self._marks = None
            return
        try:
            await self._ensure_injected()
            if self._lock.locked():
                return
            async with self._lock:
                if config_epoch != self._config_epoch or self.state.closing:
                    return
                await self._sync_automation(bloodmoon)
            if config_epoch != self._config_epoch or self.state.closing:
                return
            await self._sync_marks(bloodmoon)
            if self._probing and time.monotonic() >= self._next_probe:
                interval = max(1, int((bloodmoon.get('flag_probe') or {}).get('refresh_seconds') or 5))
                self._next_probe = time.monotonic() + interval
                await self.probe_once()
        except Exception as exc:
            LOG.exception('血月轮询失败：%s', exc)

    async def _sync_marks(self, bloodmoon: dict) -> None:
        on = bool((bloodmoon.get('stealth_mark') or {}).get('enabled'))
        _decision('marks', {'on': on, 'previous': self._marks})
        if on != self._marks:
            result = await self.transport.season_call('marks', {'on': on})
            if not isinstance(result, dict) or result.get('ok') is not True:
                LOG.error('隐匿状态标注设置失败：on=%s receipt=%r', on, result)
                return
            self._marks = on
            LOG.info('隐匿头像/行军路线显示：%s receipt=%r', '开启' if on else '关闭', result)
        if on and time.monotonic() >= self._next_mark_check:
            self._next_mark_check = time.monotonic() + 30
            info = await self.transport.season_call('diagnose')
            LOG.debug('血月标注定时诊断：%r', info)
            if isinstance(info, dict) and info.get('marks_enabled') is False:
                await self.transport.season_call('marks', {'on': True})
                LOG.info('已恢复脚本更新后停止的隐匿标注定时器')
            if isinstance(info, dict) and info.get('mark_error'):
                LOG.error('血月标注定时器异常：%r', info['mark_error'])

    # ── 战旗探测 ──

    async def probe_once(self) -> None:
        result = await self.transport.season_call('flags')
        _decision('flags_snapshot', {'snapshot': result})
        if not isinstance(result, dict):
            LOG.error('战旗读取返回无效类型：%r', result)
            return
        if not result.get('ok'):
            LOG.warning('战旗读取失败：%r', result)
            self.panel.set_flags([], f"读取失败：{result.get('message') or '未知原因'}")
            return
        groups = result.get('groups') or []
        rows = []
        for group in groups:
            members = sorted(group.get('members') or [], key=lambda m: -(m.get('power') or 0))
            rows.append({
                'title': f"{group.get('title') or '未命名阴司'}（{len(members)}人）",
                'power': self._short(group.get('power')),
                'members': [self._member_row(m) for m in members],
                'note': '',
                '_power': int(group.get('power') or 0),
            })
        rows.sort(key=lambda r: -r['_power'])
        source = result.get('source') or 'none'
        count = sum(len(r['members']) for r in rows)
        stamp = datetime.now().strftime('%H:%M:%S')
        subject = (f"{SOURCE_TEXT.get(source, source)} · {len(rows)}个阴司 / {count}人 · {stamp}"
                   + ('' if source == 'season_map' else '（战旗要等进入战场后才会下发）'))
        self.panel.set_flags(rows, subject)
        self._snapshot = result

    @staticmethod
    def _member_row(member: dict) -> dict:
        flag = member.get('flag') or '无'
        if member.get('flagLv'):
            flag = f"{flag} Lv{member['flagLv']}"
        notes = [n for n in (member.get('stateName') or '', member.get('note') or '') if n]
        if member.get('stealth'):
            notes.append('隐身中')
        for key, label in (('season_power', '赛季战力'), ('total_power', '综合战力')):
            if member.get(key) is not None:
                notes.append(label + '：' + SeasonFeature._short(member[key]))
        return {'name': member.get('name') or ('#' + str(member.get('roleId'))),
                '_power': int(member.get('power') or 0),
                'power': SeasonFeature._short(member['power']) if member.get('power') is not None else '未下发',
                'flag': flag, 'note': ' · '.join(notes)}

    @staticmethod
    def _short(value) -> str:
        number = int(value or 0)
        if number >= 100000000:
            return f"{number / 100000000:.2f}亿"
        if number >= 10000:
            return f"{number / 10000:.1f}万"
        return str(number)

    @staticmethod
    def _describe(info) -> str:
        if not isinstance(info, dict):
            return str(info)
        if not info.get('ok'):
            return f"诊断失败：{info.get('message') or '未知原因'}"
        me = info.get('self') or {}
        constants = info.get('constants') or {}
        return ('战场：{map}　模块：{module}　warId={war}　角色{roles}/阴司{legions}/节点{buildings}/行军{moves}\n'
                '自己：{name}（{state}）战旗 {flag}　位置 {pos}　报名数据 {bt}\n'
                '配置：MarchSpeed={speed} 加速CD={cd}s 最小剩余={min}s 道具={item} 提前入场={pre}分钟').format(
            map='已打开' if info.get('map_ui') else '未打开', module='已初始化' if info.get('module') else '未初始化',
            war=info.get('war_id') or '-', roles=info.get('roles'), legions=info.get('legions'),
            buildings=info.get('buildings'), moves=info.get('move_infos'),
            name=me.get('name') or '-', state=me.get('stateName') or '-', flag=me.get('flag') or '无',
            pos=('%s,%s' % (me['position']['x'], me['position']['y'])) if me.get('position') else '-',
            bt=info.get('preview_btime_count'), speed=constants.get('MarchSpeed'), cd=constants.get('MarchSpeedUpCD'),
            min=constants.get('MarchSpeedUpMinTime'), item=constants.get('MarchSpeedUpItem') or '-',
            pre=constants.get('PreEnterMinutes'))

    # JS runs both realtime loops. These calls carry configuration/events only.

    async def _sync_automation(self, bloodmoon: dict) -> None:
        epoch = self._config_epoch
        payload = {'enabled': bool(bloodmoon.get('enabled')),
                   'attack': dict(bloodmoon.get('attack') or {}),
                   'speed_up': dict(bloodmoon.get('speed_up') or {})}
        # Legacy display-only fields are not sent to the game loop.
        payload['attack'] = {k: payload['attack'][k] for k in
            ('enabled','lead_ms','dynamic_lead','interval_ms','power_limit','max_battles','lowest_power_first')
            if k in payload['attack']}
        payload['speed_up'] = {k: payload['speed_up'][k] for k in
            ('enabled','interval_seconds','max_times') if k in payload['speed_up']}
        key = json.dumps(payload, sort_keys=True)
        async with self._automation_lock:
            if epoch != self._config_epoch or self.state.closing:
                return
            if key != self._automation_config:
                result = await self.transport.season_call('automationConfigure',
                    dict(payload, controller=self._controller_id, revision=epoch, after_seq=self._event_cursor,stream_id=self._event_stream))
                if not isinstance(result, dict) or result.get('ok') is not True:
                    raise RuntimeError('JS自动循环配置未确认')
                if epoch != self._config_epoch:
                    return
                self._automation_config = key
                self._next_events = time.monotonic() + 1
                self._display_automation(result)
            elif time.monotonic() >= self._next_events:
                self._next_events = time.monotonic() + 1
                result = await self.transport.season_call('automationEvents', {'after_seq': self._event_cursor,'stream_id':self._event_stream})
                if epoch == self._config_epoch and isinstance(result, dict) and result.get('ok'):
                    self._display_automation(result)

    def _display_automation(self, result: dict) -> None:
        stream = result.get('stream_id')
        if stream is not None and stream != self._event_stream:
            self._event_stream = stream
            self._event_cursor = 0
        for event in result.get('events') or []:
            if int(event.get('seq') or 0) > self._event_cursor:
                level = {'DEBUG':logging.DEBUG,'INFO':logging.INFO,'WARNING':logging.WARNING,'ERROR':logging.ERROR}.get(event.get('level'),logging.INFO)
                LOG.log(level,'血月JS事件：%s game_at_ms=%s seq=%s %s',
                        event.get('kind'),event.get('at'),event.get('seq'),event.get('detail'))
        if result.get('dropped'):
            LOG.warning('血月事件缓冲已覆盖 %s 条较早事件', result['dropped'])
        self._event_cursor = int(result.get('cursor') or self._event_cursor)
        self._battles = int(result.get('battles') or 0)
        self.panel.set_attack_status(result.get('attack_status') or 'JS循环已配置')
        self.panel.set_speed_status(result.get('speed_status') or 'JS循环已配置')
        latency = result.get('attack_latency') or {}
        count = int(latency.get('sample_count') or 0)
        lead = int(result.get('effective_lead_ms') or 0)
        if count:
            self.panel.attack_latency_status.setText(
                f"RTT/2：{float(latency.get('mean_one_way_ms') or 0):.1f}ms；近10秒 {count} 个回包；实际提前量 {lead}ms")
        else:
            self.panel.attack_latency_status.setText(f'RTT/2：暂无回包样本；实际提前量 {lead}ms')
