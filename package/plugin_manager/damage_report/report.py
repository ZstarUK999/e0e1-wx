"""HTML 报告渲染与落盘。"""

from __future__ import annotations

import json
from pathlib import Path

from .serialize import render_csv, slim
from .template import HTML_TEMPLATE

# ── HTML ──

def build_html(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("</", "<\/")   # 防止 </script> 提前闭合
    return HTML_TEMPLATE.replace("__PAYLOAD__", blob)


# ── 落盘 ──

def write_outputs(data: dict, out_dir: Path, stamp: str, *, save_json: bool = True,
                  write_csv: bool = False, keep_events: bool = True) -> list[Path]:
    """把一份数据写成 JSON / CSV / HTML，返回写出的文件列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if save_json:
        path = out_dir / f"damage_curve_{stamp}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    if write_csv:
        path = out_dir / f"damage_curve_{stamp}.csv"
        path.write_text(render_csv(data), encoding="utf-8")
        written.append(path)
    path = out_dir / f"damage_curve_{stamp}.html"
    path.write_text(build_html(slim(data, keep_events)), encoding="utf-8")
    written.append(path)
    return written


def describe(data: dict) -> list[str]:
    """给人看的几行摘要，GUI 和 CLI 都用它。"""
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

