"""从反编译的 game.js 中按模块名抽取「摸金行动」相关代码。"""
import os
import re
import sys

SRC = r"d:/UGit/e0e1-wx/output/wx6d5e82c174635a48/65/subpackages/game/game.js"
OUT = r"d:/UGit/e0e1-wx/output/wx6d5e82c174635a48/65/subpackages/game/treasure-action"

TARGETS = [
    # 核心模块 & 列表项组件
    "treasure-action-module",
    "treasure-data-view",
    "treasure-action-room-cell",
    "treasure-action-room-cell-debug",
    "treasure-action-map-target-cell",
    "treasure-action-entry-ceil",
    "treasure-action-stage-toggle-item",
    "treasure-action-team-member",
    "treasure-action-application-cell",
    "treasure-action-invition-cell",
    "treasure-action-invite-me-team",
    "treasure-action-rec-team",
    "treasure-action-bag-grid-item",
    "treasure-action-bag-treasure-item",
    "treasure-action-treasure-item",
    "treasure-action-treasure-detail-item",
    "treasure-action-damage-queue",
    "treasure-action-reward-progress-item",
    # UI 层
    "ui-treasure-action-map",
    "ui-treasure-action-map-view",
    "ui-treasure-action-entry",
    "ui-treasure-action-entry-view",
    "ui-treasure-action-team",
    "ui-treasure-action-team-view",
    "ui-treasure-action-application",
    "ui-treasure-action-application-view",
    "ui-treasure-action-invitation",
    "ui-treasure-action-invitation-view",
    "ui-treasure-action-invite-me-teams",
    "ui-treasure-action-invite-me-teams-view",
    "ui-treasure-action-lock-reward",
    "ui-treasure-action-lock-reward-view",
    "ui-treasure-action-privilege",
    "ui-treasure-action-privilege-view",
    "ui-treasure-action-reward-progress",
    "ui-treasure-action-reward-progress-view",
    "ui-treasure-action-side-tip",
    "ui-treasure-action-side-tip-view",
    "ui-treasure-action-stage-challenge",
    "ui-treasure-action-stage-challenge-view",
    "ui-treasure-action-stage-dual",
    "ui-treasure-action-stage-dual-view",
    "ui-treasure-action-subdue-battle",
    "ui-treasure-action-subdue-battle-view",
    "ui-treasure-action-subdue-battle-result",
    "ui-treasure-action-subdue-battle-result-view",
    "ui-treasure-action-treasure-bag",
    "ui-treasure-action-treasure-bag-view",
    "ui-treasure-action-treasure-handbook",
    "ui-treasure-action-treasure-handbook-view",
    "ui-treasure-action-turntable",
    "ui-treasure-action-turntable-view",
    "ui-treasure-action-congrants",
    "ui-treasure-action-congrants-view",
    "chat-treasure-action-item",
]

# 位于共享大模块内部的片段（按行区间抽取，闭区间，1-based）
RANGES = {
    "configs.ts": [
        (33849, 33960),   # TreasureActionCfg / TreasureConstantCfg / TreasureActionMapCfg / RewardCfg / BookCfg
    ],
    "enums.ts": [
        (30269, 30290),   # TreasureRoomType / TreasureType / WalkInTreasure* / TreasureEvent / TreasureTime
        (37341, 37350),   # EMTreasureState
        (37475, 37485),   # ETreasureCellStatus
    ],
    "gd-data.ts": [
        (39646, 39675),   # GDTreasureGroup / GDRoleTreasurePenaltyItem / GDRoleTreasure
        (40400, 40460),   # GDTreasureBag/Member/RoomCell/RoomLayer/Room/Treasure
    ],
    "protocol.ts": [
        (43631, 43740),   # TreasureSyncData 及 Treasure_* 协议
    ],
}

REGISTER_RE = re.compile(r'System\.register\("chunks:///_virtual/([^"]+)"')


def main():
    with open(SRC, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # 建立 register 块索引: name -> (start_idx, end_idx)
    regs = []
    for idx, line in enumerate(lines):
        m = REGISTER_RE.search(line)
        if m:
            regs.append((os.path.basename(m.group(1)), idx))
    regs.append(("__EOF__", len(lines)))

    os.makedirs(OUT, exist_ok=True)
    written = []

    for i, (name, start) in enumerate(regs[:-1]):
        base = name[:-3] if name.endswith(".ts") else name
        if base not in TARGETS:
            continue
        end = regs[i + 1][1]
        chunk = "".join(lines[start:end]).rstrip() + "\n"
        path = os.path.join(OUT, base + ".ts")
        with open(path, "w", encoding="utf-8") as f:
            f.write(chunk)
        written.append((base, start + 1, end, len(chunk.splitlines())))

    for fname, ranges in RANGES.items():
        parts = []
        for s, e in ranges:
            parts.append("// ===== game.js:%d-%d =====" % (s, e))
            parts.append("".join(lines[s - 1:e]))
        path = os.path.join(OUT, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))
        written.append((fname, ranges[0][0], ranges[-1][1], sum(e - s + 1 for s, e in ranges)))

    written.sort(key=lambda x: x[1])
    print("输出目录: %s" % OUT)
    print("%-52s %-12s %-12s %s" % ("文件", "game.js起始行", "结束行", "行数"))
    total = 0
    for name, s, e, n in written:
        total += n
        print("%-52s %-12d %-12d %d" % (name, s, e, n))
    print("合计 %d 行" % total)


if __name__ == "__main__":
    main()
