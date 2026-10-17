"""插件管理器打包脚本：PyInstaller 产物 + 运行时资源 + 体积报告。

默认产出 onedir 目录（不是单文件），因为后续要做文件级增量更新，单文件 exe
每次更新都要整包重下。

用法::

    python tools/build_exe.py                 # onedir + 控制台（首次打包便于看报错）
    python tools/build_exe.py --windowed      # onedir + 无控制台（正式分发）
    python tools/build_exe.py --onefile       # 单文件（仅用于对比体积）
    python tools/build_exe.py --exclude-frida # 排除 frida（默认是保留的）
    python tools/build_exe.py --features build/features.json  # 按 profile 开关功能
    python tools/build_exe.py --dry-run       # 只打印命令不执行
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "plugin_main.py"
APP_NAME = "e0e1-wx-plugins"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
# profile 放 tools/ 而不是 build/：build/ 是 PyInstaller 的输出目录，已被 git 忽略。
DEFAULT_FEATURES = ROOT / "tools" / "features.json"
DEFAULT_CERTS = ROOT / "server" / "backend" / "certs" / "client"
BACKEND_ROOT = ROOT / "server" / "backend"
# 与后台同一把私钥：两边签出来的 license 格式一致，服务器都能验过
DEFAULT_LICENSE_KEY = BACKEND_ROOT / "data" / "license_ed25519.key"
PROTO_SOURCE = ROOT / "server" / "backend" / "app" / "grpc" / "plugin.proto"
GRPC_STUB_DIR = ROOT / "package" / "plugin_manager" / "grpc_stub"

MODE_RELEASE = "release"
MODE_DEBUG = "debug"

# 可以在 profile 里关掉的功能。写进产物的文件只记录被关掉的项，
# 没写到的项在运行时一律视为开启，所以老产物和源码运行不受影响。
KNOWN_TASKS: tuple[str, ...] = (
    "sanshi_tombs", "artifact_tombs", "sanshi_raid", "artifact_raid",
    "sanshi_fill", "artifact_fill", "energy", "offline_reward", "arena",
)
KNOWN_PANELS: tuple[str, ...] = (
    "global", "daily", "bloodmoon", "player", "treasure", "damage", "debug",
    "energy", "mines", "arena",
)

# 运行时按 __file__ 相对定位读取的资源：源码在 package/ 下，冻结后落在
# _internal/ 内，同名相对目录必须原样保留，否则会静默读不到。
RESOURCES: tuple[tuple[str, str], ...] = (
    ("package/daily_tasks/daily_runtime.js", "package/daily_tasks"),
    ("package/daily_tasks/sweep_runtime.js", "package/daily_tasks"),
    ("package/plugin_manager/desire_runtime.js", "package/plugin_manager"),
    ("package/plugin_manager/douyin_bridge.js", "package/plugin_manager"),
    ("tools/config/daily_tasks.json", "tools/config"),
    ("tools/js", "tools/js"),
    ("tools/hook.js", "tools"),  # frida 注入脚本，缺失会导致调试启动失败
    ("tools/config/win", "tools/config/win"),  # 各 WMPF 版本偏移配置
    ("tools/config/wi32", "tools/config/wi32"),
    ("tools/wmpf_autodetect", "tools/wmpf_autodetect"),  # 无现成配置时现算偏移
)

# 明确用不到的重量级模块。frida 只在 package/devtools/engine.py 里被函数内惰性
# import，插件管理器走 CDP 不走 frida，排除后体积和杀软误报都明显下降。
# 构建完成后从 _internal 里删掉的冗余文件。PySide6 的 hook 会无条件收走整套 Qt
# DLL，光靠 --exclude-module 只去掉了 Python 绑定，DLL 还在，只能事后删。
TRIM_FILES: tuple[str, ...] = (
    "PySide6/opengl32sw.dll",  # 软件 OpenGL，20MB，Widgets 程序用不到
    "PySide6/Qt6Quick.dll",
    "PySide6/Qt6Qml.dll",
    "PySide6/Qt6QmlMeta.dll",
    "PySide6/Qt6QmlModels.dll",
    "PySide6/Qt6QmlWorkerScript.dll",
    "PySide6/Qt6Pdf.dll",
    "PySide6/Qt6VirtualKeyboard.dll",
    "PySide6/Qt6OpenGL.dll",
    "PySide6/Qt6Network.dll",
    "PySide6/Qt6Svg.dll",
    "PySide6/plugins/tls",
    "PySide6/plugins/networkinformation",
    # pywin32 是被 site-packages 里的 .pth 带进来的，项目里没有任何引用
    "pythonwin",
    "win32com",
    "win32",
)

EXCLUDED_MODULES: tuple[str, ...] = (
    "cryptography",  # 插件链路只用 pycryptodome(Crypto) 与 hashlib，20MB 的 Rust 绑定用不上
    "pytest",
    "_pytest",
    "IPython",
    "numpy",
    "PIL",
    "tkinter",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebView",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebSockets",
)


def write_build_info(*, mode: str, version: str, target: str) -> Path:
    """把构建模式、版本、后台地址写进产物；客户端靠它决定要不要连后台。"""
    target_path = BUILD_DIR / "bundle" / "build.json"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps({"mode": mode, "version": version, "target": target}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target_path


def generate_grpc_stub() -> bool:
    """重新生成客户端 gRPC stub；没装 grpcio-tools 就沿用已有的生成物。"""
    try:
        import grpc_tools.protoc  # noqa: F401
    except ImportError:
        print("[warn] 未安装 grpcio-tools，沿用已有的 grpc_stub 生成物")
        return False
    GRPC_STUB_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{PROTO_SOURCE.parent}",
            f"--python_out={GRPC_STUB_DIR}",
            f"--grpc_python_out={GRPC_STUB_DIR}",
            str(PROTO_SOURCE),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[warn] proto 生成失败：{result.stderr.strip()}")
        return False
    # 生成物里是顶层 import，放进子包后必须改成相对导入
    generated = GRPC_STUB_DIR / "plugin_pb2_grpc.py"
    generated.write_text(
        generated.read_text(encoding="utf-8").replace(
            "import plugin_pb2 as", "from . import plugin_pb2 as"
        ),
        encoding="utf-8",
    )
    return True


def issue_license(player_id: str, key_path: Path) -> Path:
    """用后台那把私钥在本地签发 license，省掉去后台点一下。

    复用 app.domain.license 而不是自己实现一遍，保证两边格式永远一致。
    """
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from app.domain import license as license_module
        from app.settings import settings
    except ImportError as exc:
        raise SystemExit(f"无法加载后台签发逻辑（缺依赖？）：{exc}")

    key_path.parent.mkdir(parents=True, exist_ok=True)
    settings.license_key_path = key_path
    payload = license_module.issue(player_id)
    target = BUILD_DIR / "bundle" / f"license-{player_id}.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(license_module.dumps(payload))
    print(f"[info] 已为 {player_id} 签发 license（{key_path.name}）")
    return target


def load_features_profile(path: Path) -> dict[str, dict[str, bool]]:
    """读功能开关 profile；未知键只warn不报错，避免拼错静默生效。"""
    if not path.is_file():
        print(f"[warn] 功能开关文件不存在，全部功能保持开启：{path}")
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[warn] 功能开关文件无法解析（{exc}），全部功能保持开启")
        return {}
    if not isinstance(raw, dict):
        print("[warn] 功能开关文件不是对象，全部功能保持开启")
        return {}
    profile: dict[str, dict[str, bool]] = {}
    for section, known in (("tasks", KNOWN_TASKS), ("panels", KNOWN_PANELS)):
        values = raw.get(section)
        if not isinstance(values, dict):
            continue
        accepted: dict[str, bool] = {}
        for key, value in values.items():
            if key not in known:
                print(f"[warn] 未知{section}键，忽略：{key}")
                continue
            accepted[key] = bool(value)
        profile[section] = accepted
    return profile


def write_bundle_features(profile: dict[str, dict[str, bool]]) -> Path | None:
    """把"被关掉的功能"写成产物内的 features.json；没有关闭项就不写文件。"""
    payload: dict[str, dict[str, bool]] = {}
    for section, values in profile.items():
        disabled = {key: False for key, value in values.items() if not value}
        if disabled:
            payload[section] = disabled
    if not payload:
        return None
    # 文件名必须是 features.json：--add-data 的目标目录只决定放哪儿，文件名沿用源文件名。
    target = BUILD_DIR / "bundle" / "features.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] 关闭的功能：{json.dumps(payload, ensure_ascii=False)}")
    return target


def trim(internal_dir: Path) -> int:
    """删除 TRIM_FILES 列出的冗余文件，返回释放的字节数。"""
    freed = 0
    for relative in TRIM_FILES:
        target = internal_dir / relative
        if not target.exists():
            continue
        if target.is_dir():
            for item in target.rglob("*"):
                if item.is_file():
                    freed += item.stat().st_size
            shutil.rmtree(target)
        else:
            freed += target.stat().st_size
            target.unlink()
    return freed


def build_command(
    *,
    windowed: bool,
    onefile: bool,
    exclude_frida: bool,
    keep_cryptography: bool,
    features_file: Path | None,
    build_file: Path,
    certs_dir: Path | None,
    exclude_grpc: bool,
) -> list[str]:
    """组装 PyInstaller 命令行。"""
    command: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir" if not onefile else "--onefile",
        "--console" if not windowed else "--windowed",
        "--noupx",  # UPX 会显著提高杀软误报率
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(ROOT / "build" / "pyi"),
        "--specpath",
        str(ROOT / "build"),
    ]
    for module in EXCLUDED_MODULES:
        if module == "cryptography" and keep_cryptography:
            continue
        command += ["--exclude-module", module]
    if exclude_frida:
        command += ["--exclude-module", "frida"]
    if exclude_grpc:
        # 调试版不连后台，连 gRPC 一起剔掉，省十几 MB
        command += ["--exclude-module", "grpc"]
    for source, destination in RESOURCES:
        if not (ROOT / source).exists():
            print(f"[warn] 资源缺失，跳过：{source}")
            continue
        # 必须用绝对路径：--add-data 的相对源路径按 spec 文件所在目录解析，不是 cwd。
        command += ["--add-data", f"{ROOT / source};{destination}"]
    if features_file is not None:
        command += ["--add-data", f"{features_file};."]
    command += ["--add-data", f"{build_file};."]
    if certs_dir is not None:
        command += ["--add-data", f"{certs_dir};certs"]
    command.append(str(ENTRY))
    return command


def ensure_pyinstaller() -> None:
    """缺少 PyInstaller 时自动安装到当前解释器。"""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[info] 安装 PyInstaller ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"], check=True
        )


def directory_size(path: Path) -> tuple[int, int]:
    """返回目录下文件总数与总字节数。"""
    total, count = 0, 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
                count += 1
            except OSError:
                continue
    return count, total


def sync_bundle_files(
    target: Path,
    *,
    build_file: Path,
    features_file: Path | None,
    certs_dir: Path | None,
    onefile: bool,
) -> None:
    """把构建信息／功能开关／证书放进产物。

    PyInstaller 跑的时候靠 --add-data 带进去；--skip-build 没人做这件事，
    所以改了 --target 或 --features 必须自己同步一次，否则产物里还是旧的。
    """
    if onefile:
        print("[warn] 单文件模式不支持 --skip-build 同步，请完整重新构建")
        return
    internal = target / "_internal"
    if not internal.is_dir():
        print(f"[warn] 产物目录异常，跳过同步：{internal}")
        return
    shutil.copy2(build_file, internal / build_file.name)
    if features_file is not None:
        shutil.copy2(features_file, internal / features_file.name)
    if certs_dir is not None and certs_dir.is_dir():
        destination = internal / "certs"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(certs_dir, destination)
    print(f"[info] 已同步 build.json/features.json/证书 到 {internal}")


def package(target: Path, version: str, onefile: bool, *, with_license: bool) -> Path:
    """产出 zip：带 license 的是发给玩家的分发包，不带的是上传后台的发布包。"""
    suffix = "player" if with_license else "upload"
    archive_path = DIST_DIR / f"{APP_NAME}-{version}-{suffix}.zip"
    if archive_path.exists():
        archive_path.unlink()
    if onefile:
        source_dir = DIST_DIR
        members = [target.name] + (["license.bin"] if with_license else [])
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in members:
                if (source_dir / name).exists():
                    archive.write(source_dir / name, name)
        return archive_path
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            # 上传包里绝不能带某个玩家的 license
            if not with_license and path.name == "license.bin":
                continue
            archive.write(path, path.relative_to(target.parent).as_posix())
    return archive_path


def report(target: Path) -> None:
    """打印产物体积概览与最大的前 15 个文件。"""
    if not target.exists():
        print(f"[error] 产物不存在：{target}")
        return
    if target.is_file():
        size = target.stat().st_size
        print(f"\n产物：{target}  {size / 1024 / 1024:.1f} MB")
        return
    count, total = directory_size(target)
    print(f"\n产物目录：{target}")
    print(f"文件数：{count}  总大小：{total / 1024 / 1024:.1f} MB")
    largest = sorted(
        (p for p in target.rglob("*") if p.is_file()),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )[:15]
    for item in largest:
        print(f"  {item.stat().st_size / 1024 / 1024:8.1f} MB  {item.relative_to(target)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="打包插件管理器为 Windows 可执行文件")
    parser.add_argument("--windowed", action="store_true", help="不显示控制台窗口")
    parser.add_argument(
        "--console",
        action="store_true",
        help="显示控制台窗口（release 默认不带，加这个可以带，便于看报错）",
    )
    parser.add_argument("--onefile", action="store_true", help="产出单文件 exe（体积对比用）")
    parser.add_argument(
        "--exclude-frida",
        action="store_true",
        help="排除 frida（默认保留：调试链路靠它 hook 小程序运行时，排除后无法启动调试）",
    )
    parser.add_argument(
        "--keep-cryptography", action="store_true", help="保留 cryptography（默认排除）"
    )
    parser.add_argument(
        "--features",
        default=str(DEFAULT_FEATURES),
        help=f"功能开关 profile（默认 {DEFAULT_FEATURES}）；关掉的任务不进默认配置、不注册调度、不显示",
    )
    parser.add_argument(
        "--mode",
        choices=(MODE_DEBUG, MODE_RELEASE),
        default=MODE_DEBUG,
        help="debug：不连后台、不带 gRPC；release：连后台做鉴权与更新（默认 debug）",
    )
    parser.add_argument("--version", default="0.0.0-dev", help="构建版本号，写进产物的 build.json")
    parser.add_argument("--target", default="", help="后台 gRPC 地址 host:port，release 必填")
    parser.add_argument(
        "--certs", default=str(DEFAULT_CERTS), help="客户端证书目录（release 用）"
    )
    parser.add_argument("--license", default="", help="把已有的 license.bin 放进产物")
    parser.add_argument(
        "--player-id",
        default="",
        help="直接用玩家ID在本地签发 license 并打进产物（与 --license 二选一）",
    )
    parser.add_argument(
        "--license-key", default=str(DEFAULT_LICENSE_KEY), help="签发用的 Ed25519 私钥"
    )
    parser.add_argument("--package", action="store_true", help="额外产出分发/上传用的 zip")
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="跳过 PyInstaller，直接拿现有 dist 产物封装（给第二个及以后的玩家出包时用，秒出）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    args = parser.parse_args()

    if not ENTRY.exists():
        print(f"[error] 入口不存在：{ENTRY}")
        return 1
    if args.mode == MODE_RELEASE and not args.target:
        print("[error] release 构建必须用 --target 指定后台地址")
        return 1
    if args.player_id and args.license:
        print("[error] --player-id 与 --license 只能用其中一个")
        return 1
    if args.player_id:
        args.license = str(issue_license(args.player_id.strip(), Path(args.license_key)))

    release = args.mode == MODE_RELEASE
    certs_dir = Path(args.certs) if release else None
    if release and not (certs_dir / "client.pem").is_file():
        print(f"[warn] 客户端证书不在 {certs_dir}，release 包将连不上后台")
    if release:
        generate_grpc_stub()

    features_file = write_bundle_features(load_features_profile(Path(args.features)))
    build_file = write_build_info(mode=args.mode, version=args.version, target=args.target)
    command = build_command(
        # release 默认不带控制台（玩家看到黑框会以为出错了），调试版默认带
        windowed=args.windowed or (release and not args.console),
        onefile=args.onefile,
        exclude_frida=args.exclude_frida,
        keep_cryptography=args.keep_cryptography,
        features_file=features_file,
        build_file=build_file,
        certs_dir=certs_dir if certs_dir and certs_dir.is_dir() else None,
        exclude_grpc=not release,
    )
    target = DIST_DIR / APP_NAME if not args.onefile else DIST_DIR / f"{APP_NAME}.exe"
    if args.skip_build:
        # 产物是通用的，换玩家只需换 license，不必重跑 PyInstaller。
        if not target.exists():
            print(f"[error] 没有可复用的产物：{target}")
            return 1
        print(f"[info] 跳过构建，复用现有产物：{target}")
        sync_bundle_files(
            target,
            build_file=build_file,
            features_file=features_file,
            certs_dir=certs_dir if certs_dir and certs_dir.is_dir() else None,
            onefile=args.onefile,
        )
    else:
        print("命令：\n  " + " ".join(command))
        if args.dry_run:
            return 0
        ensure_pyinstaller()
        result = subprocess.run(command, cwd=str(ROOT))
        if result.returncode != 0:
            print(f"[error] PyInstaller 失败，退出码 {result.returncode}")
            return result.returncode
        if not args.onefile:
            freed = trim(target / "_internal")
            print(f"裁剪冗余：释放 {freed / 1024 / 1024:.1f} MB")
        report(target)

    if args.license:
        source = Path(args.license)
        if not source.is_file():
            print(f"[error] license 不存在：{source}")
            return 1
        # onedir：放进 app 目录，解压后正好与 exe 同级；onefile：与 exe 一起放 dist 下
        destination = (target if not args.onefile else DIST_DIR) / "license.bin"
        shutil.copy2(source, destination)
        print(f"[info] license 已放入：{destination}")
        print(f"[info] 已放入 license：{source.name}（这是分发包，不要再拿去后台上传）")
    if args.package:
        archive = package(target, args.version, args.onefile, with_license=bool(args.license))
        print(f"[info] 分发/上传包：{archive}")
    print("\n提示：先用 --console 版本跑一次冒烟，确认资源读取正常再出 --windowed。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
