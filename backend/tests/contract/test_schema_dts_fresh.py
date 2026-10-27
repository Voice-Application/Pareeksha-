"""FR-DB-6: web/lib/api/schema.d.ts regenerated from the OpenAPI equals the committed file."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from pareeksha.api.main import app

WEB = Path(__file__).resolve().parents[3] / "web"


def test_committed_schema_dts_matches_the_backend_openapi(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node, "node is required to run web/scripts/gen-api.mjs (install Node 20+)"
    assert (WEB / "node_modules" / "openapi-typescript").exists(), "run `npm ci` in web/ first"
    spec = tmp_path / "openapi.json"
    spec.write_text(json.dumps(app.openapi()))
    done = subprocess.run(
        [node, "scripts/gen-api.mjs", "--check", "--from", str(spec)],
        cwd=WEB,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (
        "web/lib/api/schema.d.ts is stale; run `npm run gen:api` in web/.\n"
        + done.stdout
        + done.stderr
    )
