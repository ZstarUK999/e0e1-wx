"""domain 层测试：license 签验、握手裁决、更新 diff。"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, Player  # noqa: E402
from app.domain import auth, license as license_module, updates  # noqa: E402
from app.settings import settings  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    """每个用例一份独立 SQLite，私钥和发布目录也隔离。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "license_key_path", tmp_path / "license.key")
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    finally:
        session.close()


# ── license ──


def test_issued_license_verifies():
    payload = license_module.issue("123456")
    assert license_module.verify(payload)


def test_tampered_player_id_fails():
    payload = license_module.issue("123456")
    payload["player_id"] = "999999"
    assert not license_module.verify(payload)


def test_forged_signature_fails():
    payload = license_module.issue("123456")
    payload["signature"] = "AAAA" + payload["signature"][4:]
    assert not license_module.verify(payload)


def test_license_roundtrip_file():
    payload = license_module.issue("123456")
    restored = license_module.loads(license_module.dumps(payload))
    assert restored == payload
    assert license_module.verify(restored)


# ── 握手裁决 ──


def test_handshake_rejects_bad_license():
    verdict, bound = auth.evaluate(license_payload=None, login_player_id="123")
    assert not verdict.allowed and verdict.reason == auth.REASON_BAD_LICENSE
    assert bound == ""


def test_handshake_rejects_id_mismatch():
    payload = license_module.issue("123456")
    verdict, bound = auth.evaluate(license_payload=payload, login_player_id="999")
    assert not verdict.allowed and verdict.reason == auth.REASON_ID_MISMATCH
    assert bound == "123456"


def test_handshake_accepts_only_whitelisted(db):
    payload = license_module.issue("123456")
    verdict, bound = auth.evaluate(license_payload=payload, login_player_id="123456")
    assert verdict is None  # 还要查白名单

    assert auth.check_whitelist(db, bound).reason == auth.REASON_NOT_ALLOWED

    db.add(Player(player_id="123456"))
    db.flush()
    assert auth.check_whitelist(db, bound).allowed


def test_disabled_player_is_revoked(db):
    db.add(Player(player_id="123456", enabled=False))
    db.flush()
    assert not auth.check_whitelist(db, "123456").allowed


def test_record_stores_guild_and_result(db):
    db.add(Player(player_id="123456"))
    db.flush()
    auth.record(
        db,
        verdict=auth.Verdict.ok("123456"),
        bound_player_id="123456",
        guild="测试阴司",
        client_version="1.2.0",
        remote="127.0.0.1:50000",
        player_name="夜行客",
    )
    db.flush()
    from app.db.models import HandshakeLog

    row = db.query(HandshakeLog).one()
    assert row.allowed and row.guild == "测试阴司" and row.client_version == "1.2.0"
    assert row.player_name == "夜行客"
    player = db.query(Player).one()
    assert player.guild == "测试阴司"
    assert player.role_name == "夜行客"


# ── 更新 ──


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in entries.items():
            archive.writestr(path, data)
    return buffer.getvalue()


def test_import_and_diff(db):
    release = updates.import_release(
        db,
        archive=_zip({"app/_internal/x.py": b"hello", "app/exe.exe": b"binary"}),
        version="1.0.0",
        changelog="首个版本",
        mandatory=False,
    )
    db.flush()
    assert release.file_count == 2

    changed, removed = updates.diff(db, release, {})
    assert {item["path"] for item in changed} == {"app/_internal/x.py", "app/exe.exe"}
    assert removed == []

    up_to_date, _ = updates.diff(
        db, release, {"app/_internal/x.py": updates.sha256_of(b"hello"),
                      "app/exe.exe": updates.sha256_of(b"binary")}
    )
    assert up_to_date == []


def test_diff_ignores_license_and_staging(db):
    """本地的 license.bin 和 _staging 不能被当成多余文件删掉。"""
    release = updates.import_release(
        db, archive=_zip({"app/x.py": b"a"}), version="1.0.0", changelog="", mandatory=False
    )
    db.flush()
    _, removed = updates.diff(db, release, {"license.bin": "deadbeef", "_staging/1.1.0/y": "x"})
    assert removed == []


def test_import_strips_top_level_dir(db):
    release = updates.import_release(
        db,
        archive=_zip({"e0e1-wx-plugins/app/x.py": b"a"}),
        version="2.0.0",
        changelog="",
        mandatory=False,
    )
    db.flush()
    assert updates.manifest(db, release).keys() == {"app/x.py"}


def test_publish_keeps_single_enabled(db):
    updates.import_release(db, archive=_zip({"a": b"1"}), version="1.0.0", changelog="", mandatory=False)
    updates.import_release(db, archive=_zip({"a": b"2"}), version="1.1.0", changelog="", mandatory=False)
    db.flush()
    updates.publish(db, "1.0.0")
    updates.publish(db, "1.1.0")
    db.flush()
    current = updates.current_release(db)
    assert current is not None and current.version == "1.1.0"


def test_player_package_contains_app_and_license(db):
    """一键出包：通用文件 + 该玩家的 license，两者缺一不可。"""
    from app.domain import packages

    updates.import_release(db, archive=_zip({"app/x.py": b"a"}), version="3.0.0", changelog="", mandatory=False)
    db.flush()
    updates.publish(db, "3.0.0")
    db.flush()

    target, version = packages.build_player_package(db, "1001")
    assert version == "3.0.0"
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "e0e1-wx-plugins/license.bin" in names
        assert "e0e1-wx-plugins/app/x.py" in names
        payload = license_module.loads(archive.read("e0e1-wx-plugins/license.bin"))
    assert payload["player_id"] == "1001"
    assert license_module.verify(payload)


def test_player_package_needs_published_release(db):
    from app.domain import packages

    with pytest.raises(ValueError, match="生效版本"):
        packages.build_player_package(db, "1001")


def test_rollback_by_republishing_old(db):
    """回滚 = 重新启用旧版本，diff 自然把文件改回去。"""
    updates.import_release(db, archive=_zip({"a": b"1"}), version="1.0.0", changelog="", mandatory=False)
    updates.import_release(db, archive=_zip({"a": b"2"}), version="1.1.0", changelog="", mandatory=False)
    db.flush()
    updates.publish(db, "1.1.0")
    db.flush()
    updates.publish(db, "1.0.0")  # 回滚
    db.flush()
    release = updates.current_release(db)
    changed, _ = updates.diff(db, release, {"a": updates.sha256_of(b"2")})
    assert changed[0]["sha256"] == updates.sha256_of(b"1")


# Multi-player packages: signatures, local/offline gate, protobuf and admin selection.
def test_multi_player_license_cross_verifies_and_binds_current_player(db, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from package.plugin_manager import license as client, server_client
    key = license_module._private_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(client, "LICENSE_PUBLIC_KEY", key)
    payload = license_module.issue(["1001", "1002", "1001"])
    assert payload["player_ids"] == ["1001", "1002"]
    assert license_module.verify(payload) and client.verify(payload)
    for player_id in ("1001", "1002"):
        assert client.bound_player_id(payload, login_player_id=player_id) == (player_id, "")
        assert server_client._offline_verdict(payload, player_id).allowed
        verdict, bound = auth.evaluate(license_payload=payload, login_player_id=player_id)
        assert verdict is None and bound == player_id
    assert not server_client._offline_verdict(payload, "9999").allowed
    assert auth.evaluate(license_payload=payload, login_player_id="9999")[0].reason == auth.REASON_ID_MISMATCH
    legacy = license_module.issue("1001")
    assert client.verify(legacy) and license_module.verify(legacy)
    for bad in (dict(payload, player_ids=["1001", "9999"]), dict(payload, player_ids=["1001"]), dict(payload, player_ids=[]), dict(payload, player_id="1002"), dict(legacy, player_ids=["1001", "9999"])):
        assert not client.verify(bad) and not license_module.verify(bad)
    removed = dict(payload);removed.pop("player_ids")
    assert not client.verify(removed) and not license_module.verify(removed)


def test_multi_player_proto_roundtrip(db):
    from app.grpc import plugin_pb2
    from app.grpc.servicer import _license_from
    for ids in ("1001", ["1001", "1002"]):
        payload = license_module.issue(ids)
        request = plugin_pb2.HandshakeRequest(license=plugin_pb2.License(**payload), login_player_id="1001")
        restored = _license_from(plugin_pb2.HandshakeRequest.FromString(request.SerializeToString()))
        assert restored == payload
        assert license_module.verify(restored)


def test_multi_package_selection_and_unique_archive(db):
    import asyncio
    from fastapi import HTTPException
    from app.http.routers.players import PackageIn, download_selected_package
    from app.domain import packages
    db.add_all([Player(player_id="1001"), Player(player_id="1002"), Player(player_id="1003", enabled=False)])
    updates.import_release(db, archive=_zip({"app/main.py": b"app"}), version="multi-1", changelog="", mandatory=False)
    db.flush();updates.publish(db, "multi-1");db.flush()
    response = download_selected_package(PackageIn(player_ids=["1001", "1002", "1001"]), db, "admin")
    with zipfile.ZipFile(response.path) as archive:
        payload = license_module.loads(archive.read("e0e1-wx-plugins/license.bin"))
        assert payload["player_ids"] == ["1001", "1002"] and license_module.verify(payload)
        assert archive.read("e0e1-wx-plugins/app/main.py") == b"app"
        assert archive.namelist().count("e0e1-wx-plugins/license.bin") == 1
    other, _ = packages.build_player_package(db, ["1001", "1002"])
    assert str(other) != str(response.path)
    asyncio.run(response.background());assert not Path(response.path).exists()
    for ids in ([], ["missing"], ["1001", "1003"], [""]):
        with pytest.raises(HTTPException):
            download_selected_package(PackageIn(player_ids=ids), db, "admin")
    assert not auth.check_whitelist(db, "1003").allowed
