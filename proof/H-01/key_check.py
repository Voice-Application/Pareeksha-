"""H-01 fresh key check: one minimal call per provider. Prints only HTTP status codes and model ids, never a key.

    GNANI_API_KEY=... DEEPSEEK_API_KEY=... python proof/H-01/key_check.py

Gnani goes through the project's own wrapper (pareeksha.gnani.GnaniSpeech: TTS then REST STT); the HTTP status of every
request it makes is recorded by wrapping requests.Session.send. DeepSeek is a raw chat-completions call.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from pareeksha.gnani.clients import TTS_MODEL, GnaniSpeech  # noqa: E402

statuses: list[dict[str, object]] = []
_send = requests.Session.send


def _recording_send(self, request, **kw):  # type: ignore[no-untyped-def]
    resp = _send(self, request, **kw)
    statuses.append({"method": request.method, "host": request.url.split("/")[2], "path": request.url.split("?")[0].split("/", 3)[3], "status": resp.status_code})
    return resp


requests.Session.send = _recording_send  # type: ignore[method-assign]


def gnani() -> dict[str, object]:
    sp = GnaniSpeech(api_key=os.environ["GNANI_API_KEY"])
    tts = sp.synthesize("नमस्ते, आपकी ई एम आई बाकी है।", "Shivani", "hi-IN", sample_rate=16000)
    out: dict[str, object] = {"tts_bytes": len(tts.audio), "tts_model": TTS_MODEL}
    stt = sp.transcribe(tts.audio, "hi-IN")
    out["stt_has_text"] = bool(stt.get("transcript") or stt.get("text"))
    return out


def deepseek() -> dict[str, object]:
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_CALLER_MODEL", "deepseek-flash")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "Reply with the word ok"}]}).encode(),
        headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
        return {"http_status": r.status, "requested_model": model, "served_model": body.get("model"), "has_choice": bool(body.get("choices"))}


report: dict[str, object] = {"gemini": "not tested: optional per owner decision (CHANGELOG 2026-10-28)"}
for name, fn in (("gnani", gnani), ("deepseek", deepseek)):
    try:
        report[name] = fn()
    except Exception as exc:  # report the failure, never hide it
        report[name] = {"error": type(exc).__name__, "detail": str(exc)[:200].replace(os.environ.get("GNANI_API_KEY", "\0"), "<key>").replace(os.environ.get("DEEPSEEK_API_KEY", "\0"), "<key>")}
report["gnani_http"] = statuses
print(json.dumps(report, indent=2, ensure_ascii=False))
