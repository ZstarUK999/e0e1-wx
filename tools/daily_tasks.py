"""日常任务框架CLI：配置检查、任务列表、开关与调度循环。

python tools/daily_tasks.py validate
python tools/daily_tasks.py list
python tools/daily_tasks.py enable --task energy
python tools/daily_tasks.py enable
python tools/daily_tasks.py run --once

已接入energy扫荡任务；总开关/energy开关均打开时run会消耗现有体力。
inspect仅只读检查体力，不切换配置、不扫荡；其余8项尚未接入。
先启动tools/cdp_bridge.py serve，run默认常驻并重读配置；Ctrl+C安全停止。
日志使用系统本地时间。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from package.daily_tasks.config import DEFAULT_CONFIG_PATH, load_config, set_enabled
from package.daily_tasks.scheduler import ExecutionUncertain, RetryableTaskError, Scheduler
from package.daily_tasks.bridge_game import BridgeGame, DEFAULT_BRIDGE_SESSION
from package.daily_tasks.energy import register_energy


def build_scheduler(config, session_file: Path, journal_path: Path):
    scheduler = Scheduler(config)
    game = BridgeGame(session_file)
    register_energy(scheduler, game, journal_path)
    return scheduler, game


async def run_scheduler(scheduler: Scheduler, path: Path, once: bool) -> dict:
    if not once:
        logging.getLogger("daily_tasks").warning("日常调度运行中；已接入energy，开启后将正常扫荡现有体力。Ctrl+C安全停止")
    work = scheduler.tick() if once else scheduler.run(config_loader=lambda: load_config(path))
    runner = asyncio.create_task(work)
    try:
        # 首次Ctrl+C取消包装协程而非处理器：先请求stop，再等待安全收尾。
        await asyncio.shield(runner)
    except asyncio.CancelledError:
        scheduler.stop()
        await asyncio.shield(runner)
        raise
    finally:
        scheduler.stop()
    return scheduler.snapshot()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="日常任务统一调度与JSON配置（已接入energy正常扫荡）")
    commands = parser.add_subparsers(dest="command", required=True)
    command_parsers = [commands.add_parser("validate", help="校验配置"), commands.add_parser("list", help="列出开关与任务状态")]
    for name in ("enable", "disable"):
        command = commands.add_parser(name, help="开启/关闭全局或指定任务")
        command.add_argument("--task", help="task_id；省略则设置总开关")
        command_parsers.append(command)
    run = commands.add_parser("run", help="启动调度循环，安全停止/配置热重载")
    run.add_argument("--once", action="store_true", help="执行一次到期任务；已开启energy时可能扫完现有体力")
    command_parsers.append(run)
    command_parsers.append(commands.add_parser("inspect", help="只读检查体力、界面安全状态，不扫荡"))
    for command in command_parsers:
        command.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
        command.add_argument("--bridge-session", type=Path, default=DEFAULT_BRIDGE_SESSION)
        command.add_argument("--restore-file", type=Path, help="原方案恢复记录；默认与日常配置同目录")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    try:
        if args.command in ("enable", "disable"):
            set_enabled(args.config, args.command == "enable", args.task)
        config = load_config(args.config)
        if args.command == "validate":
            result = {"ok": True, "config": str(args.config.absolute()), "enabled": config.enabled, "task_count": len(config.tasks)}
        else:
            journal = args.restore_file or args.config.with_name(args.config.stem + ".energy_restore.json")
            scheduler, game = build_scheduler(config, args.bridge_session, journal)
            if args.command in {"run", "inspect"}:
                async def execute():
                    try:
                        if args.command == "inspect":
                            return await game.inspect()
                        return await run_scheduler(scheduler, args.config, args.once)
                    finally:
                        await game.close()
                result = asyncio.run(execute())
            else:
                result = scheduler.snapshot()
            result["ok"] = not bool(result.get("blocked_reason") or result.get("config_error"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RetryableTaskError, ExecutionUncertain) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
