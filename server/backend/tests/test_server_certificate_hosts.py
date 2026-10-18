import importlib.util
from pathlib import Path
import ipaddress
import pytest
from cryptography import x509


def load(tmp_path):
    path=Path(__file__).resolve().parents[1]/'tools/gen_certs.py'
    spec=importlib.util.spec_from_file_location('cert_generator_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.CERTS_DIR=tmp_path/'certs';module.CLIENT_DIR=module.CERTS_DIR/'client'
    return module


def test_server_only_adds_ip_and_keeps_existing_credentials(tmp_path):
    gen=load(tmp_path)
    gen.main(['--host','old.example.test'])
    names=('ca.key','ca.pem','server.key','client/ca.pem','client/client.pem','client/client.key')
    before={name:(gen.CERTS_DIR/name).read_bytes() for name in names}
    old_server=(gen.CERTS_DIR/'server.pem').read_bytes()
    gen.main(['--server-only','--host','108.130.252.236'])
    assert all((gen.CERTS_DIR/name).read_bytes()==data for name,data in before.items())
    certificate=x509.load_pem_x509_certificate((gen.CERTS_DIR/'server.pem').read_bytes())
    san=certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address('108.130.252.236') in san.get_values_for_type(x509.IPAddress)
    assert 'old.example.test' in san.get_values_for_type(x509.DNSName)
    certificate.verify_directly_issued_by(x509.load_pem_x509_certificate(before['ca.pem']))
    assert (gen.CERTS_DIR/'server.pem.previous').read_bytes()==old_server
    with pytest.raises(SystemExit):gen.main()
    assert (gen.CERTS_DIR/'ca.key').read_bytes()==before['ca.key']


def test_server_only_never_creates_a_new_ca(tmp_path):
    gen=load(tmp_path)
    with pytest.raises(SystemExit):gen.main(['--server-only','--host','108.130.252.236'])
    assert not gen.CERTS_DIR.exists()


def test_reject_host_with_port(tmp_path):
    gen=load(tmp_path)
    with pytest.raises(SystemExit):gen.main(['--server-only','--host','108.130.252.236:8003'])
    assert not gen.CERTS_DIR.exists()
