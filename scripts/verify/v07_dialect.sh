#!/usr/bin/env bash
# V7 (FR-DI-1..6, NFR-9): the dialect HTML report has >= 5 groups (>= 3 Kannada + Hindi + code-mixed), n >= 20 per
# group and a CI on every cell, and no clip without consent=true in the database. Reads the newest report in the
# database. Without one (no stack, or a fresh database) it applies the same criteria to the verifier's own run committed
# in proof/DIALECT-02/verifier (report.json, report.html, and the dialect_samples count that run read from its database),
# only if those files are unchanged since that verification. It says so in the evidence and does not claim a re-run.
# PENDING when neither exists.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 7 "Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs"
art=proof/DIALECT-02/verifier
verified_sha=b248279  # qa/DIALECT-02: the commit recording the verifier's run
# a database that cannot be reached is not an empty one
if reports=$(psql_q "SELECT count(*) FROM dialect_reports" 2>/dev/null); then db="dialect_reports rows: $reports"; else reports=0; db="database not reachable"; fi
if [ "${reports:-0}" -gt 0 ]; then
  source=db; note "Source: newest report in the database ($db)."
elif head -1 proof/DIALECT-02/verified.md 2>/dev/null | grep -q 'verified: PASS' && [ -f "$art/report.json" ] \
     && git diff --quiet "$verified_sha" -- "$art/report.json" "$art/report.html" "$art/usage.json" 2>/dev/null; then
  source=artefact; note "Source: the verifier's run in $art, unchanged since $verified_sha (proof/DIALECT-02/verified.md). Not re-run here ($db); the live run needs the dialect worker plus Gnani and DeepSeek keys."
else
  note "No dialect report in the database ($db) and no unchanged verified run in $art."
  finish PENDING "no dialect report exists"
fi
V7_SOURCE=$source V7_ART=$art $PY - <<'PYEOF' | tee "$OUT/V7.json" | block
import json, os, sys
sys.path.insert(0, "scripts/verify")
import vapi
art = os.environ["V7_ART"]
if os.environ["V7_SOURCE"] == "db":
    agg = json.loads(vapi.sql("SELECT aggregates FROM dialect_reports ORDER BY created_at DESC LIMIT 1"))
    without_consent = int(vapi.sql("SELECT count(*) FROM dialect_samples WHERE NOT consent"))
    html_path = vapi.sql("SELECT html_path FROM dialect_reports ORDER BY created_at DESC LIMIT 1")
    extra = {}
else:
    agg = json.load(open(f"{art}/report.json", encoding="utf-8"))["aggregates"]
    total, consented = json.load(open(f"{art}/usage.json", encoding="utf-8"))["samples_total_and_consented"]
    without_consent = total - consented if total else 1  # no samples recorded proves nothing
    html_path = f"{art}/report.html"
    html = open(html_path, encoding="utf-8").read()
    cells = sum(len(engines) for conds in agg.values() for engines in conds.values())
    extra = {"db_samples_total_and_consented_recorded_by_run": [total, consented],
             "html_ok": "<table" in html and all(d in html for d in agg) and html.count("95% CI") >= cells}
groups = {}
missing_ci = 0
for dialect, conds in agg.items():
    for cond, engines in conds.items():
        for engine, cell in engines.items():
            groups[dialect] = max(groups.get(dialect, 0), int(cell.get("n", 0)))
            if not cell.get("wer_ci"):
                missing_ci += 1
kn = [d for d in groups if d.startswith("kn-") and d != "kn-en-mix"]
res = {"groups": groups, "kannada_groups": len(kn), "has_hindi": any(d.startswith("hi-") for d in groups),
       "has_code_mixed": any("mix" in d for d in groups), "cells_without_ci": missing_ci,
       "min_n": min(groups.values()) if groups else 0,
       "clips_without_consent": without_consent, "html_path": html_path, **extra}
res["ok"] = (res["kannada_groups"] >= 3 and res["has_hindi"] and res["has_code_mixed"] and len(groups) >= 5
             and res["min_n"] >= 20 and missing_ci == 0 and res["clips_without_consent"] == 0
             and res.get("html_ok", True))
print(json.dumps(res, indent=1))
sys.exit(0 if res["ok"] else 1)
PYEOF
rc=${PIPESTATUS[0]}
[ "$rc" -ne 0 ] && finish FAIL "report does not meet the criteria (see JSON)"
[ "$source" = db ] && finish PASS "report meets group, n, CI and consent criteria"
finish PASS "verifier's DIALECT-02 run meets group, n, CI and consent criteria; recorded run, not re-run here"
