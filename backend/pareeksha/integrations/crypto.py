"""Fernet encryption for integration secrets (FR-IN-2, NFR-15).

Secrets are stored as a single Fernet token over their JSON form and are never returned by the
API: ``redact`` is what API responses use.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken


class SecretDecryptError(Exception):
    """The stored token cannot be decrypted (wrong SECRET_KEY or corrupted data)."""


class SecretBox:
    """Encrypt / decrypt a ``dict[str, str]`` of secrets with ``SECRET_KEY`` (a Fernet key)."""

    def __init__(self, key: str | bytes) -> None:
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "SECRET_KEY must be a Fernet key; generate one with "
                "cryptography.fernet.Fernet.generate_key()"
            ) from exc

    def encrypt(self, secrets: dict[str, str]) -> str:
        payload = json.dumps(secrets, sort_keys=True).encode()
        return self._fernet.encrypt(payload).decode()

    def decrypt(self, token: str) -> dict[str, str]:
        try:
            raw = self._fernet.decrypt(token.encode())
        except InvalidToken as exc:
            raise SecretDecryptError("cannot decrypt secrets (wrong SECRET_KEY?)") from exc
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items()}


def redact(secrets: dict[str, str]) -> dict[str, bool]:
    """What the API may show about secrets: which names are set, never the values."""
    return {name: bool(value) for name, value in secrets.items()}
