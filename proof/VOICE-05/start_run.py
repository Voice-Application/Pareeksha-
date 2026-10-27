"""Create the VOICE-05 acceptance run through the public API: 12 calls, per-run cap 3."""
import json
import os
import sys

import httpx

BASE = os.environ.get("PAREEKSHA_API_URL", "http://localhost:8000/api/v1")
H = {"Authorization": f"Bearer {os.environ['PAREEKSHA_API_KEY']}"}
agent_name = sys.argv[1] if len(sys.argv) > 1 else "EMI Reminder Bot"
repeats = int(sys.argv[2]) if len(sys.argv) > 2 else 3
name = sys.argv[3] if len(sys.argv) > 3 else "voice05-12-calls"

with httpx.Client(base_url=BASE, headers=H, timeout=30) as c:
    def items(path: str) -> list[dict]:
        return c.get(path, params={"limit": 200}).json()["items"]

    agent = next(a for a in items("/agents") if a["name"] == agent_name)
    scenarios = [s for s in items("/scenarios") if s["title"] in ("Disputes the EMI amount", "Promise to pay on Friday")]
    personas = [p for p in items("/personas") if p["name"] in ("Priya — careful", "Mr. Iyer — formal")]
    profile = next(p for p in items("/noise-profiles") if p["name"] == "pstn_8k_alaw")
    body = {
        "agent_id": agent["id"],
        "name": name,
        "scenario_ids": [s["id"] for s in scenarios],
        "persona_ids": [p["id"] for p in personas],
        "noise_profile_ids": [profile["id"]],
        "repeats": repeats,
        "config": {"max_concurrency": 3},
    }
    est = c.post("/runs:estimate", json=body).json()
    print("estimate", json.dumps(est)[:300])
    r = c.post("/runs", json=body)
    print(r.status_code, json.dumps(r.json())[:400])
