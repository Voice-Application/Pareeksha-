"""Drive the installed `pareeksha` executable (real subprocesses) against the in-memory fake platform.

Run from sdk/python:  python ../../proof/INT-04/demo.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "sdk" / "python"))
from tests.fake_platform import API_KEY, State, serve  # noqa: E402

EXAMPLE = Path(__file__).parents[2] / "sdk" / "python" / "pareeksha.example.yaml"


def main() -> None:
    state = State()
    with serve(state) as url, tempfile.TemporaryDirectory() as tmp:
        yaml_path = Path(tmp) / "pareeksha.yaml"
        shutil.copy(EXAMPLE, yaml_path)
        env = {**os.environ, "PAREEKSHA_URL": url, "PAREEKSHA_KEY": API_KEY,
               "GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary.md")}

        def cli(*args: str) -> int:
            print("$ pareeksha", *args)
            done = subprocess.run(["pareeksha", *args], env=env, text=True, capture_output=True)
            print(done.stdout + done.stderr, end="")
            print(f"[exit {done.returncode}]\n")
            return done.returncode

        cli("apply", "-f", str(yaml_path))
        writes = state.writes
        cli("apply", "-f", str(yaml_path))
        print(f"writes after first apply: {writes}, after second: {state.writes}\n")
        cli("run", "--suite", "pr_check", "-f", str(yaml_path), "--wait", "--poll", "0.05")
        cli("run", "--suite", "pr_check", "-f", str(yaml_path), "--wait", "--fail-under", "101",
            "--poll", "0.05")
        state.suite_passed = False
        cli("regress", "--agent", "EMI Reminder Bot", "--poll", "0.05")
        cli("doctor")
        print("--- $GITHUB_STEP_SUMMARY ---")
        print((Path(tmp) / "summary.md").read_text())


if __name__ == "__main__":
    main()
