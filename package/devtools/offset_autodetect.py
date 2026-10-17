"""WMPF 偏移自动检测：本机出现没有现成配置的运行时版本时，用 frida 脚本现算偏移。

检测脚本是 frida/autodetect/win32.js 的裁剪副本（见 tools/wmpf_autodetect/win32.js），
只支持 Windows x64 的新版 WMPF（老版本都有现成配置，不会走到这里）。
"""
import json
import os
import tempfile
import threading
from pathlib import Path

AUTODETECT_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "tools" / "wmpf_autodetect" / "win32.js"

RESULT_MESSAGE = "wmpf-offsets"
ERROR_MESSAGE = "wmpf-offsets-error"

REQUIRED_TOP_LEVEL_KEYS = (
    "LoadStartHookOffset",
    "CDPFilterHookOffset",
    "CastToJsonHookOffset",
    "MiniAppConfigStructOffsets",
)
REQUIRED_STRUCT_KEYS = (
    "LaunchConfigOffsets",
    "RemoteDebugConfigOffsets",
    "SceneOffset",
    "WebSocketURLStringOffset",
    "RemoteDebugModeOffset",
)

_write_lock = threading.Lock()


def normalize_detected_config(version: int, config: dict) -> dict:
    """把脚本算出的偏移整理成 hook.js 能直接吃的配置（补 Version + 校验形状）。"""
    if not isinstance(config, dict):
        raise RuntimeError(f"自动检测返回了非对象结果：{type(config).__name__}")
    if "SceneOffsets" in config:
        # 老版链路（三个偏移的数组）不属于本副本支持的形状，避免写坏配置。
        raise RuntimeError("自动检测返回了 legacy 结构（SceneOffsets），本版本不支持")

    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in config]
    if missing:
        raise RuntimeError(f"自动检测缺少字段：{', '.join(missing)}")

    struct = config.get("MiniAppConfigStructOffsets")
    if not isinstance(struct, dict):
        raise RuntimeError("自动检测的 MiniAppConfigStructOffsets 不是对象")
    missing_struct = [key for key in REQUIRED_STRUCT_KEYS if key not in struct]
    if missing_struct:
        raise RuntimeError(f"自动检测的 MiniAppConfigStructOffsets 缺少字段：{', '.join(missing_struct)}")

    normalized = json.loads(json.dumps(config))
    # tools/hook.js 用 config.Version 决定挂 flue.dll 还是 WeChatAppEx.exe，脚本自己不带。
    normalized["Version"] = int(version)
    return normalized


def config_path_for(version: int, platform_dir: str = "win") -> Path:
    """返回某个版本对应的配置文件路径。"""
    from package.devtools.engine import tools_root

    return tools_root() / "config" / platform_dir / f"addresses.{int(version)}.json"


def persist_addresses_config(version: int, config: dict, platform_dir: str = "win") -> Path:
    """原子写入 addresses.<version>.json，返回落盘路径。"""
    path = config_path_for(version, platform_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    with _write_lock:
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return path


def detect_offsets_sync(pid: int, timeout: float = 180.0, frida=None) -> dict:
    """挂到指定 WMPF 进程算出偏移；失败抛 RuntimeError（带脚本里的原始报错）。"""
    if frida is None:
        import frida as frida_module

        frida = frida_module

    script_path = AUTODETECT_SCRIPT_PATH
    if not script_path.exists():
        raise RuntimeError(f"自动检测脚本缺失：{script_path}")

    script_content = script_path.read_text(encoding="utf-8")
    device = frida.get_local_device()
    session = device.attach(int(pid))
    script = None
    try:
        script = session.create_script(script_content)
        collected: dict = {}
        done = threading.Event()

        def on_message(message, data) -> None:
            payload = message.get("payload", None)
            if not isinstance(payload, dict):
                return
            kind = payload.get("type")
            if kind == RESULT_MESSAGE:
                collected["config"] = payload.get("config")
                done.set()
            elif kind == ERROR_MESSAGE:
                collected["error"] = payload.get("error") or "unknown error"
                done.set()

        script.on("message", on_message)
        script.load()
        if not done.wait(timeout=float(timeout)):
            raise RuntimeError(f"自动检测超时（{timeout:.0f}s）")
    finally:
        if script is not None:
            try:
                script.unload()
            except Exception:
                pass
        try:
            session.detach()
        except Exception:
            pass

    if "config" not in collected:
        error = str(collected.get("error") or "脚本未返回结果")
        if "flue.dll is not loaded" in error:
            error += "（请先在微信里打开任意小程序，让 WMPF 加载 flue.dll 后重试）"
        raise RuntimeError(error)
    return collected["config"]
