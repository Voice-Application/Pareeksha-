"""Build a SMALL synthetic dialect dataset (Gnani TTS voices, no real speakers) and evaluate it through the API.

Every group label ends in "(synthetic)"; the UI marks those groups. n is small on purpose (spend), so cells show
the low-sample hatch honestly. Needs GNANI_API_KEY (TTS+STT), PAREEKSHA_API_URL, PAREEKSHA_API_KEY.

    python proof/FIX-02/make_synthetic_dialect.py
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from pareeksha.speech import get_tts_provider  # noqa: E402

BASE = os.environ["PAREEKSHA_API_URL"]
H = {"Authorization": f"Bearer {os.environ['PAREEKSHA_API_KEY']}"}
GROUPS = [
    ("kn-IN", "Bengaluru urban (synthetic)", "Prakash", [
        "ನಿಮ್ಮ ಇಎಂಐ ನಾಲ್ಕು ಸಾವಿರದ ಐನೂರು ರೂಪಾಯಿ ಬಾಕಿ ಇದೆ",
        "ನಾನು ಶುಕ್ರವಾರ ಪಾವತಿ ಮಾಡುತ್ತೇನೆ",
        "ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಹೇಳಿ",
        "ನನಗೆ ಮಾನವ ಏಜೆಂಟ್ ಬೇಕು",
    ]),
    ("kn-IN", "Old Mysuru (synthetic)", "Lakshmi", [
        "ನಿಮ್ಮ ಸಾಲದ ಕಂತು ಬಾಕಿ ಇದೆ",
        "ನಾಳೆ ಹಣ ಕಟ್ಟುತ್ತೇನೆ",
        "ಮುಂದಿನ ತಿಂಗಳು ಕೊಡುತ್ತೇನೆ",
        "ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ",
    ]),
    ("hi-IN", "Delhi Hinglish (synthetic)", "Shubham", [
        "आपकी ईएमआई चार हज़ार पाँच सौ रुपये बाकी है",
        "मैं शुक्रवार को पेमेंट कर दूँगा",
        "कृपया दोबारा बताइए",
        "मुझे किसी इंसान से बात करनी है",
    ]),
]
CONDITIONS = ["clean_16k", "pstn_8k_alaw"]


async def main() -> None:
    tts = get_tts_provider()
    rows, clips = [], {}
    for lang, label, voice, phrases in GROUPS:
        for i, text in enumerate(phrases):
            speech = await tts.synthesize(text, voice, lang, sample_rate=16000)
            name = f"{label.split()[0].lower()}-{lang}-{i}.wav"
            clips[name] = speech.audio
            rows.append({"file": name, "reference_text": text, "language": lang, "dialect_label": label,
                         "speaker_id": f"tts-{voice}", "consent": "true", "domain_terms": ""})
    manifest = io.StringIO()
    writer = csv.DictWriter(manifest, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in clips.items():
            z.writestr(n, b)
    c = httpx.Client(base_url=BASE, headers=H, timeout=120)
    ds = c.post("/dialect-datasets", json={"name": f"synthetic-tts-{int(time.time())}",
                "description": "Gnani TTS voices (no real speakers); small n, for UI evidence only"}).json()
    up = c.post(f"/dialect-datasets/{ds['id']}/samples",
                files={"manifest": ("m.csv", manifest.getvalue().encode(), "text/csv"), "clips": ("c.zip", buf.getvalue(), "application/zip")})
    print("upload", up.status_code, up.json())
    profiles = {p["name"]: p["id"] for p in c.get("/noise-profiles", params={"limit": 100}).json()["items"]}
    ev = c.post(f"/dialect-datasets/{ds['id']}/evaluate", json={"noise_profile_ids": [profiles[n] for n in CONDITIONS], "engines": ["gnani-prisma"]})
    print("evaluate", ev.status_code, ev.json())
    rid = ev.json()["report_id"]
    for _ in range(120):
        r = c.get(f"/dialect-reports/{rid}").json()
        if r["progress"]["done"] >= r["progress"]["expected_results"]:
            break
        time.sleep(5)
    print("report", rid, r["progress"])


asyncio.run(main())
