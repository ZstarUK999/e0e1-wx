"""客户端/服务端信任边界审计：扫描所有 service 调用，列出请求体里客户端主动填的字段。

思路：服务端权威的设计里，请求体应该只传"标识符"（id / type / index），
      具体数值（价格、时长、数量、结果、增减量）由服务端查表算。
      如果请求体里出现数值字段，就说明这些值来自客户端，需要服务端复检。

用法：
    python tools/audit_client_authority.py [game.js 路径]
    python tools/audit_client_authority.py --all-keys        # 不过滤，列出全部字段
    python tools/audit_client_authority.py --top 60
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_JS = (
    Path(__file__).resolve().parents[1]
    / "output"
    / "wx6d5e82c174635a48"
    / "65"
    / "subpackages"
    / "game"
    / "game.js"
)

# 请求体里出现这些键 => 客户端在传"值"，需要服务端复检
SUSPICIOUS_KEYS = {
    # 货币 / 消耗
    "cost", "costGold", "costgold", "gold", "price", "pay", "payNum", "money",
    "num", "count", "amount", "total", "value", "add", "dec", "inc", "delta",
    # 时间 / 时长
    "time", "duration", "reduceTime", "reduce", "addTime", "leftTime", "cd",
    "arrive", "arriveAt", "startTime", "endTime",
    # 结果 / 数值
    "win", "result", "resultType", "score", "damage", "dmg", "exp", "level",
    "rate", "percent", "ratio", "multiple", "multi", "power", "fightPower",
    # 其他
    "reward", "items", "dropItems", "progress", "wave", "stage", "quality",
}

# 只传这些键 => 标识符，服务端权威
IDENTIFIER_HINT = re.compile(r"(id|Id|ID|type|index|idx|key|pos|slot|warId|teamId)$")

# 匹配形如 xxx(NS.method, { ... }) 的调用；NS 通常是服务命名空间对象。
CALL_RE = re.compile(r"[A-Za-z_$][\w$]*\(\s*([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*,\s*\{")


def extract_object(text: str, start: int) -> tuple[str, int]:
    """从 start 处的 '{' 开始，按括号配对截取对象字面量（忽略字符串里的括号）。"""
    depth = 0
    i = start
    quote = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1], i + 1
        i += 1
    return text[start:], len(text)


def top_level_keys(obj_src: str) -> list[str]:
    """取对象字面量的顶层键名（只解析一层，够用）。"""
    inner = obj_src[1:-1]
    keys: list[str] = []
    depth = 0
    quote = None
    token = ""
    expect_key = True
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            token += ch
            if ch == "\\":
                token += inner[i + 1] if i + 1 < len(inner) else ""
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            token += ch
            i += 1
            continue
        if ch in "{[(":
            depth += 1
            i += 1
            continue
        if ch in "}])":
            depth -= 1
            i += 1
            continue
        if depth == 0:
            if ch == ":" and expect_key:
                keys.append(token.strip().strip("\"'"))
                token = ""
                expect_key = False
                i += 1
                continue
            if ch == ",":
                token = ""
                expect_key = True
                i += 1
                continue
        token += ch
        i += 1
    return [k for k in keys if k]


def scan(path: Path) -> list[tuple[str, str, list[str]]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    results: list[tuple[str, str, list[str]]] = []
    for match in CALL_RE.finditer(text):
        namespace, method = match.group(1), match.group(2)
        brace = text.index("{", match.end() - 1)
        obj_src, _ = extract_object(text, brace)
        keys = top_level_keys(obj_src)
        results.append((namespace, method, keys))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描 service 调用请求体，找出客户端可控数值字段")
    parser.add_argument("js", nargs="?", default=str(DEFAULT_JS), help="game.js 路径")
    parser.add_argument("--all-keys", action="store_true", help="不过滤，列出全部字段")
    parser.add_argument("--top", type=int, default=40, help="最多打印多少条")
    args = parser.parse_args()

    path = Path(args.js)
    if not path.exists():
        print(f"文件不存在：{path}")
        return 1

    results = scan(path)
    print(f"共解析 {len(results)} 处 service 调用\n")

    findings: list[tuple[str, str, list[str]]] = []
    for namespace, method, keys in results:
        if args.all_keys:
            findings.append((namespace, method, keys))
            continue
        hits = [k for k in keys if k in SUSPICIOUS_KEYS or (k.lower() in {s.lower() for s in SUSPICIOUS_KEYS})]
        if hits:
            findings.append((namespace, method, hits))

    findings.sort(key=lambda item: (-len(item[2]), item[1]))
    print(f"命中「客户端传值」字段的调用：{len(findings)} 处（按可疑字段数排序）\n")

    key_counter: Counter[str] = Counter()
    for namespace, method, hits in findings[: args.top]:
        print(f"  {namespace}.{method:<28} {', '.join(hits)}")
        key_counter.update(hits)

    if key_counter:
        print("\n高频可疑字段：")
        for key, count in key_counter.most_common(20):
            print(f"  {key:<18} {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
