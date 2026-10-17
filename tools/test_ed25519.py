"""纯 Python Ed25519 验签的测试。

RFC 8032 TEST 1 的私钥是公开常量，用它现算向量（避免手抄十六进制抄错），
再和 cryptography 交叉验证。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from package.plugin_manager import ed25519  # noqa: E402

# RFC 8032 TEST 1 的私钥，对应公钥 d75a9801...（下面会断言核对）
RFC_SECRET = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
RFC_PUBLIC = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(RFC_SECRET)
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return key, public


def test_rfc_public_key_matches():
    """确认测试向量本身没抄错：私钥推出来的公钥必须等于 RFC 给的值。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(RFC_SECRET)
    assert (
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        == RFC_PUBLIC
    )


@pytest.mark.parametrize("message", [b"", b"license", os.urandom(64), "中文".encode()])
def test_rfc_key_signatures(message):
    key, public = _keypair()
    assert ed25519.verify(public, key.sign(message), message)


def test_tampered_message_fails():
    key, public = _keypair()
    signature = key.sign(b"license")
    assert not ed25519.verify(public, signature, b"license2")


def test_tampered_signature_fails():
    key, public = _keypair()
    signature = bytearray(key.sign(b"license"))
    signature[0] ^= 0x01
    assert not ed25519.verify(public, bytes(signature), b"license")


def test_wrong_public_key_fails():
    """换一把公钥验同一个签名必须失败，防止实现恒真。"""
    key, _ = _keypair()
    other = Ed25519PublicKeyPair()
    assert not ed25519.verify(other, key.sign(b"license"), b"license")


def Ed25519PublicKeyPair() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    )


def test_malformed_inputs_fail():
    key, public = _keypair()
    signature = key.sign(b"license")
    assert not ed25519.verify(public[:16], signature, b"license")
    assert not ed25519.verify(public, signature[:32], b"license")
    assert not ed25519.verify(public, b"\x00" * 64, b"license")


def test_cross_check_with_random_keys():
    """随机密钥往返：cryptography 签，我们验。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    for _ in range(5):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        message = os.urandom(48)
        assert ed25519.verify(public, key.sign(message), message)
        assert not ed25519.verify(public, key.sign(message), message + b"x")
