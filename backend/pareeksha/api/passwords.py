"""Password hashing with stdlib scrypt: ``scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>``."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import weakref

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


#: Concurrent scrypt runs (about 32 MiB each) per process. More requests wait their turn instead
#: of each allocating, so a burst of logins cannot exhaust memory or the thread pool.
MAX_CONCURRENT_HASHES = 4
_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _slots:
        _slots[loop] = asyncio.Semaphore(MAX_CONCURRENT_HASHES)
    return _slots[loop]


async def hash_password_async(password: str) -> str:
    """``hash_password`` off the event loop, at most ``MAX_CONCURRENT_HASHES`` at a time."""
    async with _slot():
        return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, stored: str) -> bool:
    """``verify_password`` off the event loop, at most ``MAX_CONCURRENT_HASHES`` at a time."""
    async with _slot():
        return await asyncio.to_thread(verify_password, password, stored)
