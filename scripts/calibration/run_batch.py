#!/usr/bin/env python3
"""EVAL-06 step 1: a real 30-call batch for judge calibration (docs/08-evaluation-rubric.md section 10).

Each call is its own one-cell run through POST /runs (concurrency 1: Gnani allows one active request per
key). Clean calls go to the seeded "EMI Reminder Bot"; each planted bug gets its own mock-agent container
with MOCK_BUGS set and its own agent "EMI Reminder Bot [bug:<name>]" (same mechanism as V4,
scripts/verify/v04_planted_bugs.py). The judge evaluates every call as usual.

Writes proof/EVAL-06/batch.json (one row per call, appended as calls finish so a crash keeps the
finished ones; a re-run skips cells already present) and logs to stdout.

    COMPOSE="docker compose -f docker-compose.yml -f docker-compose.proxy.yml" \
        python3 scripts/calibration/run_batch.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verify"))
import v04_planted_bugs as v4  # noqa: E402
import vapi  # noqa: E402

OUT = ROOT / "proof" / "EVAL-06" / "batch.json"
CLEAN = v4.CLEAN

PAY, PAID, DISPUTE, HUMAN = (
    "Promise to pay on Friday",
    "Already paid, wants confirmation",
    "Disputes the EMI amount",
    "Asks for a human",
)
CONFUSED, INJECT, ABUSE, SILENT = (
    "Confused about the due date",
    "Prompt-injection attempt",
    "Abusive caller",
    "Caller goes silent",
)
# pstn_street_10db was tried first and dropped: its steady noise bed trips the mock agent's barge-in VAD
# before the opening plays, so the agent stays mute (cells 3 and 7 of the first attempt, batch_run.log).
ALAW, BABBLE, CLEAN16 = "pstn_8k_alaw", "pstn_office_babble_15db", "clean_16k"

# bug (None = clean agent) -> [(scenario, persona, noise profile)]
PLAN: dict[str | None, list[tuple[str, str, str]]] = {
    None: [
        (PAY, "Manju — auto driver", ALAW),
        (PAID, "Rohit — millennial", BABBLE),
        (DISPUTE, "Arjun — corporate", CLEAN16),
        (HUMAN, "Lakshmamma — elderly", BABBLE),
        (CONFUSED, "Ramesh ji — elderly", ALAW),
        (INJECT, "Mr. Iyer — formal", ALAW),
        (ABUSE, "Abusive-but-safe", CLEAN16),
        # "Caller goes silent" ended infra_error 4 times (The Silent One x3, Pooja x1): the silent caller's
        # line is punctuation only ("...") and Gnani TTS answers 500 "No audio generated during
        # synthesis" until the caller TTS times out. Cell 8 therefore runs another scenario.
        (DISPUTE, "Ramesh ji — elderly", ALAW),
        (PAY, "Sunita — worried borrower", CLEAN16),
        (PAID, "Neha — switcher", BABBLE),
    ],
    "no_disclosure": [
        (PAY, "Priya — careful", ALAW),
        (PAID, "Kiran — IT employee", BABBLE),
        (CONFUSED, "Mohan — labourer", CLEAN16),
        (HUMAN, "Pooja — student", ALAW),
    ],
    "no_amount_confirm": [
        (PAY, "Priya — careful", BABBLE),
        (PAY, "Shivappa — farmer", ALAW),
        (PAY, "Rohit — millennial", CLEAN16),
        (PAID, "Mr. Iyer — formal", ALAW),
    ],
    "english_to_kannada": [
        (PAY, "Deepa — homemaker", ALAW),
        (PAID, "Manju — auto driver", BABBLE),
        (CONFUSED, "Lakshmamma — elderly", CLEAN16),
        (DISPUTE, "Shivappa — farmer", ALAW),
    ],
    "ignore_interrupt": [
        (PAY, "The Interrupter", ALAW),
        (DISPUTE, "The Interrupter", BABBLE),
        (ABUSE, "Vikram — angry", CLEAN16),
        (CONFUSED, "Arjun — corporate", ALAW),
    ],
    "false_waiver": [
        (INJECT, "Off-topic tester", ALAW),
        (INJECT, "Vikram — angry", BABBLE),
        (INJECT, "Imran — shopkeeper", CLEAN16),
        (INJECT, "Neha — switcher", ALAW),
    ],
}


def load() -> list[dict]:
    return json.loads(OUT.read_text()) if OUT.exists() else []


def save(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=1, ensure_ascii=False))


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def run_cell(agent: str, bug: str | None, cell: tuple[str, str, str], idx: int) -> dict:
    scenario, persona, profile = cell
    res = vapi.run_and_wait(
        agent,
        [scenario],
        [persona],
        [profile],
        repeats=1,
        concurrency=1,
        name=f"eval06-{idx:02d}-{bug or 'clean'}",
        poll_s=5,
    )
    item = res["items"][0]
    row = {
        "cell": idx,
        "bug": bug,
        "scenario": scenario,
        "persona": persona,
        "noise_profile": profile,
        "agent": agent,
        "run_id": res["run_id"],
        "wall_s": res["wall_s"],
        "run_status": res["run"]["status"],
        "item_status": item["status"],
        "call_id": item.get("call_id"),
    }
    if row["call_id"]:
        ev = vapi.call(row["call_id"]).get("evaluation") or {}
        row.update(
            judge_passed=ev.get("passed"),
            judge_score=ev.get("overall_score"),
            judge_critical=ev.get("critical_failure"),
            evaluation_status=ev.get("status"),
        )
    return row


def main() -> int:
    planned = {
        n: (bug, c)
        for n, (bug, c) in enumerate(((b, c) for b, cs in PLAN.items() for c in cs), start=1)
    }
    tried = load()
    # failed cells, and cells whose plan changed since they ran, are run again; the replaced rows are kept
    # in batch_replaced.json for the record
    keep = [
        r
        for r in tried
        if r.get("evaluation_status") == "ok"
        and planned.get(r["cell"]) == (r["bug"], (r["scenario"], r["persona"], r["noise_profile"]))
    ]
    replaced = [r for r in tried if r not in keep]
    if replaced:
        old = OUT.with_name("batch_replaced.json")
        prev = json.loads(old.read_text()) if old.exists() else []
        old.write_text(json.dumps(prev + replaced, indent=1, ensure_ascii=False))
    rows = keep
    done = {r["cell"] for r in rows}
    clean = next(a for a in vapi.items("/agents") if a["name"] == CLEAN)
    idx = 0
    for bug, cells in PLAN.items():
        todo = [(idx + i + 1, c) for i, c in enumerate(cells) if idx + i + 1 not in done]
        idx += len(cells)
        if not todo:
            continue
        container = None
        agent = CLEAN
        if bug:
            container = v4.start_container(bug)
            v4.wait_ready(container)
            agent = v4.register(bug, container, clean)
            log(f"container {container} up, agent {agent!r}")
        try:
            for n, cell in todo:
                log(f"cell {n:02d} bug={bug or 'clean'} {cell}")
                row = run_cell(agent, bug, cell, n)
                log(
                    f"  -> {row['item_status']} call={row['call_id']} judge passed={row.get('judge_passed')} "
                    f"score={row.get('judge_score')} critical={row.get('judge_critical')} wall={row['wall_s']}s"
                )
                rows.append(row)
                save(sorted(rows, key=lambda r: r["cell"]))
        finally:
            if container:
                subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
    ok = sum(r.get("evaluation_status") == "ok" for r in rows)
    log(f"evaluated {ok}/{idx}; usage: {json.dumps(vapi.request('GET', '/usage'))}")
    return 0 if ok == idx else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--plan"]:
        for bug, cells in PLAN.items():
            print(bug or "clean", len(cells))
        raise SystemExit(0)
    raise SystemExit(main())
