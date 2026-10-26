"""摸金地图：注入采集脚本、导出地图文本、切换画面标注。"""

from __future__ import annotations

import asyncio
import logging
import time

LOG = logging.getLogger('plugin_manager')


class TreasureFeature:
    def __init__(self, transport, state, panel):
        self.transport = transport
        self.state = state
        self.panel = panel
        self._injected = False
        self._snapshot = None
        self._overlay = None
        self._next_dump = 0.0

    def request(self, op: str, args: dict | None = None) -> None:
        """面板按钮入口：未就绪直接回执，就绪则交给事件循环执行。"""
        if self.state.closing or not self.state.installed:
            self.panel.set_message('摸金功能需要游戏与插件就绪')
            return
        asyncio.create_task(self.handle(op, args or {}))

    async def handle(self, op: str, args: dict) -> None:
        try:
            await self._ensure_injected()
            if op == 'dump':
                dump = await self.transport.treasure_dump()
                if not dump:
                    self.panel.set_message('当前没有摸金地图数据（未进入摸金或数据未下发）')
                    return
                text, subject = self.render(dump)
                self._snapshot = text
                self.panel.set_map(text, subject)
                LOG.info('摸金地图已导出：%s', subject)
            elif op == 'overlay':
                message = await self.transport.treasure_overlay(bool(args.get('on')))
                self._overlay = bool(args.get('on'))
                LOG.info('摸金地图标注：%s', message)
                self.panel.set_message(str(message))
            else:
                message = await self.transport.treasure_status()
                self.panel.set_message(str(message))
        except Exception as exc:
            LOG.error('摸金操作失败：%s', exc)
            self.panel.set_message(f'摸金操作失败：{exc}')

    async def _ensure_injected(self) -> None:
        if self._injected:
            return
        await self.transport.treasure_inject()
        self._injected = True
        self._overlay = None  # 注入脚本会自行启动标注，必须显式同步开关。
        await self.transport.treasure_overlay(False)
        self._overlay = False
        LOG.info('摸金脚本已注入：地图导出与画面标注可用')

    def reset(self) -> None:
        """会话结束后丢弃注入标记，下次进入摸金重新注入。"""
        self._injected = False
        self._overlay = None

    @staticmethod
    def render(dump) -> tuple[str, str]:
        layers = dump.get('layers') if isinstance(dump, dict) else None
        if not isinstance(layers, list):
            return str(dump), '摸金地图（原始回执）'
        lines = []
        cells = 0
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            grid = layer.get('ascii') or []
            rows = layer.get('rows') or len(grid)
            cols = layer.get('cols') or (len(grid[0]) if grid else 0)
            cells += rows * cols
            lines.append(f"第{layer.get('layerId', '?')}层 {rows}×{cols}")
            for index, row in enumerate(grid):
                lines.append(f"x={index} | {row}")
        members = dump.get('members') if isinstance(dump, dict) else None
        if isinstance(members, list) and members:
            lines.append('成员：' + '、'.join(str(m.get('name') or m.get('roleId')) for m in members if isinstance(m, dict)))
        return '\n'.join(lines), f"摸金地图 · {len(layers)}层 / {cells}格"

    async def poll(self, config: dict) -> None:
        treasure = config.get('treasure', {})
        ready = self.state.installed and not self.state.closing
        self.panel.set_enabled(ready)
        if not ready:
            return
        if not treasure.get('enabled'):
            if self._injected and self._overlay is not False:
                try:
                    await self.transport.treasure_overlay(False)
                    self._overlay = False
                except Exception as exc:
                    LOG.warning('关闭摸金地图标注失败，下次继续清理：%s', exc)
            return
        try:
            await self._ensure_injected()
            if self._overlay is None or bool(treasure.get('overlay')) != self._overlay:
                message = await self.transport.treasure_overlay(bool(treasure.get('overlay')))
                self._overlay = bool(treasure.get('overlay'))
                LOG.info('摸金地图标注：%s', message)
            if treasure.get('auto_dump') and time.monotonic() >= self._next_dump:
                self._next_dump = time.monotonic() + treasure.get('refresh_seconds', 30)
                dump = await self.transport.treasure_dump()
                if dump:
                    text, subject = self.render(dump)
                    if text != self._snapshot:
                        self._snapshot = text
                        self.panel.set_map(text, subject)
                        LOG.info('摸金地图更新：%s', subject)
        except Exception as exc:
            LOG.error('摸金地图检查失败：%s', exc)
