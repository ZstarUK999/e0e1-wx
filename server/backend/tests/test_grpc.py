"""gRPC 端到端：真起服务、真走 mTLS，覆盖放路与每条拒绝分支。"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import grpc
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="e0e1-grpc-"))

# 必须在 import app.* 之前把环境定好：settings 在导入时就固化了
os.environ["E0E1_DATA_DIR"] = str(TMP)
os.environ["E0E1_LICENSE_KEY_PATH"] = str(TMP / "license.key")
os.environ["E0E1_DATABASE_URL"] = f"sqlite:///{TMP / 'grpc.db'}"
os.environ["E0E1_CERTS_DIR"] = str(BACKEND_ROOT / "certs")

sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import init_db, session_scope  # noqa: E402
from app.db.models import Player  # noqa: E402
from app.domain import license as license_module, updates  # noqa: E402
from app.grpc import plugin_pb2, plugin_pb2_grpc  # noqa: E402
from app.grpc.servicer import register  # noqa: E402
from app.settings import settings  # noqa: E402

# 直接改 settings 而不是只设环境变量：同一进程里 app.settings 可能已经被别的
# 测试模块导入过，那时环境变量就不再生效了。
import app.db.session as db_session  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

settings.data_dir = TMP
settings.license_key_path = TMP / "license.key"
settings.database_url = f"sqlite:///{TMP / 'grpc.db'}"
settings.certs_dir = BACKEND_ROOT / "certs"
db_session._engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
db_session.SessionLocal = sessionmaker(bind=db_session._engine, expire_on_commit=False)

PORT = 50151


@pytest.fixture(scope="module")
def server():
    """在独立线程的事件循环里起服务：grpc.aio 的服务端必须在使用它的那个循环里创建。"""
    import threading

    init_db()
    ca = (settings.certs_dir / "ca.pem").read_bytes()
    server_cert = (settings.certs_dir / "server.pem").read_bytes()
    server_key = (settings.certs_dir / "server.key").read_bytes()
    holder: dict = {}
    ready = threading.Event()

    async def runner():
        grpc_server = grpc.aio.server()
        register(grpc_server)
        grpc_server.add_secure_port(
            f"127.0.0.1:{PORT}",
            grpc.ssl_server_credentials(
                [(server_key, server_cert)], root_certificates=ca, require_client_auth=True
            ),
        )
        await grpc_server.start()
        holder["loop"] = asyncio.get_running_loop()
        holder["server"] = grpc_server
        ready.set()
        await grpc_server.wait_for_termination()

    thread = threading.Thread(target=lambda: asyncio.run(runner()), daemon=True)
    thread.start()
    assert ready.wait(15), "gRPC 服务未能启动"
    yield holder["server"]
    loop = holder.get("loop")
    if loop is not None:
        asyncio.run_coroutine_threadsafe(holder["server"].stop(0), loop).result(5)


@pytest.fixture
def stub(server):
    client_dir = settings.certs_dir / "client"
    credentials = grpc.ssl_channel_credentials(
        root_certificates=(client_dir / "ca.pem").read_bytes(),
        private_key=(client_dir / "client.key").read_bytes(),
        certificate_chain=(client_dir / "client.pem").read_bytes(),
    )
    channel = grpc.secure_channel(f"localhost:{PORT}", credentials)
    yield plugin_pb2_grpc.PluginServiceStub(channel)
    channel.close()


def _handshake(stub, payload, login_id, version="1.0.0"):
    request = plugin_pb2.HandshakeRequest(
        license=plugin_pb2.License(
            license_id=payload.get("license_id", ""),
            player_id=payload.get("player_id", ""),
            issued_at=payload.get("issued_at", ""),
            nonce=payload.get("nonce", ""),
            signature=payload.get("signature", ""),
        ),
        login_player_id=login_id,
        guild_name="测试阴司",
        client_version=version,
    )
    return stub.Handshake(request, timeout=15)


@pytest.fixture
def whitelisted():
    with session_scope() as session:
        if session.query(Player).filter(Player.player_id == "1001").one_or_none() is None:
            session.add(Player(player_id="1001", nickname="甲"))
    return "1001"


def test_handshake_allowed(stub, whitelisted):
    payload = license_module.issue("1001")
    response = _handshake(stub, payload, "1001")
    assert response.allowed
    assert response.reason == "ok"


def test_handshake_rejects_tampered_license(stub, whitelisted):
    payload = license_module.issue("1001")
    payload["player_id"] = "1002"
    response = _handshake(stub, payload, "1002")
    assert not response.allowed
    assert response.reason == "invalid_license"


def test_handshake_rejects_id_mismatch(stub, whitelisted):
    """包绑定 1001，游戏里登录的是 1002。"""
    payload = license_module.issue("1001")
    response = _handshake(stub, payload, "1002")
    assert not response.allowed
    assert response.reason == "player_id_mismatch"


def test_handshake_rejects_unknown_player(stub):
    payload = license_module.issue("9999")
    response = _handshake(stub, payload, "9999")
    assert not response.allowed
    assert response.reason == "player_not_allowed"


def test_disabled_player_cannot_pass(stub):
    with session_scope() as session:
        session.add(Player(player_id="2002", enabled=False))
    payload = license_module.issue("2002")
    assert not _handshake(stub, payload, "2002").allowed


def test_check_update_returns_changed_files(stub, whitelisted):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("app/x.py", b"hello")
        archive.writestr("app/exe.exe", b"binary")
    with session_scope() as session:
        release = updates.import_release(
            session, archive=buffer.getvalue(), version="9.9.9", changelog="测试", mandatory=True
        )
        session.flush()
        updates.publish(session, "9.9.9")

    response = stub.CheckUpdate(
        plugin_pb2.UpdateRequest(client_version="1.0.0", player_id="1001", files=[]), timeout=30
    )
    assert response.version == "9.9.9"
    assert response.mandatory
    assert {item.path for item in response.changed} == {"app/x.py", "app/exe.exe"}
    assert all(item.url.startswith("http") for item in response.changed)

    up_to_date = stub.CheckUpdate(
        plugin_pb2.UpdateRequest(
            client_version="9.9.9",
            player_id="1001",
            files=[
                plugin_pb2.FileEntry(path="app/x.py", sha256=updates.sha256_of(b"hello")),
                plugin_pb2.FileEntry(path="app/exe.exe", sha256=updates.sha256_of(b"binary")),
            ],
        ),
        timeout=30,
    )
    assert list(up_to_date.changed) == []


def test_mandatory_update_is_reported(stub, whitelisted):
    payload = license_module.issue("1001")
    response = _handshake(stub, payload, "1001", version="1.0.0")
    assert response.latest_version == "9.9.9"
    assert response.update_required
