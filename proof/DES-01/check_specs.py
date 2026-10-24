#!/usr/bin/env python3
"""Check docs/design/pages: every FR-DB-1 page has a spec with Components, Data and Empty/Loading/Error states.
Run: python3 -I proof/DES-01/check_specs.py   (exit 1 on any gap)"""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
pages = root / "docs/design/pages"
req = (root / "docs/02-requirements.md").read_text()
fr = re.search(r"\| FR-DB-1 \| Next\.js web app pages: (.*?)\. \|", req).group(1)
names = [n.strip() for n in re.sub(r"\(\+[^)]*\)", "", fr).split(",")]
print("FR-DB-1 pages:", len(names), names)
mapping = {"Overview": "01", "Agents": "02", "Scenarios": "03", "Personas": "04", "Noise profiles": "05", "Runs": "06",
           "New run wizard": "07", "Run detail": "08", "Run compare": "09", "Call detail": "10", "Audits": "11", "Dialect": "12",
           "Regression": "13", "Integrations": "14", "DLQ": "15", "Calibration": "16", "API keys": "17"}
bad = 0
for n in names:
    key = n.split(" (")[0]
    if key not in mapping:
        print("NO MAPPING", n)
        bad += 1
        continue
    f = next(pages.glob(mapping[key] + "-*.md"), None)
    if not f:
        print("MISSING SPEC", n)
        bad += 1
        continue
    t = f.read_text()
    miss = [h for h in ("## Components", "## Data", "## States") if h not in t and not (h == "## Components" and "## Components" in t)]
    # headings may carry suffixes; check by prefix
    miss = [h for h in ("## Components", "## Data", "## States") if not re.search(r"^" + re.escape(h), t, re.M)]
    st = t.split("## States")[-1].lower() if "## States" in t else ""
    for w in ("empty", "loading", "error"):
        if w not in st:
            miss.append("state:" + w)
    print(("ok  " if not miss else "FAIL"), f.name, len(t.splitlines()), "lines", miss or "")
    bad += bool(miss)
print("RESULT:", "PASS" if not bad else f"FAIL ({bad})")
sys.exit(1 if bad else 0)
