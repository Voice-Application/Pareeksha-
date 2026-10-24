"""Print per-call agent turn indices and the evidence line for each planted bug."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for d in sorted(root.glob("0*")):
    t = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    turns = [m for m in t["messages"] if m["type"] == "transcript"]
    print(f"== {d.name} (MOCK_BUGS='{t['mock_bugs']}', {t['language']}, agent audio {t['agent_seconds']:.1f}s)")
    for i, m in enumerate(turns):
        print(f"  turn {i} [{m['wall_s']:>5}s] {m['role']:5}: {m['text']}")
    for m in t["messages"]:
        if m["type"] == "tool_call":
            print(f"  tool_call [{m['wall_s']}s] {m['name']} {m.get('arguments')}")
