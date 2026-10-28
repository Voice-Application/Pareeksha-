#!/usr/bin/env bash
# V7 (FR-DI-1..6, NFR-9): the dialect HTML report has >= 5 groups (>= 3 Kannada + Hindi + code-mixed), n >= 20 per
# group and a CI on every cell, and no clip without consent=true in the database. Needs the owner's consented clips
# (H-02) run through the dialect worker; PENDING while the database has no report.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 7 "Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs"
reports=$(psql_q "SELECT count(*) FROM dialect_reports" 2>/dev/null || echo 0)
if [ "${reports:-0}" -eq 0 ]; then
  note "dialect_reports is empty: no consented clip set (H-02) has been run through the dialect worker."
  finish PENDING "no dialect report exists; needs the owner's consented clips (H-02)"
fi
$PY - <<'PYEOF' | tee "$OUT/V7.json" | block
import json, subprocess, sys, os
sys.path.insert(0, "scripts/verify")
import vapi
agg = json.loads(vapi.sql("SELECT aggregates FROM dialect_reports ORDER BY created_at DESC LIMIT 1"))
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
       "clips_without_consent": int(vapi.sql("SELECT count(*) FROM dialect_samples WHERE NOT consent")),
       "html_path": vapi.sql("SELECT html_path FROM dialect_reports ORDER BY created_at DESC LIMIT 1")}
res["ok"] = (res["kannada_groups"] >= 3 and res["has_hindi"] and res["has_code_mixed"] and len(groups) >= 5
             and res["min_n"] >= 20 and missing_ci == 0 and res["clips_without_consent"] == 0)
print(json.dumps(res, indent=1))
sys.exit(0 if res["ok"] else 1)
PYEOF
[ "${PIPESTATUS[0]}" -eq 0 ] && finish PASS "report meets group, n, CI and consent criteria"
finish FAIL "report does not meet the criteria (see JSON)"
