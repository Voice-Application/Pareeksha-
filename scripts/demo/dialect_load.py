#!/usr/bin/env python3
"""DOC-03-REC: load a Vaani subset (data/dialect/vaani, CC-BY-4.0, consented) through the real Dialect API
into the seeded project, so the web app shows a real report. N clips per group, two conditions."""
import csv, io, json, os, sys, time, zipfile
from pathlib import Path
import httpx
ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data/dialect/vaani"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 4
env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
c = httpx.Client(base_url="http://localhost:8000/api/v1", headers={"Authorization": f"Bearer {env['PAREEKSHA_API_KEY']}"}, timeout=120)
rows = list(csv.DictReader((D / "manifest.csv").open(encoding="utf-8")))
seen, pick = {}, []
for r in rows:
    if seen.get(r["dialect_label"], 0) < N:
        seen[r["dialect_label"]] = seen.get(r["dialect_label"], 0) + 1; pick.append(r)
buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=list(rows[0])); w.writeheader(); w.writerows(pick)
z = io.BytesIO()
with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
    for r in pick: zf.write(D / r["file"], r["file"])
np_ = {p["name"]: p["id"] for p in c.get("/noise-profiles").json()["items"]}
ids = [np_["clean_16k"], np_["pstn_8k_alaw"]]
ds = c.post("/dialect-datasets", json={"name": f"Vaani dialects subset ({len(pick)} clips, CC-BY-4.0)"}).json()
up = c.post(f"/dialect-datasets/{ds['id']}/samples", files={"manifest": ("manifest.csv", buf.getvalue().encode(), "text/csv"), "clips": ("clips.zip", z.getvalue(), "application/zip")})
up.raise_for_status(); print("upload", up.json(), flush=True)
ev = c.post(f"/dialect-datasets/{ds['id']}/evaluate", json={"noise_profile_ids": ids, "engines": ["gnani-prisma"]}); ev.raise_for_status()
rid = ev.json()["report_id"]; print("report", rid, flush=True)
while True:
    r = c.get(f"/dialect-reports/{rid}").json(); print(r.get("status"), r.get("progress"), flush=True)
    if r.get("status") not in ("pending", "running", "queued", "collecting"): break
    time.sleep(20)
json.dump({"dataset_id": ds["id"], "report_id": rid}, open(ROOT / "proof/DOC-03/dialect.json", "w"))
