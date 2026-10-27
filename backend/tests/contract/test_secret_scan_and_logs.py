"""NFR-8: no secrets in tracked files; API keys never reach logs."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from pareeksha.api.main import app

REPO = Path(__file__).resolve().parents[3]

# Real-looking credentials. Documented placeholders (pk_live_<…>, pk_test_*) are not matched.
PATTERNS = {
    "api key (pk_live_ + 40+ hex)": re.compile(r"pk_live_[0-9a-f]{40,}"),
    "provider key (sk-…)": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "google key (AIza…)": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "fernet key literal": re.compile(r"SECRET_KEY\s*=\s*[A-Za-z0-9_-]{43}="),
}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".wav",
    ".mp3",
    ".ogg",
    ".flac",
    ".woff",
    ".woff2",
    ".lock",
}


def _tracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout.decode()
    return [REPO / p for p in out.split("\0") if p]


def test_env_file_is_not_tracked_and_is_ignored() -> None:
    names = {p.name for p in _tracked()}
    assert ".env" not in names
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=REPO).returncode
    assert ignored == 0, ".env must be in .gitignore"


def test_no_credentials_in_tracked_files() -> None:
    hits = []
    for path in _tracked():
        if path.suffix in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for label, rx in PATTERNS.items():
            if rx.search(text):
                hits.append(f"{path.relative_to(REPO)}: {label}")
    assert not hits, hits


def test_bearer_key_is_not_logged(caplog) -> None:  # type: ignore[no-untyped-def]
    key = "pk_live_" + "ab12" * 12
    with caplog.at_level(logging.DEBUG):
        TestClient(app, raise_server_exceptions=False).get(
            "/api/v1/agents", headers={"Authorization": f"Bearer {key}"}
        )
    assert key not in caplog.text
