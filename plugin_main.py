"""独立插件管理器入口：内部CDP服务和自动注入；不主动启动微信或游戏。

装配逻辑在 package.plugin_manager.app，这里只保留启动壳。
"""

from __future__ import annotations

from package.plugin_manager.app import main


if __name__ == "__main__":
    # 冻结后 multiprocessing 子进程会重新执行本 exe（argv[1] 为 --multiprocessing-fork），
    # 必须在这里接住它：晚了就会先撞上单实例锁直接退出，DevTools worker 永远起不来。
    import multiprocessing

    multiprocessing.freeze_support()
    import argparse
    parser = argparse.ArgumentParser(description='遗弃之地插件管理器')
    parser.add_argument('--platform', choices=('wechat', 'douyin'), help='可选；省略时显示平台选择器')
    args = parser.parse_args()
    raise SystemExit(main(platform=args.platform))
