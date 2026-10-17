"""深度探针：展开玩家信息快照里的嵌套结构，并把关键 ID 的配置行完整打印出来。

在 cdp_snapshot_probe.py 拿到顶层结构之后用。需要先在游戏里打开某个玩家的信息界面。

    python tools/cdp_deep_probe.py --port 62000

输出写到 logs/cdp_deep_probe.log，同时在终端打印。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cdp_probe  # noqa: E402
from package.devtools.constants import CDP_PORT_END, CDP_PORT_START  # noqa: E402

DEFAULT_LOG = Path(__file__).resolve().parents[1] / "logs" / "cdp_deep_probe.log"

DEEP_EXPRESSION = r"""
(async function () {
  var OUT = { ok: false };
  function kind(v) { return Object.prototype.toString.call(v); }
  function isMap(v) { return !!v && kind(v) === "[object Map]"; }

  function resolveGame() {
    try { if (globalThis.UIManager) return globalThis; } catch (e) {}
    try {
      var n = globalThis.document && globalThis.document.querySelector('iframe[name="gameContext"]');
      if (n && n.contentWindow && n.contentWindow.UIManager) return n.contentWindow;
    } catch (e) {}
    try {
      for (var i = 0; i < globalThis.frames.length; i++) {
        var f = globalThis.frames[i];
        try { if (f && f.UIManager) return f; } catch (e) {}
      }
    } catch (e) {}
    return null;
  }

  function clean(v, d, limit) {
    d = d || 0; limit = limit || 30;
    if (v === null || v === undefined) return null;
    var t = typeof v;
    if (t === "function") return "[fn]";
    if (t === "number" || t === "boolean" || t === "string") return v;
    if (d > 6) return kind(v);
    if (isMap(v)) {
      var o = {}, i = 0;
      v.forEach(function (val, key) { if (i++ >= limit) return; o[String(key)] = clean(val, d + 1, limit); });
      return { __map: true, size: v.size, sample: o };
    }
    if (Array.isArray(v)) {
      return { __arr: true, len: v.length, sample: v.slice(0, limit).map(function (x) { return clean(x, d + 1, limit); }) };
    }
    if (t === "object") {
      var o2 = {}, keys = Object.keys(v), j = 0;
      for (; j < keys.length && j < 30; j++) {
        try { o2[keys[j]] = clean(v[keys[j]], d + 1, limit); } catch (e) { o2[keys[j]] = "[err]"; }
      }
      return o2;
    }
    return String(v);
  }

  var game = resolveGame();
  if (!game) { OUT.error = "no game window"; return JSON.stringify(OUT); }
  OUT.ok = true;

  var ui = null, ins = game.UIManager && game.UIManager.ins;
  if (ins && ins.viewParams) {
    for (var k in ins.viewParams) {
      var p = ins.viewParams[k];
      if (!p || !p.showing || !p.ui) continue;
      var id = p.cfgId || (p.cfg && p.cfg.id);
      if (id === "Setting") { ui = p.ui; break; }
    }
  }
  var snap = ui && ui.info;
  if (!snap) { OUT.hint = "请先打开玩家信息界面"; return JSON.stringify(OUT); }

  // 1. 完整展开关键嵌套结构
  var deep = ["equipment", "equipmentLevel", "equipmentSuit", "desirePlan", "allDesirePlan",
    "magic", "pet", "formationPetInfo", "epicAwakening", "equipSkill", "extEquipSkill",
    "skillPlan", "epicLevel", "skillLevel"];
  OUT.deep = {};
  deep.forEach(function (f) {
    if (snap[f] !== undefined) OUT.deep[f] = clean(snap[f], 0, 30);
  });

  // 2. 配置行反查：把候选表 × 候选 ID 的完整行打出来
  var cfg = null;
  try {
    if (game.System && typeof game.System.import === "function") {
      cfg = await game.System.import("chunks:///_virtual/configs.ts");
    }
  } catch (e) { OUT.cfgError = String(e); }
  if (!cfg) return JSON.stringify(OUT);

  function rowOf(table, id) {
    var t = cfg[table];
    if (!t || typeof t.getById !== "function") return null;
    try {
      var r = t.getById(Number(id));
      return r ? clean(r, 0, 40) : null;
    } catch (e) { return "[err]"; }
  }

  var probes = {};
  // 三尸：desirePlan 的 value 形如 6010701，试整值 / 前三位 / 各种切分
  var desireIds = [];
  if (isMap(snap.desirePlan)) { var i = 0; snap.desirePlan.forEach(function (v) { if (i++ >= 3) return; desireIds.push(v); }); }
  OUT.desireValues = desireIds;
  desireIds.forEach(function (v) {
    var s = String(v);
    probes["desire_" + s] = {
      raw: v,
      whole: rowOf("DesireCfg", v),
      head3: rowOf("DesireCfg", s.slice(0, 3)),
      head4: rowOf("DesireCfg", s.slice(0, 4)),
      div10000: rowOf("DesireCfg", Math.floor(v / 10000)),
      div100: rowOf("DesireCfg", Math.floor(v / 100))
    };
  });

  // 脸谱：configId + 词条 id
  var equipEntryIds = [];
  var equipCfgIds = [];
  if (isMap(snap.equipment)) {
    snap.equipment.forEach(function (item) {
      if (item && item.configId && equipCfgIds.length < 3) equipCfgIds.push(item.configId);
      if (item && Array.isArray(item.entry)) {
        item.entry.slice(0, 3).forEach(function (e) { if (equipEntryIds.length < 5) equipEntryIds.push(e.id); });
      }
    });
  }
  OUT.equipCfgIds = equipCfgIds;
  OUT.equipEntryIds = equipEntryIds;
  equipCfgIds.forEach(function (id) {
    probes["equip_" + id] = { EquipmentCfg: rowOf("EquipmentCfg", id) };
  });
  equipEntryIds.forEach(function (id) {
    probes["equipEntry_" + id] = {
      EquipmentEntryCfg: rowOf("EquipmentEntryCfg", id),
      EquipmentEntryGroupCfg: rowOf("EquipmentEntryGroupCfg", id)
    };
  });

  // 鬼仆
  if (snap.pet) {
    probes["pet_" + snap.pet.cfgId] = { PetCfg: rowOf("PetCfg", snap.pet.cfgId) };
    (snap.pet.entry || []).slice(0, 4).forEach(function (id) {
      probes["petEntry_" + id] = { PetEntryCfg: rowOf("PetEntryCfg", id), PetQualityCfg: rowOf("PetQualityCfg", id) };
    });
    var petSkillIds = [];
    if (isMap(snap.pet.skillLevel)) { var j = 0; snap.pet.skillLevel.forEach(function (v, key) { if (j++ >= 3) return; petSkillIds.push(key); }); }
    petSkillIds.forEach(function (id) {
      probes["petSkill_" + id] = { PetSkillCfg: rowOf("PetSkillCfg", id) };
    });
  }

  // 法器
  if (snap.magic) {
    probes["magic_" + snap.magic.onUseMagic] = { MagicArtifactBaseCfg: rowOf("MagicArtifactBaseCfg", snap.magic.onUseMagic) };
    // 当前方案里的法器条目
    try {
      var plan = snap.magic.plan && (isMap(snap.magic.plan) ? snap.magic.plan.get(snap.magic.onUsePlan) : null);
      if (plan && isMap(plan.entry)) {
        var ids = [];
        plan.entry.forEach(function (val, key) { if (ids.length < 4) ids.push({ key: key, val: val }); });
        OUT.magicEntrySamples = ids.map(function (x) { return { key: x.key, val: clean(x.val, 0, 20) }; });
        ids.forEach(function (x) {
          if (x.val && typeof x.val === "object" && x.val.cfgId !== undefined) {
            probes["magicItem_" + x.val.cfgId] = { MagicArtifactBaseCfg: rowOf("MagicArtifactBaseCfg", x.val.cfgId) };
          }
        });
      }
    } catch (e) {}
  }

  // 天书觉醒分支 id（epicAwakening 内层 key，如 101）
  if (isMap(snap.epicAwakening)) {
    var branchIds = [];
    snap.epicAwakening.forEach(function (inner) {
      if (isMap(inner)) { var j = 0; inner.forEach(function (v, key) { if (j++ >= 2) return; branchIds.push(key); }); }
    });
    OUT.awakeBranchIds = branchIds.slice(0, 5);
    ["SkillBookCfg", "SkillCfg", "SummonCfg", "SkillBookEvolutionCfg", "EquipmentEntryCfg"].forEach(function (t) {
      branchIds.slice(0, 2).forEach(function (id) {
        probes["awake_" + t + "_" + id] = rowOf(t, id) ? { table: t, row: rowOf(t, id) } : null;
      });
    });
  }

  // 装备槽位上的天书 id（equipSkill 的 value）
  if (isMap(snap.equipSkill)) {
    var esIds = [];
    snap.equipSkill.forEach(function (v) { if (esIds.length < 3) esIds.push(v); });
    OUT.equipSkillValues = esIds;
    esIds.forEach(function (id) {
      probes["equipSkill_" + id] = { SkillBookCfg: rowOf("SkillBookCfg", id), SummonCfg: rowOf("SummonCfg", id) };
    });
  }

  // 三尸槽位 key 编码（65536 / 262145 ...）
  if (isMap(snap.desirePlan)) {
    var keys = [];
    var n = 0;
    snap.desirePlan.forEach(function (v, key) { if (n++ >= 6) return; keys.push({ key: key, val: v }); });
    OUT.desireSlots = keys.map(function (x) {
      return { key: x.key, slot: Math.floor(x.key / 65536), idx: x.key % 65536, val: x.val };
    });
  }

  OUT.probes = probes;
  return JSON.stringify(OUT);
})()
""".strip()


async def main() -> int:
    parser = argparse.ArgumentParser(description="深度探测玩家信息快照的嵌套结构")
    parser.add_argument("--port", type=int, default=0, help=f"CDP 端口，默认扫描 {CDP_PORT_START}-{CDP_PORT_END}")
    parser.add_argument("--out", default=str(DEFAULT_LOG), help="结果日志文件路径")
    args = parser.parse_args()

    log_path = Path(args.out)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    ports = [args.port] if args.port else await cdp_probe.scan_ports(CDP_PORT_START, CDP_PORT_END)
    if not ports:
        message = "未发现可用的 CDP 端口，请先开启调试并等待小程序回连"
        print(message)
        log_path.write_text(message + "\n", encoding="utf-8")
        return 1

    for port in ports:
        header = f"===== CDP 端口 {port} ====="
        print("\n" + header)
        lines.append(header)
        try:
            async with cdp_probe.CdpSession(f"ws://127.0.0.1:{port}") as session:
                value = await session.evaluate(DEEP_EXPRESSION, timeout=9.0)
        except Exception as exc:
            text = f"    探测失败：{exc}"
            print(text)
            lines.append(text)
            continue
        if value is None:
            text = "    无返回"
            print(text)
            lines.append(text)
            continue
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except json.JSONDecodeError:
            parsed = value
        body = json.dumps(parsed, ensure_ascii=False, indent=2)
        print(body)
        lines.append(body)

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n结果已写入：{log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
