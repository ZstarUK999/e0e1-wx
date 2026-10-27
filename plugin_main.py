"""独立插件管理器入口：内部CDP服务和自动注入；不主动启动微信或游戏。

装配逻辑在 package.plugin_manager.app，这里只保留启动壳。
"""

from __future__ import annotations



def main(*args, **kwargs):
    # Keep the importable entry point while native helpers avoid loading Qt/app state.
    from package.plugin_manager.app import main as app_main
    return app_main(*args, **kwargs)


if __name__ == "__main__":
    # 冻结后 multiprocessing 子进程会重新执行本 exe（argv[1] 为 --multiprocessing-fork），
    # 必须在这里接住它：晚了就会先撞上单实例锁直接退出，DevTools worker 永远起不来。
    import multiprocessing

    multiprocessing.freeze_support()
    import argparse
    parser = argparse.ArgumentParser(description='遗弃之地插件管理器')
    parser.add_argument('--wechat-native-ui',choices=('Snapshot','Scan','Click','CachedClick','Close','Status'),help=argparse.SUPPRESS)
    parser.add_argument('--position-cache',help=argparse.SUPPRESS)
    parser.add_argument('--native-result',help=argparse.SUPPRESS)
    parser.add_argument('--control-label',help=argparse.SUPPRESS)
    parser.add_argument('--platform', choices=('wechat', 'douyin', 'androws'), help='可选；省略时显示平台选择器')
    args = parser.parse_args()
    if args.wechat_native_ui:
        from package.plugin_manager.wechat_native_launch import helper_main
        raise SystemExit(helper_main(args.wechat_native_ui,args.control_label,args.native_result,args.position_cache))
    raise SystemExit(main(platform=args.platform))
