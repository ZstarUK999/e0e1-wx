"""血月战场：战旗探测（只读）、自动加速、自动攻击、隐匿状态标注。

四条共同边界（与 血月调查与插件设计.md 一致）：
  1. 加速与挑战只点正常按钮，保留冷却、最小剩余时间、道具与状态限制；
  2. 请求没有明确回执就是 uncertain，停止本轮自动动作，不重试不重放；
  3. 被游戏拒绝（rejected）就停下并写明原因，不换目标绕开限制；
  4. 不读取被隐藏的敌方隐匿行军，隐匿目标不作为自动攻击的选敌来源。
"""

from __future__ import annotations

import asyncio
import logging
import json
import time
from datetime import datetime

LOG = logging.getLogger('plugin_manager')
_DECISION_LOG = {}


def _decision(name: str, payload: dict) -> None:
    """分支依据变化即记 INFO；相同依据每 30 秒留一次心跳。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    now = time.monotonic()
    previous = _DECISION_LOG.get(name)
    if previous is None or previous[0] != encoded or now - previous[1] >= 30:
        LOG.info('血月决策 %s %s', name, encoded)
        _DECISION_LOG[name] = (encoded, now)

ATTACK_PROBE_SECONDS = 2     # 挑战后核对状态同步的间隔
ATTACK_SYNC_TIMEOUT = 60     # 多久还没进入战斗就当服务端没确认，停止本轮

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
        self._next_speed = 0.0
        self._next_attack = 0.0
        self._marks = None
        self._next_mark_check = 0.0
        self._lock = asyncio.Lock()
        self._speed_stopped = ''       # 加速停止原因（空表示可以继续）
        self._attack_stopped = ''      # 攻击停止原因
        self._attack_wait_until = 0.0  # 上一场结束后等待到什么时候
        self._attack_pending = False   # 已发起挑战，等服务端把状态同步成战斗
        self._attack_seen_battle = False
        self._attack_since = 0.0
        self._battles = 0
        self._snapshot = None

    # ── 面板入口 ──

    def request(self, op: str, args: dict | None = None) -> None:
        if self.state.closing or not self.state.installed:
            self.panel.set_message('血月功能需要游戏与插件就绪')
            return
        asyncio.create_task(self.handle(op, args or {}))

    async def handle(self, op: str, args: dict) -> None:
        LOG.info('血月面板操作：op=%s args=%r injected=%s stopped=(%r,%r) pending=%s battles=%s', op, args, self._injected, self._speed_stopped, self._attack_stopped, self._attack_pending, self._battles)
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
        self._speed_stopped = self._attack_stopped = ''
        self._attack_pending = False
        self._attack_seen_battle = False
        self._attack_since = 0.0
        self._attack_wait_until = 0.0
        self._battles = 0

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
        self._speed_stopped = self._attack_stopped = ''
        self._attack_pending = False
        self._attack_seen_battle = False
        self._attack_since = 0.0
        self._attack_wait_until = 0.0
        self._battles = 0
        self._snapshot = None
        self.panel.set_probe_running(False)

    # ── 每秒轮询 ──

    async def poll(self, config: dict) -> None:
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
                    await self.transport.season_call('stop')
                except Exception as exc:
                    LOG.exception('停止血月脚本失败：%s', exc)
                self._injected = False
                self._marks = None
            return
        try:
            await self._ensure_injected()
            await self._sync_marks(bloodmoon)
            if self._probing and time.monotonic() >= self._next_probe:
                interval = max(1, int((bloodmoon.get('flag_probe') or {}).get('refresh_seconds') or 5))
                self._next_probe = time.monotonic() + interval
                await self.probe_once()
            if self._lock.locked():
                return
            async with self._lock:
                await self._poll_speed(bloodmoon)
                await self._poll_attack(bloodmoon)
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
            LOG.info('隐匿标注：%s receipt=%r', '开启（仅原本可见的单位）' if on else '关闭', result)
        if on and time.monotonic() >= self._next_mark_check:
            self._next_mark_check = time.monotonic() + 30
            info = await self.transport.season_call('diagnose')
            LOG.info('血月标注定时诊断：%r', info)
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
        return {'name': member.get('name') or ('#' + str(member.get('roleId'))),
                'power': SeasonFeature._short(member.get('power')),
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

    # ── 自动加速 ──

    async def _poll_speed(self, bloodmoon: dict) -> None:
        speed = bloodmoon.get('speed_up') or {}
        _decision('speed', {'config': speed, 'stopped': self._speed_stopped, 'due': time.monotonic() >= self._next_speed})
        if not speed.get('enabled'):
            self.panel.set_speed_status('未启用' + (f'；保留停止状态：{self._speed_stopped}' if self._speed_stopped else ''))
            return
        if self._speed_stopped:
            return
        if time.monotonic() < self._next_speed:
            return
        self._next_speed = time.monotonic() + max(1, int(speed.get('poll_seconds') or 2))
        state = await self.transport.season_call('march')
        _decision('march_snapshot', {'snapshot': state})
        if not isinstance(state, dict) or not state.get('ok'):
            LOG.warning('行军状态读取失败：%r', state)
            result = state if isinstance(state, dict) else {}
            self.panel.set_speed_status(f"读取行军状态失败：{result.get('message') or '未知原因'}")
            return
        move = state.get('move')
        info = state.get('speed_up') or {}
        if not move:
            self.panel.set_speed_status('当前没有行军，等待下一次行军')
            return
        times = int(info.get('times') or 0)
        limit = int(speed.get('max_times') or 0)
        remain = max(0, int(move.get('remain_ms') or 0)) // 1000
        if limit and times >= limit:
            LOG.debug('自动加速等待：达到行军上限 times=%s limit=%s remain=%s', times, limit, remain)
            self.panel.set_speed_status(f"已达到本次行军上限 {limit} 次，剩余 {remain} 秒不再加速")
            return
        if not info.get('available'):
            reason = '；'.join(info.get('reasons') or []) or '当前不可加速'
            LOG.debug('自动加速等待：%s remain=%s', reason, remain)
            self.panel.set_speed_status(f"等待合法时机：{reason}（剩余 {remain} 秒）")
            return
        LOG.info('准备行军加速：times=%s limit=%s remain=%s margin=%s', times, limit, remain, speed.get('safety_margin_seconds') or 0)
        try:
            receipt = await self.transport.season_call('speedUp', {'safety_margin_seconds': speed.get('safety_margin_seconds') or 0, 'max_times': limit})
        except Exception as exc:
            LOG.exception('行军加速传输失败，停止自动加速')
            receipt = {'ok': False, 'status': 'uncertain', 'message': f'加速回执未取得：{exc}'}
        LOG.info('行军加速回执：%r', receipt)
        if not isinstance(receipt, dict) or receipt.get('ok') is not True or receipt.get('confirmed') is not True:
            result = receipt if isinstance(receipt, dict) else {}
            status = result.get('status') or 'uncertain'
            message = result.get('message') or '未取得明确成功回执'
            if status == 'uncertain':
                self._speed_stopped = message
                LOG.error('加速结果未知，停止本次行军的自动加速：%s', message)
                self.panel.set_speed_status(f"结果未知，已停止：{message}（可在面板点复位后继续）")
            else:
                self._speed_stopped = message
                LOG.info('加速被拒绝，停止本次行军自动加速：%s', message)
                self.panel.set_speed_status(f"已停止：{message}")
            return
        LOG.info('行军加速成功：第%s次，剩余约%s秒', receipt.get('times'), remain)
        self.panel.set_speed_status(f"已加速 {receipt.get('times')} 次（上限 {limit or '不限'}），等待冷却")

    # ── 自动攻击 ──

    async def _poll_attack(self, bloodmoon: dict) -> None:
        attack = bloodmoon.get('attack') or {}
        _decision('attack', {'config': attack, 'stopped': self._attack_stopped, 'pending': self._attack_pending, 'seen_battle': self._attack_seen_battle, 'since': self._attack_since, 'battles': self._battles, 'due': time.monotonic() >= self._attack_wait_until, 'sync_expired': bool(self._attack_since and time.monotonic() - self._attack_since > ATTACK_SYNC_TIMEOUT), 'sync_timeout': ATTACK_SYNC_TIMEOUT, 'probe_seconds': ATTACK_PROBE_SECONDS})
        if not attack.get('enabled'):
            self.panel.set_attack_status('未启用' + (f'；保留停止状态：{self._attack_stopped}' if self._attack_stopped else ''))
            return
        if self._attack_stopped:
            return
        if time.monotonic() < self._attack_wait_until:
            return
        wait = max(0, int(attack.get('wait_seconds') or 0))
        self._attack_wait_until = time.monotonic() + max(1, wait)
        snapshot = await self.transport.season_call('candidates')
        _decision('candidate_snapshot', {'snapshot': snapshot})
        if not isinstance(snapshot, dict) or not snapshot.get('ok'):
            LOG.warning('节点队列读取失败：%r', snapshot)
            result = snapshot if isinstance(snapshot, dict) else {}
            self.panel.set_attack_status(f"读取节点队列失败：{result.get('message') or '未知原因'}")
            return
        state = snapshot.get('self_state')
        if self._attack_pending:
            LOG.debug('挑战同步决策：self_state=%r state_name=%r elapsed=%s timeout=%s wait=%s', state, snapshot.get('self_state_name'), time.monotonic() - self._attack_since, ATTACK_SYNC_TIMEOUT, wait)
            # 只有明确战斗状态确认进入；缺失/行军都不能代替确认。
            if state == 3:
                self._attack_pending = False
                self._attack_seen_battle = True
                self._attack_wait_until = time.monotonic() + ATTACK_PROBE_SECONDS
                self.panel.set_attack_status(f"战斗中（{snapshot.get('self_state_name') or state}），结束后再选目标")
                return
            if time.monotonic() - self._attack_since > ATTACK_SYNC_TIMEOUT:
                self._attack_stopped = f'发起挑战后未观察到战斗状态，当前状态={state!r}，服务端未确认进入战斗'
                LOG.error(self._attack_stopped)
                self.panel.set_attack_status(f"已停止：{self._attack_stopped}")
                return
            self.panel.set_attack_status('已发起挑战，等待服务端同步战斗状态')
            self._attack_wait_until = time.monotonic() + ATTACK_PROBE_SECONDS
            return
        if state == 3:
            self._attack_seen_battle = True
            self._attack_wait_until = time.monotonic() + ATTACK_PROBE_SECONDS
            self.panel.set_attack_status('战斗中，等待结束后计时')
            return
        if self._attack_seen_battle:
            if state != 1:
                self.panel.set_attack_status(f"等待战斗结束的待命确认（当前 {snapshot.get('self_state_name') or state}）")
                self._attack_wait_until = time.monotonic() + ATTACK_PROBE_SECONDS
                return
            self._attack_seen_battle = False
            self._attack_wait_until = time.monotonic() + wait
            LOG.info('战斗结束已确认：wait_seconds=%s wait_until=%s', wait, self._attack_wait_until)
            self.panel.set_attack_status(f'战斗结束，等待 {wait} 秒后选敌')
            if wait > 0:
                return
        if state != 1:
            self.panel.set_attack_status(f"等待战斗/行军结束（当前 {snapshot.get('self_state_name') or state}）")
            return
        limit = int(attack.get('max_battles') or 0)
        if limit and self._battles >= limit:
            self._attack_stopped = f"已达到单轮上限 {limit} 场"
            LOG.info('自动攻击停止：%s', self._attack_stopped)
            self.panel.set_attack_status(self._attack_stopped)
            return
        target = self._pick(snapshot, attack)
        if target is None:
            LOG.debug('自动攻击未选到目标：mine=%s ratio=%s absolute=%s reason=%s', snapshot.get('self_plan_power') or snapshot.get('self_power'), attack.get('power_ratio'), attack.get('power_limit'), self._no_target_reason(snapshot, attack))
            self.panel.set_attack_status(self._no_target_reason(snapshot, attack))
            return
        LOG.info('准备挑战：roleId=%s power=%s mine=%s ratio=%s absolute=%s battles=%s limit=%s', target['roleId'], target.get('planPower') or target.get('power'), snapshot.get('self_plan_power') or snapshot.get('self_power'), attack.get('power_ratio'), attack.get('power_limit'), self._battles, limit)
        try:
            receipt = await self.transport.season_call('attack', {'roleId': target['roleId'], 'power_ratio': int(attack.get('power_ratio') or 100), 'power_limit': int(attack.get('power_limit') or 0)})
        except Exception as exc:
            LOG.exception('挑战传输失败，停止自动攻击：roleId=%s', target['roleId'])
            receipt = {'ok': False, 'status': 'uncertain', 'message': f'挑战回执未取得：{exc}'}
        LOG.info('挑战回执：roleId=%s receipt=%r', target['roleId'], receipt)
        if not isinstance(receipt, dict) or receipt.get('ok') is not True or receipt.get('confirmed') is not True:
            result = receipt if isinstance(receipt, dict) else {}
            status = result.get('status') or 'uncertain'
            message = result.get('message') or '未取得明确成功回执'
            self._attack_stopped = message
            LOG.error('挑战未成功，停止自动攻击：%s（%s）', message, status)
            self.panel.set_attack_status(f"已停止：{message}")
            return
        self._battles += 1
        self._attack_pending = True
        self._attack_since = time.monotonic()
        self._attack_wait_until = time.monotonic() + ATTACK_PROBE_SECONDS
        LOG.info('已发起挑战：%s（战力 %s）第%s场', receipt.get('name') or target['roleId'], target.get('power'), self._battles)
        self.panel.set_attack_status(f"已挑战 {receipt.get('name') or target['roleId']}（第{self._battles}场），等待战斗状态同步")

    @staticmethod
    def _pick(snapshot: dict, attack: dict):
        """挑一个能打、战力够低的目标：战力最高的那个（打得过里最强的）。"""
        mine = int(snapshot.get('self_plan_power') or snapshot.get('self_power') or 0)
        if mine <= 0:
            LOG.debug('选敌停止：self_plan_power=%r self_power=%r effective_mine=%s', snapshot.get('self_plan_power'), snapshot.get('self_power'), mine)
            return None
        ratio = int(attack.get('power_ratio') or 100)
        absolute = int(attack.get('power_limit') or 0)
        ceiling = mine * ratio // 100 if mine > 0 else 0
        if absolute and (ceiling <= 0 or absolute < ceiling):
            ceiling = absolute
        _decision('target_threshold', {'mine': mine, 'ratio': ratio, 'absolute': absolute, 'ceiling': ceiling})
        if ceiling <= 0:
            return None
        best = None
        for row in list(snapshot.get('attack') or []) + list(snapshot.get('defense') or []):
            _decision('target_' + str(row.get('roleId')), {'roleId': row.get('roleId'), 'attackable': row.get('attackable'), 'planPower': row.get('planPower'), 'power': row.get('power'), 'reasons': row.get('reasons'), 'ceiling': ceiling})
            if not row.get('attackable'):
                continue
            power = int(row.get('planPower') or row.get('power') or 0)
            if power <= 0:
                continue
            if ceiling and power >= ceiling:
                continue
            if best is None or power > int(best.get('planPower') or best.get('power') or 0):
                best = row
        _decision('target_selected', {'target': best})
        return best

    @staticmethod
    def _no_target_reason(snapshot: dict, attack: dict) -> str:
        rows = list(snapshot.get('attack') or []) + list(snapshot.get('defense') or [])
        if not rows:
            return '当前节点没有可见的其他玩家'
        mine = int(snapshot.get('self_plan_power') or snapshot.get('self_power') or 0)
        ratio = int(attack.get('power_ratio') or 100)
        if mine <= 0:
            return '我方战力尚未可靠读取，暂停选敌'
        ceiling = mine * ratio // 100
        absolute = int(attack.get('power_limit') or 0)
        if absolute:
            ceiling = min(ceiling, absolute)
        blocked = [r for r in rows if not r.get('attackable')]
        too_strong = [r for r in rows if r.get('attackable')
                      and int(r.get('planPower') or r.get('power') or 0) >= ceiling]
        unknown = [r for r in rows if r.get('attackable')
                   and int(r.get('planPower') or r.get('power') or 0) <= 0]
        if not blocked and not too_strong and not unknown:
            return '当前节点没有可见的其他玩家'
        bits = []
        if unknown:
            bits.append(f"{len(unknown)} 人战力尚未可靠读取")
        if too_strong:
            bits.append(f"{len(too_strong)} 人战力不低于阈值")
        if blocked:
            reasons = {}
            for row in blocked:
                for reason in row.get('reasons') or []:
                    reasons[reason] = reasons.get(reason, 0) + 1
            bits.append('、'.join(f"{k}×{v}" for k, v in reasons.items()))
        return '无可挑战目标：' + '；'.join(bits)
