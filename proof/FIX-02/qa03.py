"""QA-03 driver: planted-bug detection through the real pipeline (public API only).

  setup  - create one agent per planted bug (same config as the clean "EMI Reminder Bot", endpoint = that
           bug's mock-agent container) and print nothing secret
  run    - run <label> <agent-name> <scenario,..> <persona,..> <profile,..> <repeats>: create the run
           through POST /runs, wait for it, write results/<label>.json with every call's checks and
           judge dimensions (cited turn indices)

Env: PAREEKSHA_API_URL, PAREEKSHA_API_KEY.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE = os.environ.get("PAREEKSHA_API_URL", "http://localhost:8000/api/v1")
H = {"Authorization": f"Bearer {os.environ['PAREEKSHA_API_KEY']}"}
OUT = Path(__file__).parent / "results"
CLEAN = "EMI Reminder Bot"
BUGS = ["no_disclosure", "no_amount_confirm", "english_to_kannada", "ignore_interrupt", "false_waiver"]
FINAL = {"completed", "partial", "failed", "cancelled"}

c = httpx.Client(base_url=BASE, headers=H, timeout=60)


def items(path: str) -> list[dict]:
    return c.get(path, params={"limit": 200}).json()["items"]


def setup() -> None:
    agents = {a["name"]: a for a in items("/agents")}
    clean = agents[CLEAN]
    for bug in BUGS:
        name = f"{CLEAN} [bug:{bug}]"
        if name in agents:
            continue
        body = {
            k: clean[k]
            for k in (
                "description", "adapter", "adapter_config", "languages", "glass_box",
                "mandatory_disclosures", "forbidden_phrases", "expected_tools", "bias_list",
                "max_call_seconds",
            )
            if k in clean
        }
        body["name"] = name
        body["endpoint_url"] = f"ws://qa03-{bug.replace('_', '-')}:8765/ws"
        r = c.post("/agents", json=body)
        print(name, r.status_code, r.text[:200] if r.status_code >= 300 else "")


def pick(rows: list[dict], key: str, wanted: list[str]) -> list[str]:
    found = {r[key]: r["id"] for r in rows}
    return [found[w] for w in wanted]


def run(label: str, agent: str, scenarios: str, personas: str, profiles: str, repeats: int) -> None:
    OUT.mkdir(exist_ok=True)
    ag = next(a for a in items("/agents") if a["name"] == agent)
    body = {
        "agent_id": ag["id"],
        "name": label,
        "scenario_ids": pick(items("/scenarios"), "title", scenarios.split(";")),
        "persona_ids": pick(items("/personas"), "name", personas.split(";")),
        "noise_profile_ids": pick(items("/noise-profiles"), "name", profiles.split(";")),
        "repeats": repeats,
        "config": {"max_concurrency": int(os.environ.get("RUN_CONCURRENCY", "1"))},
    }
    t0 = time.time()
    run_id = os.environ.get("RESUME_RUN_ID")  # re-attach to a run whose driver process died (the run itself continues)
    if not run_id:
        r = c.post("/runs", json=body)
        r.raise_for_status()
        run_id = r.json()["id"]
    print("run", label, run_id, flush=True)
    while True:
        d = c.get(f"/runs/{run_id}").json()
        if d["status"] in FINAL:
            break
        time.sleep(10)
    wall = time.time() - t0
    rows = c.get(f"/runs/{run_id}/items", params={"limit": 200}).json()["items"]
    calls = []
    for it in rows:
        if not it.get("call_id"):
            calls.append({"item": it, "call": None})
            continue
        calls.append({"item": it, "call": c.get(f"/calls/{it['call_id']}").json()})
    result = {
        "label": label, "run_id": run_id, "agent": agent, "status": d["status"],
        "wall_seconds": round(wall, 1), "progress": d["progress"], "summary": d["summary"],
        "request": body, "calls": calls,
    }
    (OUT / f"{label}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(label, d["status"], d["progress"], f"{wall:.0f}s", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "setup":
        setup()
    else:
        run(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], int(sys.argv[7]))
