"""连到已建立的 DevTools CDP 会话，打印玩家信息快照的真实内存结构。

用途：GDRoleSnap 里很多字段是嵌套 Map / 对象，靠猜字段名解析不出来。
本脚本会：
  1. 跨进 gameContext 拿到当前打开的玩家信息界面快照
  2. 打印每个字段的真实结构（类型 / 大小 / 前几条样本）
  3. 加载 configs.ts，对每个 ID 反查它到底命中哪张配置表（解决"解析出 ID 开头的英文+数字"问题）

用法：先在 GUI 里连上调试，然后在游戏里【打开某个玩家的信息界面】，再执行：
    python tools/cdp_snapshot_probe.py --port 62000
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

PROBE_EXPRESSION = r"""
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

  function clean(v, d) {
    d = d || 0;
    if (v === null || v === undefined) return null;
    var t = typeof v;
    if (t === "function") return "[fn]";
    if (t === "number" || t === "boolean" || t === "string") return v;
    if (d > 3) return kind(v);
    if (isMap(v)) {
      var o = {}, i = 0;
      v.forEach(function (val, key) { if (i++ >= 6) return; o[String(key)] = clean(val, d + 1); });
      return { __map: true, size: v.size, sample: o };
    }
    if (Array.isArray(v)) {
      return { __arr: true, len: v.length, sample: v.slice(0, 6).map(function (x) { return clean(x, d + 1); }) };
    }
    if (t === "object") {
      var o2 = {}, keys = Object.keys(v), j = 0;
      for (; j < keys.length && j < 14; j++) {
        try { o2[keys[j]] = clean(v[keys[j]], d + 1); } catch (e) {}
      }
      return o2;
    }
    return String(v);
  }

  var game = resolveGame();
  if (!game) { OUT.error = "no game window"; return JSON.stringify(OUT); }
  OUT.ok = true;

  var ui = null;
  var ins = game.UIManager && game.UIManager.ins;
  if (ins && ins.viewParams) {
    for (var k in ins.viewParams) {
      var p = ins.viewParams[k];
      if (!p || !p.showing || !p.ui) continue;
      var id = p.cfgId || (p.cfg && p.cfg.id);
      if (id === "Setting") { ui = p.ui; break; }
    }
  }
  OUT.hasSettingUi = !!ui;
  OUT.uiIsSelf = ui ? !!ui.isSelf : null;

  var snap = ui && ui.info;
  OUT.hasSnapshot = !!snap;
  if (!snap) {
    OUT.hint = "没拿到快照：请先在游戏里打开一个玩家的信息界面";
    OUT.gameGlobals = Object.keys(game).filter(function (k) {
      return /^(ROLE|SERVER_DATA|TREASURE|BATTLEFIELDS|GOOD_FRIEND|ROLE_EXT)$/.test(k);
    });
    return JSON.stringify(OUT);
  }

  OUT.snapKeys = Object.keys(snap).slice(0, 120);

  var fields = ["skillLevel", "skillCombineLevel", "equipSkill", "extEquipSkill",
    "epicLevel", "epicAwakening", "skillPlan", "desirePlan", "allDesirePlan",
    "equipment", "equipmentLevel", "equipmentSuit", "equipmentPlanSkill",
    "pet", "formationPetInfo", "formationPetSkill", "magic",
    "attribute", "achieve", "fashion", "unlockModuleIds", "team", "roleBase", "moduleAttr"];
  OUT.fields = {};
  fields.forEach(function (f) {
    if (snap[f] !== undefined) OUT.fields[f] = clean(snap[f], 0);
  });

  var cfg = null;
  try {
    if (game.System && typeof game.System.import === "function") {
      cfg = await game.System.import("chunks:///_virtual/configs.ts");
    }
  } catch (e) { OUT.cfgError = String(e); }
  OUT.cfgLoaded = !!cfg;

  if (cfg) {
    var tables = Object.keys(cfg).filter(function (k) { return /Cfg$/.test(k); });
    OUT.cfgTableCount = tables.length;

    function idsOf(f) {
      var v = snap[f], ids = [];
      if (isMap(v)) {
        var i = 0;
        v.forEach(function (val, key) {
          if (i++ >= 4) return;
          ids.push({ key: key, cfgId: (val && typeof val === "object" && val.cfgId !== undefined) ? val.cfgId : key });
        });
      } else if (Array.isArray(v)) {
        v.slice(0, 4).forEach(function (x) {
          if (x && typeof x === "object" && x.cfgId !== undefined) ids.push({ key: null, cfgId: x.cfgId });
        });
      } else if (v && typeof v === "object" && v.cfgId !== undefined) {
        ids.push({ key: null, cfgId: v.cfgId });
      }
      return ids;
    }

    OUT.idMatch = {};
    ["skillLevel", "epicLevel", "epicAwakening", "skillCombineLevel", "equipSkill",
     "desirePlan", "allDesirePlan", "equipment", "pet", "magic", "formationPetSkill"].forEach(function (f) {
      OUT.idMatch[f] = idsOf(f).map(function (item) {
        var hits = [];
        tables.forEach(function (t) {
          var table = cfg[t];
          if (!table || typeof table.getById !== "function") return;
          try {
            var row = table.getById(Number(item.cfgId));
            if (row && typeof row === "object") {
              var nm = row.name || row.Name || row.cfgName || row.title || row.des;
              if (nm) hits.push(t + " = " + String(nm).slice(0, 24));
            }
          } catch (e) {}
        });
        return { key: item.key, cfgId: item.cfgId, hits: hits.slice(0, 14) };
      });
    });
  }

  return JSON.stringify(OUT);
})()
""".strip()


DEFAULT_LOG = Path(__file__).resolve().parents[1] / "logs" / "cdp_snapshot_probe.log"


async def main() -> int:
    parser = argparse.ArgumentParser(description="探测玩家信息快照的内存结构")
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
                value = await session.evaluate(PROBE_EXPRESSION, timeout=8.0)
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
