"""生成自签 CA、服务器证书与客户端证书（mTLS 用）。

CA 私钥留在服务器；客户端证书随发布包分发给所有玩家共用一份。
"""

from __future__ import annotations

import argparse
import sys
import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CERTS_DIR = BACKEND_ROOT / "certs"
CLIENT_DIR = CERTS_DIR / "client"

# 服务器证书的 SAN：按实际部署地址改，否则客户端校验证书会失败。
DEFAULT_SAN = ["localhost", "127.0.0.1"]


def _key():
    return ec.generate_private_key(ec.SECP256R1())


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _sign(builder, ca_key) -> x509.Certificate:
    return builder.sign(private_key=ca_key, algorithm=hashes.SHA256())


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"  写入 {path}")


def _write_server(ca_key, ca_cert, hosts, now, *, reuse_key=False):
    if ca_cert.not_valid_after_utc <= now:
        raise SystemExit("现有CA已过期，不能补签服务器证书")
    key_path = CERTS_DIR / "server.key"
    server_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None) if reuse_key and key_path.is_file() else _key()
    san = [x509.DNSName(name) for name in hosts if not _is_ip(name)]
    san += [x509.IPAddress(ipaddress.ip_address(name)) for name in hosts if _is_ip(name)]
    server_cert = _sign(
        x509.CertificateBuilder()
        .subject_name(_name("e0e1-plugin-server"))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(min(now + dt.timedelta(days=825), ca_cert.not_valid_after_utc))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False),
        ca_key,
    )
    certificate = server_cert.public_bytes(serialization.Encoding.PEM)
    if reuse_key and (CERTS_DIR / "server.pem").is_file():
        _write(CERTS_DIR / "server.pem.previous", (CERTS_DIR / "server.pem").read_bytes())
    _write(CERTS_DIR / "server.pem", certificate)
    if not (reuse_key and key_path.is_file()):
        _write(
            CERTS_DIR / "server.key",
            server_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )



def main(argv=()) -> None:
    parser = argparse.ArgumentParser(description="生成 mTLS 证书；已有部署使用 --server-only 保留 CA 和客户端证书")
    parser.add_argument('--host', action='append', default=[], help="服务器域名或IP，不含协议和端口，可重复指定")
    parser.add_argument('--server-only', action='store_true', help="只补签服务器证书，复用已有 CA 和服务器私钥")
    parser.add_argument('--replace-all', action='store_true', help="明确允许覆盖已有整套证书")
    args = parser.parse_args(list(argv))
    hosts = list(dict.fromkeys(DEFAULT_SAN + [value.strip() for value in args.host]))
    for host in hosts:
        if not host or '/' in host or (not _is_ip(host) and ':' in host):
            parser.error('--host 只填写IP或域名，不要带 http:// 或端口')
    if args.server_only:
        if not args.host:
            parser.error('--server-only 必须用 --host 指定实际连接地址')
        ca_path, key_path = CERTS_DIR / 'ca.pem', CERTS_DIR / 'ca.key'
        if not ca_path.is_file() or not key_path.is_file():
            raise SystemExit('缺少现有 ca.pem 或 ca.key；不会自动生成新 CA')
        ca_cert = x509.load_pem_x509_certificate(ca_path.read_bytes())
        ca_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        fmt = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if ca_key.public_key().public_bytes(*fmt) != ca_cert.public_key().public_bytes(*fmt):
            raise SystemExit('CA证书与私钥不匹配，未修改任何证书')
        existing = CERTS_DIR / 'server.pem'
        if existing.is_file():
            previous = x509.load_pem_x509_certificate(existing.read_bytes())
            try:
                for value in previous.extensions.get_extension_for_class(x509.SubjectAlternativeName).value:
                    if isinstance(value, (x509.DNSName, x509.IPAddress)):
                        address = str(value.value)
                        if address not in hosts:
                            hosts.append(address)
            except x509.ExtensionNotFound:
                pass
        _write_server(ca_key, ca_cert, hosts, dt.datetime.now(dt.timezone.utc), reuse_key=True)
        print('服务器证书已更新，SAN：' + ', '.join(hosts))
        print('CA、客户端证书和授权密钥保持原样；重启 e0e1-server 后生效。')
        return
    if (CERTS_DIR / 'ca.key').exists() and not args.replace_all:
        raise SystemExit('已有 CA，已停止覆盖。补地址请用 --server-only --host；确需重建全部证书时使用 --replace-all')
    now = dt.datetime.now(dt.timezone.utc)
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_DIR.mkdir(parents=True, exist_ok=True)

    ca_key = _key()
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("e0e1-plugin-ca"))
        .issuer_name(_name("e0e1-plugin-ca"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    _write(CERTS_DIR / "ca.pem", ca_cert.public_bytes(serialization.Encoding.PEM))
    _write(
        CERTS_DIR / "ca.key",
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )

    _write_server(ca_key, ca_cert, hosts, now)

    client_key = _key()
    client_cert = _sign(
        x509.CertificateBuilder()
        .subject_name(_name("e0e1-plugin-client"))
        .issuer_name(ca_cert.subject)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        ),
        ca_key,
    )
    _write(CLIENT_DIR / "client.pem", client_cert.public_bytes(serialization.Encoding.PEM))
    _write(
        CLIENT_DIR / "client.key",
        client_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    _write(CLIENT_DIR / "ca.pem", ca_cert.public_bytes(serialization.Encoding.PEM))

    print("\n完成。客户端证书目录：", CLIENT_DIR)
    print("把 client.pem / client.key / ca.pem 随发布包分发（build_exe.py --certs 指向该目录）。")


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    main(sys.argv[1:])
