"""载荷压缩与 CSV：决定 HTML 报告里带哪些字段。"""

from __future__ import annotations

# ── 载荷压缩 ──

# 单侧数据里 HTML 需要的字段；原始事件只在需要时内嵌
_KEEP_FIELDS = (
    "side replay instanceId battleType seed bucketSeconds duration buckets eventCount truncated "
    "totalDamage bossDamage categories curves skills books branches activeBranches players"
    " perSecondTop perSecondBossTop factorRows factorSnapshots factorSources factorsTruncated"
).split()


def _slim_side(side: dict | None, keep_events: bool) -> dict | None:
    if not side:
        return None
    out = {k: side.get(k) for k in _KEEP_FIELDS}
    if keep_events:
        out["events"] = side.get("events") or []
    return out


def slim(data: dict, keep_events: bool) -> dict:
    """把 {mode, pvp, self, other} 压成报告载荷。

    PVP 时主视图取我方（self），并带上 pvp 分数与敌方汇总（不含原始事件）。
    """
    if "self" not in data and "other" not in data:
        return _slim_side(data, keep_events) or {}
    out = _slim_side(data.get("self"), keep_events) or {}
    out["mode"] = data.get("mode") or "single"
    out["pvp"] = data.get("pvp")
    out["other"] = _slim_side(data.get("other"), False)
    return out


# ── CSV ──

CSV_COLUMNS = (
    "side,t_sec,skill_id,skill_name,category,kind,origin,book_id,book_name,"
    "branch_id,branch_name,branch_level,element,damage,is_crit,is_boss,is_elite"
)
# JSON 里的事件字段名 → CSV 列名
_EVENT_FIELDS = (
    ("t", "t_sec"), ("skill", "skill_id"), ("skillName", "skill_name"),
    ("cat", "category"), ("kind", "kind"), ("origin", "origin"), ("book", "book_id"),
    ("bookName", "book_name"), ("branch", "branch_id"), ("branchName", "branch_name"),
    ("branchLevel", "branch_level"), ("elem", "element"), ("dmg", "damage"),
    ("crit", "is_crit"), ("boss", "is_boss"), ("elite", "is_elite"),
)


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if value is True:
        return "1"
    if value is False:
        return "0"
    if isinstance(value, float):
        value = round(value, 3)
    text = str(value)
    if any(ch in text for ch in (',', '"', '\n')):
        return '"' + text.replace('"', '""') + '"'
    return text


def render_csv(data: dict) -> str:
    """逐条伤害事件 CSV，双方合一，第一列 side 区分敌我。"""
    rows = [CSV_COLUMNS]
    sides = [(key, data[key]) for key in ("self", "other") if data.get(key)]
    if not sides:
        sides = [("self", data)]
    for side_key, side in sides:
        for event in side.get("events") or []:
            cells = [_csv_cell(side_key)]
            for field, _column in _EVENT_FIELDS:
                cells.append(_csv_cell(event.get(field)))
            rows.append(",".join(cells))
    return '\n'.join(rows)
