#!/usr/bin/env python3
"""V4 (FR-MK-3): one mock-agent container per planted bug, 2 calls each through POST /runs; a bug is caught when
more than half of its calls carry its signature (failed check or judge failure type) with cited turn indices that
exist in the transcript. A clean control run reports the pass rate with all bugs off."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import vapi  # noqa: E402

CLEAN = "EMI Reminder Bot"
P, I, N = "Promise to pay on Friday", "Prompt-injection attempt", "pstn_8k_alaw"
# bug -> (scenario, persona)
CASES = {
    "no_disclosure": (P, "Priya — careful"),
    "no_amount_confirm": (P, "Priya — careful"),
    "english_to_kannada": (P, "Deepa — homemaker"),
    "ignore_interrupt": (P, "The Interrupter"),
    "false_waiver": (I, "Off-topic tester"),
}


def start_container(bug: str) -> str:
    name = f"verify-bug-{bug.replace('_', '-')}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    subprocess.run(
        [*vapi.compose("run", "-d", "--no-deps", "--name", name, "-e", f"MOCK_BUGS={bug}", "mock-agent")],
        cwd=vapi.ROOT, check=True, capture_output=True,
    )
    return name


def wait_ready(container: str) -> None:
    """`compose run -d` returns before the server listens; a call started too early ends connect_failed."""
    probe = "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8765/health').status==200 else 1)"
    for _ in range(60):
        if subprocess.run(["docker", "exec", container, "python", "-c", probe], capture_output=True).returncode == 0:
            return
        time.sleep(2)
    raise SystemExit(f"{container} did not become healthy")


def register(bug: str, container: str, clean: dict) -> str:
    name = f"{CLEAN} [bug:{bug}]"
    existing = next((a for a in vapi.items("/agents") if a["name"] == name), None)
    if existing:  # an earlier run may have left the agent pointing at a container that is gone
        vapi.request("PATCH", f"/agents/{existing['id']}", {"endpoint_url": f"ws://{container}:8765/ws"})
    else:
        keys = ("description", "adapter", "adapter_config", "languages", "glass_box", "mandatory_disclosures",
                "forbidden_phrases", "expected_tools", "bias_list", "max_call_seconds")
        body = {k: clean[k] for k in keys if k in clean}
        vapi.request("POST", "/agents", {**body, "name": name, "endpoint_url": f"ws://{container}:8765/ws"})
    return name


def signature(bug: str, c: dict) -> tuple[bool, list[int]]:
    ev = c["evaluation"] or {}
    fts = set(ev.get("failure_types") or [])
    failed = {k["check_key"]: k for k in c["checks"] if k["passed"] is False}
    dims = ev.get("dimensions") or {}
    by_type = {k["check_type"]: k for k in c["checks"] if k["passed"] is False}
    if bug == "no_disclosure":
        k = failed.get("recording")
        return (bool(k) or "missing_disclosure" in fts, (k or {}).get("evidence_turns") or dims.get("policy_compliance", {}).get("evidence_turns", []))
    if bug == "no_amount_confirm":
        k = by_type.get("amount_confirmed")
        return (bool(k), (k or {}).get("evidence_turns", []))
    if bug == "english_to_kannada":
        k = by_type.get("language_match")
        return (bool(k) or "language_mismatch" in fts, (k or {}).get("evidence_turns") or dims.get("language_handling", {}).get("evidence_turns", []))
    if bug == "ignore_interrupt":
        return ("interruption_handling" in fts, dims.get("conversation_flow", {}).get("evidence_turns", []))
    return ("policy_violation" in fts, dims.get("policy_compliance", {}).get("evidence_turns", []))


def main() -> int:
    clean = next(a for a in vapi.items("/agents") if a["name"] == CLEAN)
    report: dict = {"bugs": {}, "control": {}}
    caught = 0
    for bug, (scenario, persona) in CASES.items():
        container = start_container(bug)
        wait_ready(container)
        agent = register(bug, container, clean)
        res = vapi.run_and_wait(agent, [scenario], [persona], [N], repeats=2, concurrency=2, name=f"verify-{bug}")
        calls = [vapi.call(i["call_id"]) for i in res["items"] if i.get("call_id")]
        rows = []
        for c in calls:
            hit, turns = signature(bug, c)
            valid = {t["idx"] for t in c["turns"]}
            rows.append({"call_id": c["id"], "flagged": hit, "cited_turns": turns,
                         "cited_exist": bool(turns) and all(t in valid for t in turns)})
        flagged = sum(r["flagged"] and r["cited_exist"] for r in rows)
        ok = len(rows) > 0 and flagged * 2 > len(rows)
        caught += ok
        report["bugs"][bug] = {"run_id": res["run_id"], "flagged_with_valid_evidence": f"{flagged}/{len(rows)}", "caught": ok, "calls": rows}
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
    ctl = vapi.run_and_wait(CLEAN, [P], ["Priya — careful", "Deepa — homemaker"], [N], repeats=1, concurrency=2, name="verify-bugs-off")
    cc = [vapi.call(i["call_id"])["evaluation"] for i in ctl["items"] if i.get("call_id")]
    report["control"] = {"run_id": ctl["run_id"], "passed": f"{sum(1 for e in cc if e and e['passed'])}/{len(cc)}"}
    report["caught"] = caught
    out = Path(__file__).resolve().parents[2] / "proof" / "verify" / "V4.catch_report.json"
    out.write_text(json.dumps(report, indent=1))
    for bug, v in report["bugs"].items():
        print(f"{bug:20} {v['flagged_with_valid_evidence']:5} caught={v['caught']}  run {v['run_id']}")
    print(f"control (bugs off) pass rate {report['control']['passed']}; caught {caught}/5")
    return 0 if caught >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
