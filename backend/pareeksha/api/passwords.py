"""Password hashing with stdlib scrypt: ``scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>``."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**15, 8, 1
_MAXMEM = 128 * 1024 * 1024  # scrypt needs ~128*n*r = 32 MiB; OpenSSL's default cap is 32 MiB
MIN_LENGTH, MAX_LENGTH = 10, 200


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        actual = _scrypt(password, base64.b64decode(salt_b64), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)
