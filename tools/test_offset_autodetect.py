"""WMPF 偏移自动检测兜底的纯逻辑测试（不接触真实 WMPF / frida）。"""

import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def modules():
    try:
        return (
            importlib.import_module("package.devtools.engine"),
            importlib.import_module("package.devtools.offset_autodetect"),
        )
    except ModuleNotFoundError as exc:
        if exc.name.startswith("package.devtools"):
            pytest.fail("尚未实现 devtools 偏移自动检测")
        raise


def detected(version_offsets=True):
    return {
        "LoadStartHookOffset": "0x2d5a240",
        "CDPFilterHookOffset": "0x385e1d0",
        "CastToJsonHookOffset": "0x9f0abb0",
        "MiniAppConfigStructOffsets": {
            "LaunchConfigOffsets": [64, 1584, 8],
            "RemoteDebugConfigOffsets": [1512, 16],
            "SceneOffset": 456,
            "WebSocketURLStringOffset": 624,
            "RemoteDebugModeOffset": 724,
        },
    }


# ── fake frida ──

class FakeScript:
    def __init__(self, payloads):
        self.payloads = payloads
        self.handler = None
        self.unloaded = False

    def on(self, name, callback):
        self.handler = callback

    def load(self):
        for payload in self.payloads:
            self.handler({"type": "send", "payload": payload}, None)

    def unload(self):
        self.unloaded = True


class FakeSession:
    def __init__(self, payloads):
        self.payloads = payloads
        self.script = FakeScript(payloads)
        self.detached = False

    def create_script(self, content):
        self.content = content
        return self.script

    def detach(self):
        self.detached = True


class FakeDevice:
    def __init__(self, payloads):
        self.session = FakeSession(payloads)
        self.attaches=[]

    def attach(self, pid):
        self.attaches.append(pid)
        self.pid = pid
        return self.session


class FakeFrida:
    def __init__(self, payloads):
        self.device = FakeDevice(payloads)

    def get_local_device(self):
        return self.device


def test_detect_wmpf_version_prefers_highest_directory(tmp_path, monkeypatch):
    engine, _ = modules()
    runtime = tmp_path / "RadiumWMPF"
    (runtime / "25715").mkdir(parents=True)
    (runtime / "25799").mkdir()
    (runtime / "30000").mkdir()
    # 只给旧版本放配置：不能因为它有配置就选它
    config_dir = tmp_path / "tools" / "config" / "win"
    config_dir.mkdir(parents=True)
    (config_dir / "addresses.25715.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(engine, "tools_root", lambda: tmp_path / "tools")
    proc_path = runtime / "WeChatAppEx.exe"
    assert engine.DebugEngine._detect_wmpf_version(None, str(proc_path)) == 30000


def test_detect_wmpf_version_reads_directory_in_path(tmp_path, monkeypatch):
    engine, _ = modules()
    target = tmp_path / "RadiumWMPF" / "25799"
    target.mkdir(parents=True)
    monkeypatch.setattr(engine, "tools_root", lambda: tmp_path / "tools")
    assert engine.DebugEngine._detect_wmpf_version(None, str(target / "WeChatAppEx.exe")) == 25799


def test_normalize_detected_config_adds_version():
    _, offset_autodetect = modules()
    result = offset_autodetect.normalize_detected_config(25799, detected())
    assert result["Version"] == 25799
    assert result["LoadStartHookOffset"] == "0x2d5a240"


def test_normalize_detected_config_rejects_missing_key():
    _, offset_autodetect = modules()
    broken = detected()
    del broken["CastToJsonHookOffset"]
    with pytest.raises(RuntimeError) as info:
        offset_autodetect.normalize_detected_config(25799, broken)
    assert "CastToJsonHookOffset" in str(info.value)


def test_normalize_detected_config_rejects_legacy_shape():
    _, offset_autodetect = modules()
    legacy = {"LoadStartHookOffset": "0x1", "CDPFilterHookOffset": "0x2", "SceneOffsets": [64, 1568, 8]}
    with pytest.raises(RuntimeError) as info:
        offset_autodetect.normalize_detected_config(18955, legacy)
    assert "legacy" in str(info.value)


def test_persist_addresses_config_writes_atomically(tmp_path, monkeypatch):
    engine, offset_autodetect = modules()
    monkeypatch.setattr(engine, "tools_root", lambda: tmp_path / "tools")

    path = offset_autodetect.persist_addresses_config(25799, detected() | {"Version": 25799})
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["Version"] == 25799
    assert not list(path.parent.glob("*.tmp"))

    # 覆盖写
    offset_autodetect.persist_addresses_config(25799, detected() | {"Version": 25799, "Note": "again"})
    assert json.loads(path.read_text(encoding="utf-8"))["Note"] == "again"


def test_detect_offsets_sync_success(monkeypatch):
    _, offset_autodetect = modules()
    monkeypatch.setattr(offset_autodetect, "AUTODETECT_SCRIPT_PATH", Path(__file__).resolve())
    fake = FakeFrida([{"type": "wmpf-offsets", "config": detected()}])
    result = offset_autodetect.detect_offsets_sync(1234, timeout=5, frida=fake)
    assert result["LoadStartHookOffset"] == "0x2d5a240"
    assert fake.device.session.detached is True
    assert fake.device.session.script.unloaded is True


def test_detect_offsets_sync_error(monkeypatch):
    _, offset_autodetect = modules()
    monkeypatch.setattr(offset_autodetect, "AUTODETECT_SCRIPT_PATH", Path(__file__).resolve())
    fake = FakeFrida([{"type": "wmpf-offsets-error", "error": "flue.dll is not loaded"}])
    with pytest.raises(RuntimeError) as info:
        offset_autodetect.detect_offsets_sync(1234, timeout=5, frida=fake)
    assert "flue.dll is not loaded" in str(info.value)
    assert "打开任意小程序" in str(info.value)


def test_detect_offsets_sync_timeout(monkeypatch):
    _, offset_autodetect = modules()
    monkeypatch.setattr(offset_autodetect, "AUTODETECT_SCRIPT_PATH", Path(__file__).resolve())
    fake = FakeFrida([])
    with pytest.raises(RuntimeError) as info:
        offset_autodetect.detect_offsets_sync(1234, timeout=0.05, frida=fake)
    assert "超时" in str(info.value)


def test_detect_offsets_sync_requires_script(monkeypatch, tmp_path):
    _, offset_autodetect = modules()
    monkeypatch.setattr(offset_autodetect, "AUTODETECT_SCRIPT_PATH", tmp_path / "missing.js")
    with pytest.raises(RuntimeError) as info:
        offset_autodetect.detect_offsets_sync(1234, timeout=5, frida=FakeFrida([]))
    assert "缺失" in str(info.value)


def test_start_frida_sync_falls_back_to_autodetect(tmp_path, monkeypatch):
    """配置缺失时：发进度提示 → 检测 → 落盘 → 清空提示，然后照常注入 hook。"""
    engine, offset_autodetect = modules()
    monkeypatch.setattr(engine, "tools_root", lambda: tmp_path / "tools")

    tools = tmp_path / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "hook.js").write_text("// @@CONFIG@@", encoding="utf-8")

    fake_frida = FakeFrida([])
    statuses = []

    class StubEngine(engine.DebugEngine):
        def __init__(self):
            self.logger = type("L", (), {"info": staticmethod(lambda *a: None),
                                         "error": staticmethod(lambda *a: None)})()
            self._status_callbacks = []
            self.status = {}

        def _notify_status(self, key, value):
            statuses.append((key, value))

    monkeypatch.setattr(engine.DebugEngine, "_load_frida", lambda self: fake_frida)
    monkeypatch.setattr(
        engine.DebugEngine,
        "_find_wmpf_pids_win",
        lambda self: ([1234], 25799),
    )
    monkeypatch.setattr(
        offset_autodetect, "detect_offsets_sync", lambda pid, timeout=180.0, frida=None, session=None: detected()
    )

    instance = StubEngine.__new__(StubEngine)
    instance.options=type("Options",(),{"channel":"wechat"})()
    instance.__init__()
    session, script = engine.DebugEngine._start_frida_sync(instance)

    config_path = tools / "config" / "win" / "addresses.25799.json"
    assert config_path.exists()
    assert json.loads(config_path.read_text(encoding="utf-8"))["Version"] == 25799
    assert statuses == [
        ("message", "正在自动检测 25799 偏移…"),
        ("offset_detect", True),
        ("offset_detect", False),
        ("message", ""),
    ]
    assert fake_frida.device.attaches==[1234]
    assert session is fake_frida.device.session
    assert script is fake_frida.device.session.script
    assert "@@CONFIG@@" not in fake_frida.device.session.content
    instance.frida_session=session;instance.frida_script=script
    script.handler()  # destroyed: the surviving listener is no longer usable
    assert statuses[-1]==('frida',False)
    statuses.clear();instance.frida_session=object()
    script.handler()
    assert statuses==[]  # a late old-session event cannot invalidate a new one



def test_start_frida_sync_reports_autodetect_failure(tmp_path, monkeypatch):
    engine, offset_autodetect = modules()
    monkeypatch.setattr(engine, "tools_root", lambda: tmp_path / "tools")
    (tmp_path / "tools").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tools" / "hook.js").write_text("// @@CONFIG@@", encoding="utf-8")

    monkeypatch.setattr(engine.DebugEngine, "_load_frida", lambda self: FakeFrida([]))
    monkeypatch.setattr(engine.DebugEngine, "_find_wmpf_pids_win", lambda self: ([1234], 25799))
    monkeypatch.setattr(
        offset_autodetect,
        "detect_offsets_sync",
        lambda pid, timeout=180.0, frida=None, session=None: (_ for _ in ()).throw(RuntimeError("flue.dll is not loaded")),
    )

    instance = engine.DebugEngine.__new__(engine.DebugEngine)
    instance.options=type("Options",(),{"channel":"wechat"})()
    instance.logger = type("L", (), {"info": staticmethod(lambda *a: None),
                                     "error": staticmethod(lambda *a: None)})()
    instance._status_callbacks = []
    instance.status = {}
    with pytest.raises(RuntimeError) as info:
        engine.DebugEngine._start_frida_sync(instance)
    assert "25799" in str(info.value) and "flue.dll" in str(info.value)
    assert instance.status["message"] == ""  # 失败也要把提示清掉


def test_find_available_cdp_port_skips_listener():
    """探测不能带 SO_REUSEADDR，否则会把已占用的端口报成可用。"""
    import socket

    worker_module = importlib.import_module("package.devtools.worker")
    # 探测与引擎一样用 0.0.0.0：Windows 下 127.0.0.1 与 0.0.0.0 的冲突判定不等价。
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("0.0.0.0", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        picked = worker_module.find_available_cdp_port(start=port)
        assert picked != port
        assert worker_module.port_available(port) is False
    finally:
        listener.close()


def test_port_available_detects_listener():
    """worker 靠它区分「9421 被占」和「CDP 端口被占」，不能把已监听端口判成可用。"""
    import socket

    worker_module = importlib.import_module("package.devtools.worker")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("0.0.0.0", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert worker_module.port_available(port) is False
    finally:
        listener.close()
    assert worker_module.port_available(port) is True
    # 顺带确认 9421 这类固定端口的判定也走同一套规则
    assert isinstance(worker_module.port_available(9421), bool)


def test_worker_status_message_hint_wins():
    """engine 借 message 传的一次性提示要盖过 running_message()。"""
    worker_module = importlib.import_module("package.devtools.worker")

    class Stub(worker_module.AsyncDevtoolsWorker):
        def __init__(self):
            self.state = {"status": "starting", "miniapp": False, "miniapp_epoch": 0}
            self.injected_js_signatures = {}
            self.emitted = 0

        def emit_state(self):
            self.emitted += 1

        def mark_runtime_toggle_scripts_stale(self, **kwargs):
            return None

        def schedule_runtime_toggle_auto_restore(self, **kwargs):
            return None

    stub = Stub.__new__(Stub)
    stub.state = {"status": "starting", "miniapp": False, "miniapp_epoch": 0}
    stub.injected_js_signatures = {}
    stub.emitted = 0

    worker_module.AsyncDevtoolsWorker.handle_bridge_status(stub, {"message": "正在自动检测 25799 偏移…"})
    assert stub.state["message"] == "正在自动检测 25799 偏移…"

    worker_module.AsyncDevtoolsWorker.handle_bridge_status(stub, {"message": "", "frida": True})
    assert stub.state["message"] == stub.running_message()


def test_autodetect_reuses_caller_session_without_detaching_it(monkeypatch):
    engine, module=modules()
    fake=FakeFrida([{'type':module.RESULT_MESSAGE,'config':detected()}])
    session=fake.device.session
    monkeypatch.setattr(fake.device,'attach',lambda pid:(_ for _ in ()).throw(AssertionError('no second attach')))
    result=module.detect_offsets_sync(1234,timeout=5,frida=fake,session=session)
    assert result==detected() and session.script.unloaded and not session.detached
