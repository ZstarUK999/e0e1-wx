"""纯 Python 的 Ed25519 验签（RFC 8032）。

只为"客户端离线校验 license"这一件事存在：包里不能为了验一次签名带上
cryptography（20MB+），而标准库没有 Ed25519。启动时只验一次，几十毫秒无所谓。

验签用无余因子形式（S*B == R + k*A），与主流实现一致。
"""

from __future__ import annotations

import hashlib

P = 2**255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P
L = 2**252 + 27742317777372353535851937790883648493


def _inverse(value: int) -> int:
    return pow(value, P - 2, P)


def _xrecover(y: int) -> int | None:
    """由 y 反解 x。"""
    xx = (y * y - 1) * _inverse(D * y * y + 1) % P
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = x * pow(2, (P - 1) // 4, P) % P
    if (x * x - xx) % P != 0:
        return None
    return x


def _base_point() -> tuple[int, int]:
    y = 4 * _inverse(5) % P
    x = _xrecover(y)
    if x is None:
        raise RuntimeError("基点计算失败")
    # 开方有两个解，标准基点的 x 取偶数那个；取反会导致所有点乘结果差一个符号
    if x % 2:
        x = P - x
    return x % P, y


BASE = _base_point()


def _add(point1: tuple[int, int], point2: tuple[int, int]) -> tuple[int, int]:
    """扭曲爱德华兹曲线加法（a = -1），仿射坐标。"""
    x1, y1 = point1
    x2, y2 = point2
    k = D * x1 * x2 * y1 * y2 % P
    x3 = (x1 * y2 + x2 * y1) * _inverse(1 + k) % P
    y3 = (y1 * y2 + x1 * x2) * _inverse(1 - k) % P
    return x3 % P, y3 % P


def _multiply(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    result = (0, 1)  # 单位元
    value = scalar % L
    while value > 0:
        if value & 1:
            result = _add(result, point)
        point = _add(point, point)
        value >>= 1
    return result


def _decompress(data: bytes) -> tuple[int, int] | None:
    """解压 32 字节的压缩点；最高位是 x 的奇偶。"""
    if len(data) != 32:
        return None
    raw = bytearray(data)
    sign = raw[31] >> 7
    raw[31] &= 0x7F
    y = int.from_bytes(bytes(raw), "little")
    if y >= P:
        return None
    x = _xrecover(y)
    if x is None:
        return None
    if x % 2 != sign:
        x = P - x
    return x % P, y


def verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """验签；任何格式问题一律返回 False，不抛异常。"""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    point_a = _decompress(public_key)
    point_r = _decompress(signature[:32])
    if point_a is None or point_r is None:
        return False
    s_value = int.from_bytes(signature[32:], "little")
    if s_value >= L:
        return False
    digest = hashlib.sha512(signature[:32] + public_key + message).digest()
    k = int.from_bytes(digest, "little") % L
    left = _multiply(BASE, s_value)
    right = _add(point_r, _multiply(point_a, k))
    return left[0] == right[0] and left[1] == right[1]
