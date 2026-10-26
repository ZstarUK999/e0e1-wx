"""HTML 报告渲染与落盘。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .serialize import render_csv, slim
from .buff_catalog import BUFF_CATALOG
from .template import HTML_TEMPLATE
from .analysis import analyze_recording

# ── HTML ──

def build_html(payload: dict) -> str:
    # 来源分散在双方属性快照、命中属性来源和BOSS状态中，统一收集参考ID。
    ids = set()

    def collect(value):
        if isinstance(value, dict):
            if "id" in value and ("piles" in value or "changes" in value):
                ids.add(str(value["id"]))
            for buff in value.get("targetBuffs", []):
                ids.add(str(buff.get("id")))
            for key, child in value.items():
                if key == "label" and isinstance(child, str):
                    ids.update(re.findall(r"Buff[： :]+(\d+)", child))
                elif key != "buffCatalog":
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for side in (payload, payload.get("other") or {}):
        collect(side.get("factorSources") or [])
    collect((payload.get("pvp") or {}).get("attrSeconds") or [])
    payload = dict(payload)
    payload["buffCatalog"] = {"version": BUFF_CATALOG["version"],
                              "buffs": {key: BUFF_CATALOG["buffs"][key]
                                        for key in sorted(ids) if key in BUFF_CATALOG["buffs"]}}
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("</", "<\/")   # 防止 </script> 提前闭合
    return HTML_TEMPLATE.replace("__PAYLOAD__", blob)


# ── 落盘 ──

def report_match_name(data: dict) -> str:
    players = {}
    for side in (data.get('self'), data.get('other'), data):
        if isinstance(side, dict) and side.get('players'):
            players = side['players']
            break

    def name(key: str, fallback: str) -> str:
        person = players.get(key) or {}
        value = str(person.get('name') or person.get('sName') or person.get('roleId') or fallback)
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:48].rstrip(' .')
        return value or fallback

    return f"{name('self', '我方')}vs{name('other', '敌方')}"


def write_outputs(data: dict, out_dir: Path, stamp: str, *, save_json: bool = True,
                  write_csv: bool = False, keep_events: bool = True, basename: str | None = None) -> list[Path]:
    """把一份数据写成 JSON / CSV / HTML，返回写出的文件列表。"""
    data=analyze_recording(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    stem = basename or f"{report_match_name(data)}_{stamp}"
    if basename is None:
        candidate, number = stem, 2
        while any((out_dir / f"{candidate}{suffix}").exists() for suffix in ('.json', '.csv', '.html')):
            candidate = f"{stem}_{number}"
            number += 1
        stem = candidate
    if save_json:
        path = out_dir / f"{stem}.json"
        path.write_text(json.dumps(data.get('rawRecording') or data, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    if write_csv:
        path = out_dir / f"{stem}.csv"
        path.write_text(render_csv(data), encoding="utf-8")
        written.append(path)
    path = out_dir / f"{stem}.html"
    path.write_text(build_html(slim(data, keep_events)), encoding="utf-8")
    written.append(path)
    return written


def describe(data: dict) -> list[str]:
    """给人看的几行摘要，GUI 和 CLI 都用它。"""
    data=analyze_recording(data)
    lines = []
    mode = data.get("mode") or "single"
    pvp = data.get("pvp")
    lines.append(f"模式：{mode}")
    if mode == "pvp" and pvp:
        lines.append(
            f"分数：我方 {pvp.get('finalSelfScore', 0):.1f} · 敌方 {pvp.get('finalOtherScore', 0):.1f}"
            f" · 胜利线 {pvp.get('winLine', 0)}"
            f" · 复算 我方 {pvp.get('derivedSelfScore', 0):.1f} / 敌方 {pvp.get('derivedOtherScore', 0):.1f}")
        if pvp.get('skipped'):
            lines.append("跳过：本场点了跳过战斗（好友切磋本地快进数据完整；其它 PVP 走服务端结算，曲线只到跳过那一刻）")
    for label, side in (("我方", data.get("self") or data), ("敌方", data.get("other"))):
        if not side:
            continue
        lines.append(f"{label}：事件 {side.get('eventCount')} 条 · 总伤害 {side.get('totalDamage')} "
                     f"· 天书 {len(side.get('books') or [])} 本 · 分支 {len(side.get('branches') or [])} 条")
    return lines

