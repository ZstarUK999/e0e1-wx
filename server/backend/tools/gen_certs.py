"""生成自签 CA、服务器证书与客户端证书（mTLS 用）。

CA 私钥留在服务器；客户端证书随发布包分发给所有玩家共用一份。
"""

from __future__ import annotations

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


def main() -> None:
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

    server_key = _key()
    san = [x509.DNSName(name) for name in DEFAULT_SAN if not _is_ip(name)]
    san += [x509.IPAddress(ipaddress.ip_address(name)) for name in DEFAULT_SAN if _is_ip(name)]
    server_cert = _sign(
        x509.CertificateBuilder()
        .subject_name(_name("e0e1-plugin-server"))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False),
        ca_key,
    )
    _write(CERTS_DIR / "server.pem", server_cert.public_bytes(serialization.Encoding.PEM))
    _write(
        CERTS_DIR / "server.key",
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )

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
    main()
