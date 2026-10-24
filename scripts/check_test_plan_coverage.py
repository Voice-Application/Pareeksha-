#!/usr/bin/env python3
"""Fail if docs/TEST_PLAN.md does not cover every requirement, task, GOAL item and verify step."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
plan = (ROOT / "docs/TEST_PLAN.md").read_text()
reqs = (ROOT / "docs/02-requirements.md").read_text()
agents = (ROOT / "docs/AGENTS.md").read_text()
goal = (ROOT / "docs/orchestration/GOAL.md").read_text()

errors = []

req_ids = sorted(
    set(re.findall(r"^\| ((?:N?FR)-(?:[A-Z]+-)?\d+[a-z]?) \|", reqs, re.M))
)
task_ids = set(re.findall(r"^- \*\*([A-Z]+-\d+)\*\*", agents, re.M)) | {"ALL"}

section2 = plan.split("## 2.")[1].split("\n## 3.")[0]
rows = {}
for line in section2.splitlines():
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) == 8 and re.fullmatch(r"N?FR-.*\d[a-z]?", cells[0]):
        rows[cells[0]] = cells

for rid in req_ids:
    row = rows.get(rid)
    if not row:
        errors.append(f"requirement {rid} missing from plan section 2")
        continue
    _, _, test_id, level, loc, owner, feat, _ = row
    if test_id != f"T-{rid}" or not level or not loc.strip("`"):
        errors.append(f"{rid}: missing test id/level/location")
    for t in re.split(r"[,\s]+", owner + " " + feat):
        if t and t not in task_ids:
            errors.append(f"{rid}: unknown task '{t}'")
for rid in rows:
    if rid not in req_ids:
        errors.append(f"plan lists unknown requirement {rid}")

goal_items = re.findall(r"^(\d+) ", goal, re.M)
section4 = plan.split("## 4.")[1].split("\n## 5.")[0]
for n in goal_items:
    if not re.search(rf"^\| {n} \|", section4, re.M):
        errors.append(f"GOAL.md item {n} unmapped")
    if not re.search(rf"V{n}:", section4):
        errors.append(f"verify step V{n} missing")
if len(goal_items) != 11:
    errors.append(f"expected 11 GOAL.md items, found {len(goal_items)}")

section3 = plan.split("## 3.")[1].split("\n## 4.")[0]
metric_rows = [
    l for l in section3.splitlines() if l.startswith("| ") and "V" in l.split("|")[-2]
]
if len(metric_rows) != 9:
    errors.append(f"expected 9 PRD section 8 metric rows, found {len(metric_rows)}")

print(
    f"requirements in 02-requirements.md: {len(req_ids)} "
    f"({sum(i.startswith('FR') for i in req_ids)} FR, {sum(i.startswith('NFR') for i in req_ids)} NFR)"
)
print(f"requirements mapped in plan:        {len([r for r in req_ids if r in rows])}")
print(
    f"GOAL.md items mapped:               {len([n for n in goal_items if re.search(rf'^\| {n} \|', section4, re.M)])}/11"
)
print(f"PRD section 8 metric rows:          {len(metric_rows)}/9")
if errors:
    print("FAIL")
    print("\n".join(errors))
    sys.exit(1)
print("PASS: every FR/NFR, GOAL item and verify step is mapped")
