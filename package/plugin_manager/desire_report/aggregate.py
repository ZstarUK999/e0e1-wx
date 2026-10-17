"""三尸合成日志 → 报告载荷。纯数据，方便单测。"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

# DesireType 的六个子类型归到 UI 上的三种（贪/嗔/痴）；心与凡不能互合，但统计上同属一种。
TYPE_KIND = {1: 1, 4: 1, 2: 2, 5: 2, 3: 3, 6: 3}
KIND_NAMES = {1: '贪', 2: '嗔', 3: '痴'}
TYPE_NAMES = {1: '贪·心', 2: '嗔·心', 3: '痴·心', 4: '贪·凡', 5: '嗔·凡', 6: '痴·凡'}


def _int(value, default=0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _float(value):
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def load_records(path: Path) -> list[dict]:
    """读 CSV 日志；坏行跳过，不因为一行坏数据就让整份报告打不开。"""
    if not Path(path).exists():
        return []
    rows = []
    with Path(path).open(encoding='utf-8', newline='') as file:
        for raw in csv.DictReader(file):
            try:
                rows.append({'seq': _int(raw.get('seq')), 'batch': _int(raw.get('batch')),
                             'ts': str(raw.get('time') or ''), 'type': _int(raw.get('type')),
                             'kind': TYPE_KIND.get(_int(raw.get('type')), 0),
                             'quality': _int(raw.get('quality')),
                             'quality_name': str(raw.get('quality_name') or ''),
                             'ok': 1 if _int(raw.get('success')) == 1 else 0,
                             'ratio': _float(raw.get('ratio')),
                             'same_uuid': _int(raw.get('same_uuid'))})
            except (TypeError, ValueError):
                continue
    rows.sort(key=lambda row: (row['seq'], row['ts']))
    return rows


def batches_of(records: list[dict]) -> list[dict]:
    """批次列表：从记录反推，不额外维护状态文件。序号对外的文案是「第x次」。"""
    order: list[int] = []
    grouped: dict[int, list[dict]] = {}
    for row in records:
        if row['batch'] not in grouped:
            grouped[row['batch']] = []
            order.append(row['batch'])
        grouped[row['batch']].append(row)
    out = []
    for batch in sorted(order):
        rows = sorted(grouped[batch], key=lambda r: (r['seq'], r['ts']))
        out.append({'batch': batch, 'started_at': rows[0]['ts'], 'ended_at': rows[-1]['ts'],
                    'count': len(rows)})
    return out


def failure_gaps(records: list[dict]) -> tuple[list[int], int]:
    """连续失败次数：每次成功结束一段，段内是这段之前的失败次数。

    末尾还没被成功终结的那一段是不完整观测，单独返回、不进分布。
    """
    gaps: list[int] = []
    run = 0
    for row in records:
        if row['ok']:
            gaps.append(run)
            run = 0
        else:
            run += 1
    return gaps, run


def summarize(records: list[dict]) -> dict:
    total = len(records)
    ok = sum(1 for row in records if row['ok'])
    gaps, trailing = failure_gaps(records)
    return {'n': total, 'ok': ok, 'fail': total - ok,
            'rate': (ok / total) if total else 0.0,
            'gaps': len(gaps), 'avg_gap': (sum(gaps) / len(gaps)) if gaps else 0.0,
            'max_gap': max(gaps) if gaps else 0, 'trailing': trailing}


def build_payload(path: Path, expected_rate: float = 30.0) -> dict:
    records = load_records(path)
    qualities: dict[int, str] = {}
    cfg_ratio: dict[int, float] = {}
    for row in records:
        if row['quality_name']:
            qualities[row['quality']] = row['quality_name']
        if row['ratio'] is not None and row['quality'] not in cfg_ratio:
            cfg_ratio[row['quality']] = row['ratio']
    return {'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'log_path': str(Path(path).resolve()),
            'records': records,
            'batches': batches_of(records),
            'kinds': [{'id': key, 'name': KIND_NAMES[key]} for key in sorted(KIND_NAMES)],
            'types': [{'id': key, 'name': TYPE_NAMES[key]} for key in sorted(TYPE_NAMES)],
            'qualities': [{'id': key, 'name': qualities[key]} for key in sorted(qualities)],
            'cfg_ratio': {str(key): value for key, value in sorted(cfg_ratio.items())},
            'expected_rate': float(expected_rate),
            'summary': summarize(records)}
