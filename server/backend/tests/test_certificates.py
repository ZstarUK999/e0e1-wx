"""Client certificate download: real HTTP authentication and exact ZIP allowlist."""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.domain.accounts import create_token, create_download_ticket
from app.http.routers.certificates import router
from app.settings import settings


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'certs_dir', tmp_path)
    monkeypatch.setattr(settings, 'jwt_secret', 'isolated-certificate-download-test-secret')
    client_dir = tmp_path / 'client'
    client_dir.mkdir()
    for name in ('ca.pem', 'client.pem', 'client.key'):
        (client_dir / name).write_bytes(('fixture-' + name).encode())
    # Extra sensitive files must never be included, even inside the client directory.
    for name in ('ca.key', 'server.key', 'license_ed25519.key'):
        (tmp_path / name).write_bytes(b'never-download')
        (client_dir / name).write_bytes(b'never-download')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, client_dir, {'Authorization': 'Bearer ' + create_token('test-admin')}


def test_certificate_download_requires_admin(endpoint):
    client, _, _ = endpoint
    assert client.get('/api/certificates/client.zip').status_code == 401
    assert client.get('/api/certificates/client.zip', headers={'Authorization':'Bearer invalid'}).status_code == 401
    ticket = create_download_ticket('1.2.3')
    assert client.get('/api/certificates/client.zip', headers={'Authorization':'Bearer '+ticket}).status_code == 401


def test_certificate_zip_allowlist_and_no_cache(endpoint):
    client, _, headers = endpoint
    response = client.get('/api/certificates/client.zip', headers=headers)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-type'] == 'application/zip'
    assert 'e0e1-client-certs.zip' in response.headers['content-disposition']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {'client/ca.pem', 'client/client.pem', 'client/client.key'}
        assert archive.read('client/client.key') == b'fixture-client.key'


def test_missing_and_empty_certificate_errors(endpoint):
    client, directory, headers = endpoint
    (directory/'client.key').unlink()
    response = client.get('/api/certificates/client.zip', headers=headers)
    assert response.status_code == 404 and 'client.key' in response.json()['detail']
    (directory/'client.key').write_bytes(b'')
    response = client.get('/api/certificates/client.zip', headers=headers)
    assert response.status_code == 503
