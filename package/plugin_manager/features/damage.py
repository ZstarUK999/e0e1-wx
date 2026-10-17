"""PVP／战斗伤害采集：注入采集脚本、按场采集快照、落盘 HTML 报告。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from ..damage_report import write_outputs

LOG = logging.getLogger('plugin_manager')

REPORT_DIR = Path('logs')

# 面板里展示的属性项：攻击/增伤/天书/法术爆伤/暴伤/PVP增减伤/最终PVP增伤/最终增减伤
# 'finalPvp' 是派生项：最终PVP增伤 = 本方PVP增伤(117) − 对方PVP减伤(118)
ATTR_PANEL_KEYS = (1, 104, 115, 107, 102, 117, 118, 'finalPvp', 123, 124)


class DamageFeature:
    def __init__(self, transport, state, panel, store):
        self.transport = transport
        self.state = state
        self.panel = panel
        self.store = store
        self._injected = False
        self._pending = None      # 当前（或刚结束）这一场最后一次快照
        self._last = None         # 最近一次取到的快照，仅用于展示
        self._battle_key = None   # 当前这一场的标识，变了就是新一场
        self._written = False     # 这一场的报告是否已经落盘
        self._report_path = None
        self._next_poll = 0.0

    # ── 面板操作 ──

    def request(self, op: str, args: dict | None = None) -> None:
        if self.state.closing or not self.state.installed:
            self.panel.message.setText('伤害采集需要游戏与插件就绪')
            return
        asyncio.create_task(self.handle(op, args or {}))

    async def handle(self, op: str, args: dict) -> None:
        try:
            await self._ensure_injected()
            if op == 'refresh':
                await self.take(force=True)
            elif op == 'debug':
                info = await self.transport.damage_debug()
                if not info:
                    self.panel.set_summary('采集脚本没有注入（damageCurveDebug 不存在）。'
                                           '请确认开关打开、脚本已注入，或重开小程序后重试。')
                else:
                    self.panel.set_summary(json.dumps(info, ensure_ascii=False, indent=2))
                self.panel.message.setText('诊断信息已显示在上方，可直接复制发给我')
            elif op == 'reset':
                message = await self.transport.damage_reset()
                self._last = None
                self._pending = None
                self._battle_key = None
                self._written = False
                self.panel.set_status(str(message))
                self.panel.set_summary('已清空，进入下一场 PVP 会重新开始采集')
            elif op == 'stop':
                message = await self.transport.damage_stop()
                self._injected = False
                self.panel.set_status('已停止采集')
                self.panel.message.setText(str(message))
        except Exception as exc:
            LOG.error('伤害采集操作失败：%s', exc)
            self.panel.message.setText(f'操作失败：{exc}')

    async def _ensure_injected(self) -> None:
        if self._injected:
            return
        result = await self.transport.damage_inject()
        self._injected = True
        LOG.info('伤害采集脚本已持久注入：%s', result.get('message') or '')

    # ── 每秒轮询 ──

    async def poll(self, config: dict) -> None:
        damage = config.get('damage') or {}
        ready = self.state.installed and not self.state.closing
        self.panel.set_ready(ready)
        if not ready:
            return
        if not damage.get('enabled'):
            if self._injected:
                # 关掉开关就顺手停掉，避免继续在页面里跑
                try:
                    await self.transport.damage_stop()
                except Exception as exc:
                    LOG.warning('停止伤害采集失败：%s', exc)
                self._injected = False
                self._pending = None
                self._battle_key = None
                self._written = False
                self.panel.set_status('未启用（打开开关后自动开始）')
                self.panel.set_hint('')
                self.panel.set_summary('')
            return
        if time.monotonic() < self._next_poll:
            return
        self._next_poll = time.monotonic() + 1.0
        try:
            await self._ensure_injected()
            await self.take()
        except Exception as exc:
            LOG.error('伤害采集检查失败：%s', exc)
            self.panel.set_status(f'采集检查失败：{exc}')

    async def take(self, *, force: bool = False) -> None:
        """取一次状态与快照：更新面板；战斗结束（没有 World 了）时落盘出报告。"""
        status = await self.transport.damage_status()
        hooked = int(status.get('hooked') or 0) if isinstance(status, dict) else 0

        if hooked <= 0:
            # 没有挂上任何 World：上一场已经结束，把它最后一次快照落盘
            if self._pending is not None and not self._written:
                self.write_report(self._pending, '本场')
                self._written = True
            detail = ''
            if isinstance(status, dict):
                hooked = int(status.get('hooked') or 0)
                detail = '' if hooked else '（未挂上任何 World）'
            self.panel.set_status(f'采集中 · 等待进入 PVP 对局{detail}')
            self.panel.set_hint(self.hint(self._pending or {}))
            return

        data = await self.transport.damage_snapshot()
        if not isinstance(data, dict) or not self._has_data(data):
            self.panel.set_status('采集中 · 等待伤害事件')
            return

        self._last = data
        key = self._battle_key_of(data)
        if key != self._battle_key:
            # 换了新的一场：先把上一场没落盘的补上，再开始记新的
            if self._pending is not None and not self._written:
                self.write_report(self._pending, '上一场')
            self._battle_key = key
            self._written = False
        self._pending = data

        self.panel.set_status(self.status_text(data))
        self.panel.set_hint(self.hint(data))
        self.panel.set_summary(self.summary(data))
        if force:
            self.write_report(data, '当前')
            self._written = True

    def write_report(self, data: dict, label: str) -> None:
        try:
            config = self.store.snapshot().get('damage') or {}
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            written = write_outputs(data, REPORT_DIR, stamp, save_json=True,
                                    write_csv=bool(config.get('auto_csv')), keep_events=True)
            html = next((p for p in written if p.suffix == '.html'), None)
            self._report_path = html
            self.panel.set_report_path(html)
            LOG.info('%s伤害报告已生成：%s', label, html)
        except OSError as exc:
            LOG.error('伤害报告写入失败：%s', exc)
            self.panel.message.setText(f'报告写入失败：{exc}')

    # ── 渲染 ──

    @staticmethod
    def _battle_key_of(data) -> tuple | None:
        """当前这一场的标识：变了说明是新一场（或上一场已结束）。"""
        for side in (data.get('self'), data.get('other')):
            if isinstance(side, dict) and side.get('instanceId') is not None:
                return (side.get('battleType'), side.get('seed'), side.get('instanceId'))
        return None

    @staticmethod
    def _has_data(data) -> bool:
        for side in (data.get('self'), data.get('other')):
            if isinstance(side, dict) and side.get('eventCount'):
                return True
        return bool(data.get('pvp'))

    @staticmethod
    def _battle_type_name(data) -> str:
        for source in (data.get('pvp'), data.get('self'), data.get('other')):
            if isinstance(source, dict) and source.get('battleTypeName'):
                return source['battleTypeName']
        for source in (data.get('pvp'), data.get('self'), data.get('other')):
            if isinstance(source, dict) and source.get('battleType') is not None:
                return f"类型{source['battleType']}"
        return "未知类型"

    def status_text(self, data) -> str:
        mode = data.get('mode') or 'single'
        pvp = data.get('pvp')
        name = self._battle_type_name(data)
        if mode == 'pvp' and pvp:
            text = (f"{name} · 我方 {pvp.get('finalSelfScore', 0):.1f} / "
                    f"敌方 {pvp.get('finalOtherScore', 0):.1f} · 胜利线 {pvp.get('winLine', 0)}")
            if pvp.get('skipped'):
                text += "（已跳过战斗）"
            return text
        side = data.get('self') or {}
        return f"{name} · 单世界采集 · 事件 {side.get('eventCount', 0)} 条（当前不是双分数 PVP）"

    def hint(self, data) -> str:
        """面板里那行提示：说清当前模式是不是受支持的那个、跳过会不会丢数据。"""
        pvp = data.get('pvp')
        if not pvp:
            return ("发起一场「好友切磋」即可自动采集。好友切磋是当前完整支持的模式："
                    "点「跳过战斗」也会在本地把整场跑完，数据完整。"
                    "斗法／血月／酆都决斗也能采，但它们的跳过走服务端结算，"
                    "本地不再补算，只能拿到跳过那一刻之前的部分。")
        if pvp.get('skipSafe'):
            return "好友切磋 · 已支持：可以正常打，也可以直接点「跳过战斗」，本地会把整场模拟跑完，数据完整。"
        name = pvp.get('battleTypeName') or self._battle_type_name(data)
        if pvp.get('skipped'):
            return (f"{name} · 已点跳过：非好友切磋的跳过走服务端结算，"
                    "本地不再补算，下面只有跳过之前的数据，最终分数来自服务端。")
        return (f"{name} · 可以采集，但请勿点「跳过战斗」：这类 PVP 的跳过走服务端结算，"
                "本地不再补算，会丢掉后续数据。")

    @staticmethod
    def _pct_text(value) -> str:
        """百分比属性存的是比率，×100 后显示：9.2518 → 925%；小于 10% 保留一位小数（0.006 → 0.6%）。"""
        pct = value * 100
        if abs(pct) >= 10:
            return f"{round(pct)}%"
        return f"{round(pct, 1)}%"

    def _render_attr_snapshot(self, pvp, lines):
        """面板里的双方属性快照（取最后一秒，完整曲线在 HTML 报告里看）。"""
        rows = pvp.get('attrSeconds') or []
        if not rows:
            return
        snap = rows[-1]
        # JSON 的对象 key 都是字符串，这里统一按字符串查（数字 key 也要转成 str）
        meta = {str(m.get('key')): m for m in (pvp.get('attrMeta') or [])}
        shown = 0
        for key in ATTR_PANEL_KEYS:
            key = str(key)
            m = meta.get(key) or {}
            a = (snap.get('self') or {}).get(key)
            b = (snap.get('other') or {}).get(key)
            if a is None and b is None:
                continue
            name = m.get('note') or m.get('label') or str(key)
            pct = bool(m.get('percent'))

            def fmt_one(v):
                if v is None:
                    return '—'
                if pct:
                    # 百分比属性存的是比率（2.135 = 213.5%），×100 后显示
                    return self._pct_text(v)
                return str(int(v))

            delta = None if (a is None or b is None) else a - b
            tail = '' if delta is None else f"（我方 {'+' if delta >= 0 else ''}{fmt_one(delta)}）"
            lines.append(f"   {name}\t我方 {fmt_one(a)} / 敌方 {fmt_one(b)}\t{tail}")
            shown += 1
        if shown:
            lines.append(f"   （第 {snap.get('sec')} 秒快照，逐秒变化与曲线见 HTML 报告）")
            lines.append('')

    def summary(self, data) -> str:
        """面板里的基础信息 + 双方拆解。"""
        lines = []
        pvp = data.get('pvp')
        if pvp:
            cfg = pvp.get('cfg') or {}
            lines.append(f"分数  我方 {pvp.get('finalSelfScore', 0):.1f} · "
                         f"敌方 {pvp.get('finalOtherScore', 0):.1f} · 胜利线 {pvp.get('winLine', 0)}")
            lines.append(f"复算  我方 {pvp.get('derivedSelfScore', 0):.1f} · "
                         f"敌方 {pvp.get('derivedOtherScore', 0):.1f}（应与上面一致）")
            lines.append(f"参数  PVPInitScore={cfg.get('PVPInitScore')} "
                         f"PVPInitVariable={cfg.get('PVPInitVariable')} "
                         f"PVPBaseBonus={cfg.get('PVPBaseBonus')} "
                         f"PVPLimitTime={cfg.get('PVPLimitTime')}")
            if pvp.get('skipped'):
                lines.append("跳过  本场点了跳过战斗"
                             + ("（好友切磋本地快进，模拟跑完整场，数据完整）"
                                if pvp.get('battleType') == 26 else
                                "（非好友切磋走服务端结算，本地不补算，曲线只到跳过那一刻）"))
            derived = pvp.get('derived') or []
            if derived:
                last = derived[-1]
                share = last.get('share')
                lines.append(f"当前  第{last.get('sec')}秒 我方伤害占比 "
                             f"{'%.1f%%' % (share * 100) if isinstance(share, (int, float)) else '-'}"
                             f" · 每秒满额 ±{last.get('weight', 0):.1f}")
            lines.append('')
            self._render_attr_snapshot(pvp, lines)
        players = (data.get('self') or {}).get('players')
        if players:
            for label, person in (('我方', players.get('self')), ('敌方', players.get('other'))):
                if not person:
                    continue
                bits = [str(person.get('name') or person.get('roleId') or '?')]
                if person.get('level') is not None:
                    bits.append(f"Lv{person['level']}")
                if person.get('fightPower') is not None:
                    bits.append(f"战力 {person['fightPower']}")
                lines.append(f"{label}  " + ' · '.join(bits))
                if person.get('books'):
                    lines.append('   天书：' + '、'.join(
                        f"{b.get('name')}{(' Lv%s' % b['level']) if b.get('level') else ''}"
                        for b in person['books']))
                if person.get('awakenings'):
                    lines.append('   觉醒：' + '、'.join(
                        f"{a.get('bookName')} {a.get('branchName')} Lv{a.get('level')}"
                        for a in person['awakenings']))
            lines.append('')
        for label, side in (('我方', data.get('self')), ('敌方', data.get('other'))):
            if not isinstance(side, dict):
                continue
            lines.append(f"── {label} · {side.get('battleTypeName') or ('类型' + str(side.get('battleType')))}"
                         f" · seed {side.get('seed')} · 时长 {side.get('duration', 0):.1f}s"
                         f" · 事件 {side.get('eventCount')} 条")
            lines.append(f"   总伤害 {side.get('totalDamage')} · 对敌方英雄 {side.get('bossDamage')}")
            total = side.get('totalDamage') or 0
            for cat in (side.get('categories') or []):
                pct = f"{cat['dmg'] / total * 100:.1f}%" if total else '-'
                lines.append(f"   {cat.get('label')}\t{cat.get('dmg')}\t{pct}")
            for book in (side.get('books') or []):
                pct = f"{book['dmg'] / total * 100:.1f}%" if total else '-'
                lines.append(f"   天书 {book.get('name')}\t{book.get('dmg')}\t{pct}")
                for branch in (book.get('branches') or []):
                    lines.append(f"     └ {branch.get('name')} Lv{branch.get('level')}"
                                 f"({branch.get('pathName')})\t{branch.get('dmg')}")
            for skill in (side.get('skills') or [])[:8]:
                lines.append(f"   技能 {skill.get('name')}\t{skill.get('origin') or '-'}\t{skill.get('dmg')}")
            zero = [a for a in (side.get('activeBranches') or []) if not a.get('dealtDamage')]
            if zero:
                lines.append('   已激活但零伤害的分支（只贡献属性加成或被更高阶覆盖）：')
                for item in zero:
                    lines.append(f"     · {item.get('bookName')} {item.get('branchName')} "
                                 f"Lv{item.get('level')} {item.get('pathName')}")
            lines.append('')
        return '\n'.join(lines).rstrip()
