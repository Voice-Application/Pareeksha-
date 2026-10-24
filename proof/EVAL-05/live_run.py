"""EVAL-05 acceptance run: the whole dialect pipeline on real infrastructure.

Real Kafka, real Postgres (own database, Alembic-migrated), the real API (uvicorn), the real
outbox relay and dialect consumer processes, real Gnani STT and real DeepSeek for the intent flag.
The only synthetic part is the audio: Gnani TTS voices read Kannada / Hindi EMI sentences (no human
recordings exist yet, H-02). Dialect labels say "synth" so nobody mistakes this for dialect data.

    KAFKA=localhost:19094 PG=postgresql://pareeksha:pareeksha@localhost:5432 \
        python3 proof/EVAL-05/live_run.py

Outputs next to this file: report.json, report.html, clips.json, usage.json, *.log.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
import psycopg
from alembic import command

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pareeksha.api.auth import generate_api_key  # noqa: E402
from pareeksha.audio.profiles import BUILTIN_PROFILES  # noqa: E402
from pareeksha.gnani import GnaniSpeech  # noqa: E402
from tests.conftest import alembic_config  # noqa: E402

KAFKA = os.environ.get("KAFKA", "localhost:19094")
PG = os.environ.get("PG", "postgresql://pareeksha:pareeksha@localhost:5432")
DB = "pareeksha_eval05"
API_PORT = 18005
CONDITIONS = ("clean_16k", "pstn_8k_alaw", "pstn_street_10db")

# (dialect group, language, speaker, voice, [(sentence, domain terms)])
SCRIPT = [
    ("kn-synth-m", "kn-IN", "kn-m-1", "Prakash", [
        ("ನಿಮ್ಮ ಇಎಂಐ ಐದು ಸಾವಿರ ರೂಪಾಯಿ ಬಾಕಿ ಇದೆ", "ಇಎಂಐ"),
        ("ನಿಮ್ಮ ಕಂತು ಮೂರು ತಿಂಗಳಿಂದ ಕಟ್ಟಿಲ್ಲ", "ಕಂತು"),
    ]),
    ("kn-synth-m", "kn-IN", "kn-m-2", "Avinash", [
        ("ನಾನು ಇಪ್ಪತ್ತು ಸಾವಿರ ರೂಪಾಯಿ ಲೋನ್ ತೆಗೆದುಕೊಂಡಿದ್ದೇನೆ", "ಲೋನ್"),
        ("ದಯವಿಟ್ಟು ನನ್ನ ಬ್ಯಾಲೆನ್ಸ್ ಹೇಳಿ", "ಬ್ಯಾಲೆನ್ಸ್"),
    ]),
    ("kn-synth-f", "kn-IN", "kn-f-1", "Lakshmi", [
        ("ನನ್ನ ಅಕೌಂಟ್ ನಂಬರ್ ಹನ್ನೆರಡು ಮೂವತ್ತೆರಡು", "ಅಕೌಂಟ್"),
        ("ಈ ತಿಂಗಳ ಪೇಮೆಂಟ್ ಹದಿನೈದನೇ ತಾರೀಖು ಮಾಡುತ್ತೇನೆ", "ಪೇಮೆಂಟ್"),
    ]),
    ("kn-synth-f", "kn-IN", "kn-f-2", "Kalpana", [
        ("ನನ್ನ ಬಡ್ಡಿ ಏಕೆ ಹೆಚ್ಚಾಯಿತು", "ಬಡ್ಡಿ"),
        ("ಎರಡು ಲಕ್ಷ ರೂಪಾಯಿ ಲೋನ್ ಬಗ್ಗೆ ತಿಳಿಸಿ", "ಲೋನ್"),
    ]),
    ("hi-synth", "hi-IN", "hi-1", "Shubham", [
        ("आपकी ईएमआई पाँच हज़ार रुपये बाकी है", "ईएमआई"),
        ("मैंने पिछले महीने भुगतान कर दिया था", "भुगतान"),
    ]),
    ("hi-synth", "hi-IN", "hi-2", "Shivani", [
        ("मुझे दो लाख रुपये का लोन चाहिए", "लोन"),
        ("कृपया मेरा बैलेंस बताइए", "बैलेंस"),
    ]),
]


def sh(*cmd: str, log: str) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "KAFKA_BOOTSTRAP_SERVERS": KAFKA,
        "DATABASE_URL": f"postgresql+psycopg://{PG.split('://', 1)[1]}/{DB}",
        "DATA_DIR": str(HERE / "data"),
        "PYTHONPATH": str(ROOT / "backend"),
    }
    return subprocess.Popen(cmd, env=env, stdout=(HERE / log).open("wb"), stderr=subprocess.STDOUT)


def build_inputs(data: Path) -> tuple[bytes, bytes]:
    speech = GnaniSpeech(os.environ["GNANI_API_KEY"], cache_dir=data / "tts_cache")
    rows = ["file,reference_text,language,dialect_label,speaker_id,consent,domain_terms"]
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w") as z:
        for group, lang, speaker, voice, lines in SCRIPT:
            for text, terms in lines:
                n += 1
                name = f"clip{n:02d}.wav"
                z.writestr(name, speech.synthesize(text, voice, lang).audio)
                rows.append(f"{name},{text},{lang},{group},{speaker},true,{terms}")
    (HERE / "tts_usage.json").write_text(json.dumps(speech.ledger.totals(), indent=2))
    return ("\n".join(rows) + "\n").encode(), buf.getvalue()


def main() -> None:
    (HERE / "data").mkdir(exist_ok=True)
    admin = f"{PG}/postgres"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{DB}"')
    db_url = f"postgresql+psycopg://{PG.split('://', 1)[1]}/{DB}"
    command.upgrade(alembic_config(db_url), "head")
    key, prefix, key_hash = generate_api_key()
    with psycopg.connect(f"{PG}/{DB}", autocommit=True) as c:
        pid = c.execute("INSERT INTO projects (name) VALUES ('eval05') RETURNING id").fetchone()[0]
        c.execute(
            "INSERT INTO api_keys (project_id, name, prefix, key_hash, scopes) "
            "VALUES (%s,'eval05',%s,%s,ARRAY['admin'])",
            (pid, prefix, key_hash),
        )
    manifest, clips = build_inputs(HERE / "data")

    procs = [
        sh(sys.executable, "-m", "uvicorn", "pareeksha.api.main:app", "--port", str(API_PORT),
           log="api.log"),
        sh(sys.executable, "-m", "pareeksha.workers.outbox_relay", log="outbox_relay.log"),
        sh(sys.executable, "-m", "pareeksha.workers.dialect", log="dialect_worker.log"),
    ]
    try:
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{API_PORT}/api/v1",
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
        )
        for _ in range(60):
            try:
                if client.get("/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        ids = []
        for name in CONDITIONS:
            p = BUILTIN_PROFILES[name]
            r = client.post("/noise-profiles", json={
                "name": p.name, "sample_rate": p.sample_rate, "codec": p.codec,
                "pstn_bandpass": p.pstn_bandpass, "background_category": p.background,
                "snr_db": p.snr_db, "packet_loss_pct": p.packet_loss_pct, "clipping": p.clipping,
            })
            r.raise_for_status()
            ids.append(r.json()["id"])
        dataset = client.post("/dialect-datasets", json={"name": "Synthetic EMI sentences"}).json()
        up = client.post(
            f"/dialect-datasets/{dataset['id']}/samples",
            files={"manifest": ("m.csv", manifest, "text/csv"),
                   "clips": ("clips.zip", clips, "application/zip")},
        )
        up.raise_for_status()
        print("upload:", up.json())
        started = time.time()
        ev = client.post(
            f"/dialect-datasets/{dataset['id']}/evaluate",
            json={"noise_profile_ids": ids, "engines": ["gnani-prisma"]},
        )
        ev.raise_for_status()
        report_id = ev.json()["report_id"]
        print("evaluate:", ev.json())
        while True:
            report = client.get(f"/dialect-reports/{report_id}").json()
            print(f"  progress {report['progress']}")
            if report["html"]:
                break
            if time.time() - started > 600:
                raise SystemExit("timed out waiting for the report")
            time.sleep(5)
        print(f"report ready in {time.time() - started:.0f} s")
        (HERE / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        (HERE / "report.html").write_text(client.get(f"/dialect-reports/{report_id}/html").text)
        clips_out = client.get(f"/dialect-reports/{report_id}/clips", params={"limit": 200}).json()
        (HERE / "clips.json").write_text(json.dumps(clips_out, indent=2, ensure_ascii=False))
        with psycopg.connect(f"{PG}/{DB}") as c:
            usage = c.execute(
                "SELECT provider, operation, sum(units)::float, unit_type, count(*) "
                "FROM api_usage GROUP BY 1,2,4 ORDER BY 1,2"
            ).fetchall()
            consent = c.execute(
                "SELECT count(*), count(*) FILTER (WHERE consent) FROM dialect_samples"
            ).fetchone()
            lag = c.execute("SELECT count(*) FROM processed_events WHERE consumer_group='dialect'")
            processed = lag.fetchone()
        (HERE / "usage.json").write_text(
            json.dumps(
                {"api_usage": usage, "samples_total_and_consented": consent,
                 "dialect_events_processed": processed},
                indent=2, default=str,
            )
        )
        print("usage:", usage)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=20)


if __name__ == "__main__":
    main()
