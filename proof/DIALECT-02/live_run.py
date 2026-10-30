"""DIALECT-02 acceptance run: Vaani clips through the real Dialect API on the Compose stack.

Stack (docker compose, profile workers): kafka, postgres, migrate, api, outbox-relay, dialect,
retrier, dlq-recorder. Real Gnani Prisma STT (one dialect consumer, one request at a time) and
real DeepSeek for the intent flag. Audio and references: data/dialect/vaani (fetch_vaani.py).

    API=http://localhost:8000/api/v1 PG=postgresql://pareeksha:pareeksha@localhost:5432/pareeksha \
        python3 proof/DIALECT-02/live_run.py

Outputs next to this file: report.json, report.html, clips.json, usage.json, live_run.txt (stdout).
``live_run.py --collect`` re-reads those outputs for the report recorded in usage.json.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import httpx
import psycopg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pareeksha.api.auth import generate_api_key  # noqa: E402
from pareeksha.audio.profiles import BUILTIN_PROFILES  # noqa: E402

API = os.environ.get("API", "http://localhost:8000/api/v1")
PG = os.environ.get("PG", "postgresql://pareeksha:pareeksha@localhost:5432/pareeksha")
DATA = ROOT / "data" / "dialect" / "vaani"
CONDITIONS = ("clean_16k", "pstn_8k_alaw", "pstn_street_10db")
TIMEOUT_S = 3 * 3600


def build_inputs() -> tuple[bytes, bytes, int]:
    manifest = (DATA / "manifest.csv").read_bytes()
    rows = list(csv.DictReader(io.StringIO(manifest.decode("utf-8"))))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for row in rows:
            z.write(DATA / row["file"], row["file"])
    return manifest, buf.getvalue(), len(rows)


def api_key(project_id: str | None = None) -> tuple[str, str]:
    """An admin key for a new project, or for ``project_id`` when given."""
    key, prefix, key_hash = generate_api_key()
    with psycopg.connect(PG, autocommit=True) as c:
        pid = (
            project_id
            or c.execute(
                "INSERT INTO projects (name) VALUES ('dialect-02 vaani') RETURNING id"
            ).fetchone()[0]
        )
        c.execute(
            "INSERT INTO api_keys (project_id, name, prefix, key_hash, scopes) "
            "VALUES (%s,'dialect-02',%s,%s,ARRAY['admin'])",
            (pid, prefix, key_hash),
        )
    return key, str(pid)


def collect(client: httpx.Client, report_id: str, dataset_id: str, project_id: str) -> None:
    """Write report.json, report.html, clips.json and usage.json from the API and the DB."""
    report = client.get(f"/dialect-reports/{report_id}").json()
    (HERE / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (HERE / "report.html").write_text(client.get(f"/dialect-reports/{report_id}/html").text)
    clips_out: list[dict] = []
    cursor = None
    while True:  # worst clips first, 200 per page (the API maximum)
        params = {"limit": 200, **({"cursor": cursor} if cursor else {})}
        page = client.get(f"/dialect-reports/{report_id}/clips", params=params)
        page.raise_for_status()
        clips_out += page.json()["items"]
        cursor = page.json().get("next_cursor")
        if not cursor:
            break
    (HERE / "clips.json").write_text(json.dumps(clips_out, indent=2, ensure_ascii=False))
    with psycopg.connect(PG) as c:
        usage = c.execute(
            "SELECT provider, operation, sum(units)::float, unit_type, count(*), sum(est_cost) "
            "FROM api_usage GROUP BY 1,2,4 ORDER BY 1,2"
        ).fetchall()
        consent = c.execute(
            "SELECT count(*), count(*) FILTER (WHERE consent) FROM dialect_samples "
            "WHERE dataset_id = %s",
            (dataset_id,),
        ).fetchone()
        results = c.execute(
            "SELECT count(*) FROM asr_results r JOIN dialect_samples s ON s.id = r.sample_id "
            "WHERE s.dataset_id = %s",
            (dataset_id,),
        ).fetchone()
        processed = c.execute(
            "SELECT count(*) FROM processed_events WHERE consumer_group='dialect'"
        ).fetchone()
    (HERE / "usage.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "report_id": report_id,
                "api_usage(provider, operation, units, unit_type, calls, est_cost)": usage,
                "samples_total_and_consented": consent,
                "asr_results": results,
                "dialect_events_processed": processed,
            },
            indent=2,
            default=str,
        )
    )
    print("usage:", usage)


def main() -> None:
    manifest, clips, n_rows = build_inputs()
    print(f"manifest rows: {n_rows}, clips zip: {len(clips) / 1e6:.1f} MB")
    key, project_id = api_key()
    client = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {key}"}, timeout=120)
    client.get("/health").raise_for_status()

    existing = {p["name"]: p["id"] for p in client.get("/noise-profiles").json().get("items", [])}
    ids = []
    for name in CONDITIONS:
        if name in existing:
            ids.append(existing[name])
            continue
        p = BUILTIN_PROFILES[name]
        r = client.post(
            "/noise-profiles",
            json={
                "name": p.name,
                "sample_rate": p.sample_rate,
                "codec": p.codec,
                "pstn_bandpass": p.pstn_bandpass,
                "background_category": p.background,
                "snr_db": p.snr_db,
                "packet_loss_pct": p.packet_loss_pct,
                "clipping": p.clipping,
            },
        )
        r.raise_for_status()
        ids.append(r.json()["id"])
    print("noise profiles:", dict(zip(CONDITIONS, ids, strict=True)))

    dataset = client.post(
        "/dialect-datasets", json={"name": "Vaani dialects v1 (CC-BY-4.0)"}
    ).json()
    up = client.post(
        f"/dialect-datasets/{dataset['id']}/samples",
        files={
            "manifest": ("manifest.csv", manifest, "text/csv"),
            "clips": ("clips.zip", clips, "application/zip"),
        },
    )
    up.raise_for_status()
    print("upload:", json.dumps(up.json(), ensure_ascii=False))
    started = time.time()
    ev = client.post(
        f"/dialect-datasets/{dataset['id']}/evaluate",
        json={"noise_profile_ids": ids, "engines": ["gnani-prisma"]},
    )
    ev.raise_for_status()
    report_id = ev.json()["report_id"]
    print("evaluate:", ev.json())
    last = None
    while True:
        report = client.get(f"/dialect-reports/{report_id}").json()
        if report["progress"] != last:
            print(f"  {time.time() - started:6.0f} s progress {report['progress']}", flush=True)
            last = report["progress"]
        if report["html"]:
            break
        if time.time() - started > TIMEOUT_S:
            raise SystemExit("timed out waiting for the report")
        time.sleep(10)
    print(f"report ready in {time.time() - started:.0f} s")
    collect(client, report_id, dataset["id"], project_id)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--collect"]:  # re-read the outputs of a finished run, no new STT calls
        ids = json.loads((HERE / "usage.json").read_text())
        key, _ = api_key(ids["project_id"])
        collect(
            httpx.Client(base_url=API, headers={"Authorization": f"Bearer {key}"}, timeout=120),
            ids["report_id"],
            ids["dataset_id"],
            ids["project_id"],
        )
    else:
        main()
