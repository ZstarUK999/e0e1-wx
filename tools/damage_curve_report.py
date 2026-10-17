"""把战斗／PVP 伤害采集结果拉下来，生成 HTML 报告。

正常用法（连 CDP 取数并落盘）：
    python tools/damage_curve_report.py                 # 自动扫端口
    python tools/damage_curve_report.py --port 62000 --csv --open

只重算 HTML（不连 CDP，读 logs 里已保存的 JSON）：
    python tools/damage_curve_report.py --from-json latest
    python tools/damage_curve_report.py --from-json logs/damage_curve_20261015_113000.json

产物默认落在 logs/：damage_curve_<时间戳>.json / .html / .csv

渲染代码在 package/plugin_manager/damage_report.py（与插件管理器共用），
本文件只负责 CDP 取数和命令行参数。

数据口径：事件里的 damage 是 CompLife.sub 返回的实际扣血量
（过护盾/格挡/生命保底，被 overkill 截断），不是公式算出的原始伤害。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cdp_probe  # noqa: E402
from package.devtools.constants import CDP_PORT_END, CDP_PORT_START  # noqa: E402
from package.plugin_manager.damage_report import describe, write_outputs  # noqa: E402

# 跨进 gameContext 取数：脚本把 damageCurveJson 同时挂在了 top 和 gameContext，
# 但采集状态只存在于脚本实际执行的那个上下文里，所以两边都试一遍。
FETCH_EXPRESSION = r"""
(function () {
  function gameWindow() {
    try { if (globalThis.UIManager) return globalThis; } catch (e) {}
    try {
      var f = globalThis.document && globalThis.document.querySelector('iframe[name="gameContext"]');
      if (f && f.contentWindow && f.contentWindow.UIManager) return f.contentWindow;
    } catch (e) {}
    try {
      for (var i = 0; i < globalThis.frames.length; i++) {
        if (globalThis.frames[i] && globalThis.frames[i].UIManager) return globalThis.frames[i];
      }
    } catch (e) {}
    return null;
  }
  var candidates = [];
  try {
    var g = gameWindow();
    if (g) candidates.push(g);
    if (candidates.indexOf(globalThis) < 0) candidates.push(globalThis);
  } catch (e) {
    candidates.push(globalThis);
  }
  for (var i = 0; i < candidates.length; i++) {
    var ctx = candidates[i];
    if (!ctx || typeof ctx.damageCurveJson !== "function") continue;
    var data = ctx.damageCurveJson();
    if (data && (data.self || data.other || data.eventCount)) {
      return { ok: true, via: (ctx === globalThis ? "top" : "gameContext"), data: data };
    }
  }
  return {
    ok: false,
    error: "damageCurveJson() 不可用或还没有采集到伤害事件（脚本注入了吗？打过一场了吗？）"
  };
})()
"""


async def fetch(port: int) -> dict:
    async with cdp_probe.CdpSession(f"ws://127.0.0.1:{port}") as session:
        msg_id = await session.send(
            "Runtime.evaluate",
            {
                "expression": FETCH_EXPRESSION,
                "returnByValue": True,
                "awaitPromise": True,
                "includeCommandLineAPI": True,
            },
        )
        responses = await session.drain(20.0)
        raw = responses.get(msg_id) or {}
        if not raw:
            raise RuntimeError("CDP 无响应（小程序可能未回连）")
        result = (raw.get("result") or {}).get("value")
        if not isinstance(result, dict):
            raise RuntimeError(f"返回格式异常：{str(raw)[:300]}")
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "取数失败")
        return result


async def main() -> int:
    parser = argparse.ArgumentParser(description="导出战斗／PVP 伤害曲线 HTML 报告")
    parser.add_argument("--port", type=int, default=0,
                        help=f"CDP 端口，默认扫描 {CDP_PORT_START}-{CDP_PORT_END}")
    parser.add_argument("--out", default="logs", help="输出目录，默认 logs/")
    parser.add_argument("--from-json", dest="from_json", default="",
                        help="直接读取 logs 里已保存的 damage_curve_*.json 渲染，不连 CDP"
                             "（改了模板后拿旧数据重算用；latest 取最新一份）")
    parser.add_argument("--no-events", action="store_true",
                        help="不内嵌原始事件（HTML 更小）")
    parser.add_argument("--csv", action="store_true", help="同时导出逐条伤害事件 CSV（双方合一，带 side 列）")
    parser.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.from_json:
        source = Path(args.from_json)
        if args.from_json == "latest":
            candidates = sorted(out_dir.glob("damage_curve_*.json"))
            if not candidates:
                print(f"{out_dir} 里没有 damage_curve_*.json")
                return 1
            source = candidates[-1]
        elif not source.is_absolute() and not source.exists():
            source = out_dir / args.from_json
        if not source.exists():
            print(f"找不到数据文件：{source}")
            return 1
        data = json.loads(source.read_text(encoding="utf-8"))
        # 沿用原文件名的时间戳，覆盖同一份产物，避免堆积
        stamp = source.stem[len("damage_curve_"):] or datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"读取：{source}")
        for line in describe(data):
            print(line)
        written = write_outputs(data, out_dir, stamp, save_json=False,
                                write_csv=args.csv, keep_events=not args.no_events)
    else:
        ports = [args.port] if args.port else await cdp_probe.scan_ports(CDP_PORT_START, CDP_PORT_END)
        if not ports:
            print("未发现可用的 CDP 端口，请先开启调试并等待小程序回连")
            return 1
        port = ports[0]
        print(f"===== CDP 端口 {port} =====")
        result = await fetch(port)
        print("取值上下文:", result.get("via"))
        data = result["data"]
        for line in describe(data):
            print(line)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        written = write_outputs(data, out_dir, stamp, save_json=True,
                                write_csv=args.csv, keep_events=not args.no_events)

    print()
    for path in written:
        print(f"{path.suffix.lstrip('.').upper()}: {path}")
    if (data.get("mode") or "single") == "pvp":
        print("      改模板后不用重打，运行：python tools/damage_curve_report.py --from-json latest")
    if args.open:
        html = next((p for p in written if p.suffix == ".html"), None)
        if html:
            webbrowser.open(html.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
