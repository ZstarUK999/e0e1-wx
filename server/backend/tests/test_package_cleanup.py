"""Player package expiry and application lifecycle scheduling."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import packages
from app.settings import settings


def test_cleanup_respects_age_and_storage_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    now = 200000.0
    monkeypatch.setattr(packages.time, 'time', lambda: now)
    directory = tmp_path / 'packages'
    directory.mkdir()
    files = {
        'e0e1-wx-plugins-old-1players-abc.zip': now - 86401,
        'e0e1-wx-plugins-boundary-1players-abc.zip': now - 86400,
        'e0e1-wx-plugins-new-2players-abc.zip': now - 86399,
        'unrelated.zip': 1,
        'license.bin': 1,
    }
    for name, timestamp in files.items():
        path = directory / name
        path.write_bytes(b'package')
        os.utime(path, (timestamp, timestamp))
    release = tmp_path / 'releases' / 'e0e1-wx-plugins-old.zip'
    release.parent.mkdir()
    release.write_bytes(b'keep')
    os.utime(release, (1, 1))
    assert packages.cleanup_expired_packages() == 2
    assert sorted(p.name for p in directory.iterdir()) == sorted([
        'e0e1-wx-plugins-new-2players-abc.zip', 'unrelated.zip', 'license.bin',
    ])
    assert release.exists()
    assert packages.cleanup_expired_packages() == 0


def test_missing_package_directory_is_harmless(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    assert packages.cleanup_expired_packages() == 0
    assert not (tmp_path / 'packages').exists()


def test_one_delete_failure_does_not_abort_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    directory = tmp_path / 'packages'
    directory.mkdir()
    for name in ('locked', 'old'):
        path = directory / f'e0e1-wx-plugins-{name}.zip'
        path.touch()
        os.utime(path, (1, 1))
    original = Path.unlink

    def unlink(path, *args, **kwargs):
        if path.name.endswith('locked.zip'):
            raise PermissionError('busy')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', unlink)
    assert packages.cleanup_expired_packages() == 1
    assert (directory / 'e0e1-wx-plugins-locked.zip').exists()


def test_cleanup_runs_on_startup_periodically_and_stops(monkeypatch):
    from app import http
    calls = []

    async def cleanup():
        calls.append('cleanup')

    original_sleep = asyncio.sleep
    started = asyncio.Event()

    async def sleep(seconds):
        assert seconds == 3600
        if len(calls) == 1:
            await original_sleep(0)
        else:
            started.set()
            await asyncio.Future()

    monkeypatch.setattr(http, '_cleanup_packages', cleanup)
    monkeypatch.setattr(http.asyncio, 'sleep', sleep)

    async def run():
        async with http.lifespan(http.create_app()):
            assert calls == ['cleanup']
            await asyncio.wait_for(started.wait(), timeout=2)
            assert calls == ['cleanup', 'cleanup']

    asyncio.run(run())
