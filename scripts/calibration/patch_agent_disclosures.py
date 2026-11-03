#!/usr/bin/env python3
"""EVAL-08: give every live "EMI Reminder Bot" agent (clean and [bug:...]) the seed's mandatory
disclosures (recording + company, owner rule R-a) through PATCH /agents/{id}. The seed only creates
the agent when it is missing, and the bug agents are copies made by the V4 / batch scripts.

    python3 scripts/calibration/patch_agent_disclosures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verify"))
import vapi  # noqa: E402

SEED = ROOT / "backend" / "pareeksha" / "seed" / "data" / "agent_emi.yaml"


def main() -> int:
    want = yaml.safe_load(SEED.read_text(encoding="utf-8"))["mandatory_disclosures"]
    agents = vapi.request("GET", "/agents?limit=100")
    items = agents["items"] if isinstance(agents, dict) else agents
    for a in items:
        if not a["name"].startswith("EMI Reminder Bot"):
            continue
        before = [d["id"] for d in a.get("mandatory_disclosures") or []]
        if a.get("mandatory_disclosures") != want:
            vapi.request("PATCH", f"/agents/{a['id']}", {"mandatory_disclosures": want})
        after = vapi.request("GET", f"/agents/{a['id']}")["mandatory_disclosures"]
        shown = [(d["id"], d.get("within_turns")) for d in after]
        print(f"{a['name']}: {before} -> {shown}", flush=True)
        assert after == want
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
