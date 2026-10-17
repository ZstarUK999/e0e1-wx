"""三尸合成报告的渲染与落盘。"""

from __future__ import annotations

import json
from pathlib import Path

from .aggregate import build_payload
from .template import HTML_TEMPLATE


def build_html(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("</", "<\\/")   # 防止 </script> 提前闭合
    return HTML_TEMPLATE.replace("__PAYLOAD__", blob)


def write_outputs(log_path: Path, out_dir: Path, stamp: str, *,
                  expected_rate: float = 30.0, save_json: bool = False) -> list[Path]:
    """读日志生成 HTML（可选 JSON），返回写出的文件列表。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(log_path, expected_rate)
    written: list[Path] = []
    if save_json:
        path = out_dir / f"desire_compose_{stamp}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    path = out_dir / f"desire_compose_{stamp}.html"
    path.write_text(build_html(payload), encoding="utf-8")
    written.append(path)
    return written


def describe(payload: dict) -> list[str]:
    summary = payload.get("summary") or {}
    lines = [f"日志：{payload.get('log_path', '')}",
             f"合成 {summary.get('n', 0)} 次 · 成功 {summary.get('ok', 0)} 次 · "
             f"成功率 {(summary.get('rate') or 0) * 100:.1f}%",
             f"最长连续失败 {summary.get('max_gap', 0)} 次 · 平均 {summary.get('avg_gap', 0):.2f} 次"
             f"（末尾未结束的 {summary.get('trailing', 0)} 次不计入）"]
    return lines
