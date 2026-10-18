"""客户端连接模块端到端：真连一次 gRPC，验证 mTLS、握手与更新检查。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

import grpc
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "server" / "backend"
TMP = Path(tempfile.mkdtemp(prefix="e0e1-client-"))

os.environ["E0E1_DATA_DIR"] = str(TMP)
# 客户端 license.py 里烧的是部署公钥，所以这里必须用同一把私钥，签名才对得上
os.environ["E0E1_LICENSE_KEY_PATH"] = str(
    TMP / "license_ed25519.key"
)
os.environ["E0E1_DATABASE_URL"] = f"sqlite:///{TMP / 'client.db'}"
os.environ["E0E1_CERTS_DIR"] = str(BACKEND_ROOT / "certs")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import Player  # noqa: E402
from app.db.session import init_db, session_scope  # noqa: E402
from app.domain import license as server_license  # noqa: E402
from app.domain import updates as server_updates  # noqa: E402
from app.grpc.servicer import register  # noqa: E402
from app.settings import settings  # noqa: E402

from package.plugin_manager import build_info, license as client_license, server_client  # noqa: E402

# 后端 tools 是个带 __init__.py 的包，留在 sys.path 里会顶掉仓库根目录的 tools，
# 让同进程里的其它用例 import 错模块；导入完就撤掉。
sys.path.remove(str(BACKEND_ROOT))
sys.modules.pop("tools", None)

PORT = 50152


@pytest.fixture(scope="module", autouse=True)
def isolated_credentials():
    """测试自建密钥和证书，不依赖也不改动部署用凭据。"""
    import importlib.util
    from cryptography.hazmat.primitives import serialization
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import app.db.session as database
    previous_settings = (settings.data_dir, settings.license_key_path, settings.certs_dir, settings.database_url)
    previous_database = (database._engine, database.SessionLocal)
    settings.database_url = f"sqlite:///{TMP / 'isolated-client.db'}"
    database._engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    database.SessionLocal = sessionmaker(bind=database._engine, expire_on_commit=False)
    settings.data_dir = TMP
    settings.license_key_path = TMP / "license_ed25519.key"
    settings.certs_dir = TMP / "certs"
    spec = importlib.util.spec_from_file_location("test_gen_certs", BACKEND_ROOT / "tools/gen_certs.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generator.CERTS_DIR = settings.certs_dir
    generator.CLIENT_DIR = settings.certs_dir / "client"
    generator.main()
    original = client_license.LICENSE_PUBLIC_KEY
    client_license.LICENSE_PUBLIC_KEY = server_license._private_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    yield
    client_license.LICENSE_PUBLIC_KEY = original
    database._engine.dispose()
    database._engine, database.SessionLocal = previous_database
    settings.data_dir, settings.license_key_path, settings.certs_dir, settings.database_url = previous_settings


@pytest.fixture(scope="module")
def server():
    init_db()
    holder: dict = {}
    ready = threading.Event()

    async def runner():
        grpc_server = grpc.aio.server()
        register(grpc_server)
        grpc_server.add_secure_port(
            f"127.0.0.1:{PORT}",
            grpc.ssl_server_credentials(
                [
                    (
                        (settings.certs_dir / "server.key").read_bytes(),
                        (settings.certs_dir / "server.pem").read_bytes(),
                    )
                ],
                root_certificates=(settings.certs_dir / "ca.pem").read_bytes(),
                require_client_auth=True,
            ),
        )
        await grpc_server.start()
        holder["loop"] = asyncio.get_running_loop()
        holder["server"] = grpc_server
        holder["finished"] = asyncio.Event()
        ready.set()
        await grpc_server.wait_for_termination()
        await holder["finished"].wait()

    threading.Thread(target=lambda: asyncio.run(runner()), daemon=True).start()
    assert ready.wait(15), "gRPC 服务未能启动"
    yield holder["server"]
    try:
        asyncio.run_coroutine_threadsafe(holder["server"].stop(0), holder["loop"]).result(5)
    finally:
        holder["loop"].call_soon_threadsafe(holder["finished"].set)


@pytest.fixture
def release_client(tmp_path, monkeypatch):
    """把客户端伪装成 release 构建：指向本地服务，证书用仓库里那份。"""
    # server_client 里是 from .build_info import current as build_info，直接换掉该函数引用
    monkeypatch.setattr(
        server_client,
        "build_info",
        lambda: build_info.BuildInfo(mode="release", version="1.0.0", target=f"localhost:{PORT}"),
    )
    monkeypatch.setattr(
        server_client, "cert_dir", lambda: settings.certs_dir / "client"
    )

    def write_license(payload: dict | None) -> Path:
        path = tmp_path / "license.bin"
        if payload is not None:
            path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(client_license, "license_path", lambda: path)
        return path

    return write_license


def test_debug_build_skips_handshake(monkeypatch):
    monkeypatch.setattr(
        server_client, "build_info", lambda: build_info.BuildInfo(mode="debug", version="0.0.0-dev", target="")
    )
    result = server_client.handshake(player_id="1001", legion_name="某阴司")
    assert result.allowed and result.skipped


def test_release_handshake_allowed(server, release_client):
    with session_scope() as session:
        if session.query(Player).filter(Player.player_id == "1001").one_or_none() is None:
            session.add(Player(player_id="1001"))
    release_client(server_license.issue("1001"))
    result = server_client.handshake(player_id="1001", legion_name="测试阴司")
    assert result.allowed, result.message


def test_release_handshake_denied_on_mismatch(server, release_client):
    release_client(server_license.issue("1001"))
    result = server_client.handshake(player_id="9999", legion_name="")
    assert not result.allowed
    assert result.reason == "player_id_mismatch"


def test_release_handshake_without_license(server, release_client):
    release_client(None)
    result = server_client.handshake(player_id="1001", legion_name="")
    assert not result.allowed and result.reason == "no_license"


def test_offline_fallback_allows_matching_id(release_client, monkeypatch):
    """服务器连不上：绑定 id 与登录 id 一致就放行。"""
    monkeypatch.setattr(
        server_client,
        "build_info",
        lambda: build_info.BuildInfo(mode="release", version="1.0.0", target="127.0.0.1:59999"),
    )
    release_client(server_license.issue("1001"))
    result = server_client.handshake(player_id="1001", legion_name="某阴司")
    assert result.allowed and result.offline
    assert result.reason == "offline_ok"


def test_offline_fallback_rejects_mismatch(release_client, monkeypatch):
    """服务器连不上但账号对不上：照样拒绝。"""
    monkeypatch.setattr(
        server_client,
        "build_info",
        lambda: build_info.BuildInfo(mode="release", version="1.0.0", target="127.0.0.1:59999"),
    )
    release_client(server_license.issue("1001"))
    result = server_client.handshake(player_id="9999", legion_name="")
    assert not result.allowed and result.offline
    assert result.reason == "player_id_mismatch"


def test_offline_rejects_tampered_license(release_client, monkeypatch):
    """离线兜底也要验签：改了 player_id 的包不能靠改 JSON 白用。"""
    monkeypatch.setattr(
        server_client,
        "build_info",
        lambda: build_info.BuildInfo(mode="release", version="1.0.0", target="127.0.0.1:59999"),
    )
    payload = server_license.issue("1001")
    tampered = dict(payload, player_id="9999")  # 拿到别人的包，改成自己的号
    release_client(tampered)
    result = server_client.handshake(player_id="9999", legion_name="")
    assert not result.allowed
    assert result.reason == "invalid_license"


def test_offline_local_verify_matches_server(release_client):
    """客户端内置公钥与服务端的私钥必须是一对。"""
    payload = server_license.issue("1001")
    assert client_license.verify(payload)
    assert not client_license.verify(dict(payload, player_id="9999"))
    assert not client_license.verify(None)


def test_check_update_returns_plan(server, release_client):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("app/x.py", b"hello")
    with session_scope() as session:
        release = server_updates.import_release(
            session, archive=buffer.getvalue(), version="2.0.0", changelog="第二版", mandatory=True
        )
        session.flush()
        server_updates.publish(session, "2.0.0")

    plan = server_client.check_update({"app/x.py": "stale-hash"}, player_id="1001")
    assert plan is not None and plan["version"] == "2.0.0"
    assert plan["changed"][0]["path"] == "app/x.py"
    assert plan["mandatory"]


def test_debug_build_skips_update_check(monkeypatch):
    monkeypatch.setattr(
        server_client, "build_info", lambda: build_info.BuildInfo(mode="debug", version="0.0.0-dev", target="")
    )
    assert server_client.check_update({}, player_id="") is None


def test_release_handshake_accepts_second_member(server, release_client):
    with session_scope() as session:
        from app.db.models import Player
        if session.query(Player).filter(Player.player_id == "1002").one_or_none() is None:
            session.add(Player(player_id="1002"))
    release_client(server_license.issue(["1001", "1002"]))
    result = server_client.handshake(player_id="1002", legion_name="测试阴司")
    assert result.allowed and not result.offline
    result = server_client.handshake(player_id="9999", legion_name="")
    assert not result.allowed and result.reason == "player_id_mismatch"
