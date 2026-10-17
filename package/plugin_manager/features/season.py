"""血月战场：战旗探测（只读）、自动加速、自动攻击、水旗标注。

四条共同边界（与 血月调查与插件设计.md 一致）：
  1. 加速与挑战只点正常按钮，保留冷却、最小剩余时间、道具与状态限制；
  2. 请求没有明确回执就是 uncertain，停止本轮自动动作，不重试不重放；
  3. 被游戏拒绝（rejected）就停下并写明原因，不换目标绕开限制；
  4. 不读取被隐藏的敌方隐匿行军，隐匿目标不作为自动攻击的选敌来源。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

LOG = logging.getLogger('plugin_manager')

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
        self._lock = asyncio.Lock()
        self._speed_stopped = ''       # 加速停止原因（空表示可以继续）
        self._attack_stopped = ''      # 攻击停止原因
        self._attack_wait_until = 0.0  # 上一场结束后等待到什么时候
        self._attack_pending = False   # 已发起挑战，等服务端把状态同步成战斗
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
        if op == 'reset':
            # 复位不依赖脚本有没有注入：本地的停止标记与计数先清掉。
            try:
                await self.transport.season_call('reset')
            except Exception as exc:
                LOG.warning('复位血月脚本失败：%s', exc)
            self._reset_local()
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
                self.panel.set_message(self._describe(info))
                LOG.info('血月诊断：%s', self._describe(info))
        except Exception as exc:
            LOG.error('血月操作失败：%s', exc)
            self.panel.set_message(f'血月操作失败：{exc}')

    def _reset_local(self) -> None:
        self._speed_stopped = self._attack_stopped = ''
        self._attack_pending = False
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
        await self.transport.season_inject()
        self._injected = True
        LOG.info('血月脚本已注入：战旗探测/加速/挑战/水旗标注可用')

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
        self._attack_since = 0.0
        self._attack_wait_until = 0.0
        self._battles = 0
        self._snapshot = None
        self.panel.set_probe_running(False)

    # ── 每秒轮询 ──

    async def poll(self, config: dict) -> None:
        bloodmoon = config.get('bloodmoon') or {}
        ready = self.state.installed and not self.state.closing
        self.panel.set_ready(ready)
        if not ready or not bloodmoon.get('enabled'):
            if self._injected and not bloodmoon.get('enabled'):
                # 总开关关掉就顺手停掉标注，不在页面里继续跑
                try:
                    await self.transport.season_call('stop')
                except Exception as exc:
                    LOG.warning('停止血月脚本失败：%s', exc)
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
            LOG.error('血月轮询失败：%s', exc)

    async def _sync_marks(self, bloodmoon: dict) -> None:
        on = bool((bloodmoon.get('stealth_mark') or {}).get('enabled'))
        if on != self._marks:
            await self.transport.season_call('marks', {'on': on})
            self._marks = on
            LOG.info('水旗标注：%s', '开启（仅原本可见的单位）' if on else '关闭')

    # ── 战旗探测 ──

    async def probe_once(self) -> None:
        result = await self.transport.season_call('flags')
        if not isinstance(result, dict):
            return
        if not result.get('ok'):
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
        if not speed.get('enabled'):
            if self._speed_stopped:
                self._speed_stopped = ''
                self.panel.set_speed_status('未启用')
            return
        if self._speed_stopped:
            return
        if time.monotonic() < self._next_speed:
            return
        self._next_speed = time.monotonic() + max(1, int(speed.get('poll_seconds') or 2))
        state = await self.transport.season_call('march')
        if not isinstance(state, dict) or not state.get('ok'):
            self.panel.set_speed_status(f"读取行军状态失败：{(state or {}).get('message') or '未知原因'}")
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
            self.panel.set_speed_status(f"已达到本次行军上限 {limit} 次，剩余 {remain} 秒不再加速")
            return
        if not info.get('available'):
            reason = '；'.join(info.get('reasons') or []) or '当前不可加速'
            self.panel.set_speed_status(f"等待合法时机：{reason}（剩余 {remain} 秒）")
            return
        receipt = await self.transport.season_call('speedUp', {'safety_margin_seconds': speed.get('safety_margin_seconds') or 0})
        if not isinstance(receipt, dict) or not receipt.get('ok'):
            status = (receipt or {}).get('status') or ''
            message = (receipt or {}).get('message') or '未知原因'
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
        if not attack.get('enabled'):
            if self._attack_stopped:
                self._attack_stopped = ''
                self._battles = 0
                self.panel.set_attack_status('未启用')
            return
        if self._attack_stopped:
            return
        if time.monotonic() < self._attack_wait_until:
            return
        wait = max(0, int(attack.get('wait_seconds') or 0))
        self._attack_wait_until = time.monotonic() + max(1, wait)
        snapshot = await self.transport.season_call('candidates')
        if not isinstance(snapshot, dict) or not snapshot.get('ok'):
            self.panel.set_attack_status(f"读取节点队列失败：{(snapshot or {}).get('message') or '未知原因'}")
            return
        state = snapshot.get('self_state')
        if self._attack_pending:
            # 挑战已发出：必须等到自己真的进入战斗（状态不再是待命），才允许再发下一场。
            if state != 1:
                self._attack_pending = False
                self._attack_wait_until = time.monotonic() + max(1, wait)
                self.panel.set_attack_status(f"战斗中（{snapshot.get('self_state_name') or state}），结束后再选目标")
                return
            if time.monotonic() - self._attack_since > ATTACK_SYNC_TIMEOUT:
                self._attack_stopped = '发起挑战后状态一直是待命，服务端未确认进入战斗'
                LOG.error(self._attack_stopped)
                self.panel.set_attack_status(f"已停止：{self._attack_stopped}")
                return
            self.panel.set_attack_status('已发起挑战，等待服务端同步战斗状态')
            self._attack_wait_until = time.monotonic() + ATTACK_PROBE_SECONDS
            return
        if state != 1:
            self.panel.set_attack_status(f"等待战斗/行军结束（当前 {snapshot.get('self_state_name') or state}）")
            return
        limit = int(attack.get('max_battles') or 0)
        if limit and self._battles >= limit:
            self._attack_stopped = f"已达到单轮上限 {limit} 场"
            self.panel.set_attack_status(self._attack_stopped)
            return
        target = self._pick(snapshot, attack)
        if target is None:
            self.panel.set_attack_status(self._no_target_reason(snapshot, attack))
            return
        receipt = await self.transport.season_call('attack', {'roleId': target['roleId']})
        if not isinstance(receipt, dict) or not receipt.get('ok'):
            status = (receipt or {}).get('status') or ''
            message = (receipt or {}).get('message') or '未知原因'
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
        ratio = int(attack.get('power_ratio') or 100)
        absolute = int(attack.get('power_limit') or 0)
        ceiling = mine * ratio // 100 if mine > 0 else 0
        if absolute and (ceiling <= 0 or absolute < ceiling):
            ceiling = absolute
        best = None
        for row in list(snapshot.get('attack') or []) + list(snapshot.get('defense') or []):
            if not row.get('attackable'):
                continue
            power = int(row.get('planPower') or row.get('power') or 0)
            if ceiling and power >= ceiling:
                continue
            if best is None or power > int(best.get('planPower') or best.get('power') or 0):
                best = row
        return best

    @staticmethod
    def _no_target_reason(snapshot: dict, attack: dict) -> str:
        rows = list(snapshot.get('attack') or []) + list(snapshot.get('defense') or [])
        if not rows:
            return '当前节点没有可见的其他玩家'
        mine = int(snapshot.get('self_plan_power') or snapshot.get('self_power') or 0)
        ratio = int(attack.get('power_ratio') or 100)
        blocked = [r for r in rows if not r.get('attackable')]
        too_strong = [r for r in rows if r.get('attackable')
                      and int(r.get('planPower') or r.get('power') or 0) >= (mine * ratio // 100 if mine else 0)]
        if not blocked and not too_strong:
            return '当前节点没有可见的其他玩家'
        bits = []
        if too_strong:
            bits.append(f"{len(too_strong)} 人战力不低于阈值")
        if blocked:
            reasons = {}
            for row in blocked:
                for reason in row.get('reasons') or []:
                    reasons[reason] = reasons.get(reason, 0) + 1
            bits.append('、'.join(f"{k}×{v}" for k, v in reasons.items()))
        return '无可挑战目标：' + '；'.join(bits)
