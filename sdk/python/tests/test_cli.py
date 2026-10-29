"""CLI end to end: real HTTP against the in-memory fake platform."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pareeksha_sdk.cli import app
from tests.fake_platform import API_KEY, State, add_dead_letter

runner = CliRunner()
EXAMPLE = Path(__file__).parents[1] / "pareeksha.example.yaml"


@pytest.fixture
def yaml_path(tmp_path: Path) -> str:
    target = tmp_path / "pareeksha.yaml"
    shutil.copy(EXAMPLE, target)
    return str(target)


def invoke(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def test_login_saves_profile_and_checks_reachability(
    base_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "p" / "config.toml"
    monkeypatch.setenv("PAREEKSHA_CONFIG", str(profile))
    code, out = invoke("login", "--url", base_url, "--key", API_KEY)
    assert code == 0 and "logged in" in out
    assert profile.exists() and (profile.stat().st_mode & 0o777) == 0o600
    code, out = invoke("login", "--url", "http://127.0.0.1:9", "--key", "x")
    assert code == 2 and "cannot reach" in out


def test_commands_require_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAREEKSHA_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.delenv("PAREEKSHA_URL", raising=False)
    monkeypatch.delenv("PAREEKSHA_KEY", raising=False)
    code, out = invoke("doctor")
    assert code == 2 and "not logged in" in out


def test_env_credentials_override_profile(
    base_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAREEKSHA_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("PAREEKSHA_URL", base_url)
    monkeypatch.setenv("PAREEKSHA_KEY", API_KEY)
    assert invoke("doctor")[0] == 0


def test_wrong_key_is_exit_2(
    base_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAREEKSHA_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("PAREEKSHA_URL", base_url)
    monkeypatch.setenv("PAREEKSHA_KEY", "pk_live_wrong")
    code, out = invoke("dlq", "list")
    assert code == 2 and "unauthorized" in out


def test_apply_twice_changes_nothing(logged_in: str, state: State, yaml_path: str) -> None:
    code, out = invoke("apply", "-f", yaml_path)
    assert code == 0 and "created   agent: EMI Reminder Bot" in out
    first_writes = state.writes
    assert first_writes == 5  # agent, 2 scenarios, 1 persona, 1 noise profile
    code, out = invoke("apply", "-f", yaml_path)
    assert code == 0 and "0 change(s)" in out
    assert state.writes == first_writes  # no write at all the second time
    assert len(state.agents) == 1 and len(state.scenarios) == 2


def test_apply_updates_only_what_changed(logged_in: str, state: State, yaml_path: str) -> None:
    invoke("apply", "-f", yaml_path)
    text = Path(yaml_path).read_text().replace("snr_db: 5", "snr_db: 10")
    Path(yaml_path).write_text(text)
    code, out = invoke("apply", "-f", yaml_path)
    assert code == 0 and "updated   noise profile: pstn_market_5db" in out and "1 change(s)" in out


def test_apply_bad_config_exit_2(logged_in: str, tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 2\nagent: {name: x, bogus: 1}\n")
    code, out = invoke("apply", "-f", str(bad))
    assert code == 2 and "version" in out
    code, out = invoke("apply", "-f", str(tmp_path / "nope.yaml"))
    assert code == 2


def test_run_fail_under_101_exits_1(logged_in: str, yaml_path: str, tmp_path: Path) -> None:
    invoke("apply", "-f", yaml_path)
    summary = tmp_path / "summary.md"
    code, out = invoke(
        "run",
        "--suite",
        "pr_check",
        "-f",
        yaml_path,
        "--wait",
        "--fail-under",
        "101",
        "--poll",
        "0.01",
        "--summary-file",
        str(summary),
    )
    assert code == 1
    assert "below 101%" in out
    assert "FAIL" in summary.read_text()


def test_run_passes_and_writes_github_step_summary(
    logged_in: str, yaml_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoke("apply", "-f", yaml_path)
    step = tmp_path / "step.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    monkeypatch.setenv("PAREEKSHA_WEB_URL", "https://pareeksha.example.com")
    code, out = invoke("run", "--suite", "pr_check", "-f", yaml_path, "--poll", "0.01", "--wait")
    assert code == 0, out  # fail_under 80 comes from the suite; pass rate is 90%
    text = step.read_text()
    assert "PASS" in text and "90.0%" in text and "threshold 80%" in text
    assert "https://pareeksha.example.com/runs/" in text


def test_run_regression_below_threshold_from_suite_exits_1(
    logged_in: str, state: State, yaml_path: str, tmp_path: Path
) -> None:
    invoke("apply", "-f", yaml_path)
    state.pass_rate = 0.4
    step = tmp_path / "s.md"
    code, _out = invoke(
        "run", "--suite", "pr_check", "-f", yaml_path, "--poll", "0.01", "--summary-file", str(step)
    )
    assert code == 1
    assert "Failing cells" in step.read_text() and "Already paid" in step.read_text()


def test_run_without_wait_returns_immediately(logged_in: str, yaml_path: str) -> None:
    invoke("apply", "-f", yaml_path)
    code, out = invoke("run", "--agent", "EMI Reminder Bot", "--tags", "happy_path")
    assert code == 0 and "created run" in out and "(1 items)" in out


def test_run_argument_errors(logged_in: str, yaml_path: str) -> None:
    invoke("apply", "-f", yaml_path)
    assert invoke("run")[0] == 2  # no agent
    assert invoke("run", "--suite", "nope", "-f", yaml_path)[0] == 2
    code, out = invoke("run", "--agent", "Missing Bot")
    assert code == 2 and "not found" in out
    code, out = invoke("run", "--agent", "EMI Reminder Bot", "--tags", "no_such_tag")
    assert code == 2 and "no scenarios" in out
    code, out = invoke("run", "--agent", "EMI Reminder Bot", "--persona", "Ghost")
    assert code == 2 and "persona(s) not found" in out


def test_regress_exit_codes(logged_in: str, state: State, yaml_path: str) -> None:
    invoke("apply", "-f", yaml_path)
    state.polls_until_done = 0
    code, out = invoke("regress", "--agent", "EMI Reminder Bot", "--poll", "0.01")
    assert code == 0, out
    state.suite_passed = False
    code, out = invoke("regress", "--agent", "EMI Reminder Bot", "--poll", "0.01")
    assert code == 1 and "regression suite failed" in out
    code, out = invoke("regress", "--agent", "EMI Reminder Bot", "--no-wait")
    assert code == 0 and "created regression run" in out


def test_regress_failed_run_status_exits_1(logged_in: str, state: State, yaml_path: str) -> None:
    invoke("apply", "-f", yaml_path)
    state.final_status = "failed"
    state.pass_rate = None
    code, out = invoke("regress", "--agent", "EMI Reminder Bot", "--poll", "0.01")
    assert code == 1 and "ERROR: run had infrastructure errors, no verdict" in out


def test_audit_uploads_and_prints_result(
    logged_in: str, state: State, yaml_path: str, tmp_path: Path
) -> None:
    invoke("apply", "-f", yaml_path)
    wav = tmp_path / "call.wav"
    wav.write_bytes(b"RIFF0000WAVE")
    code, out = invoke(
        "audit", str(wav), "--agent", "EMI Reminder Bot", "--language", "kn-IN", "--poll", "0.01"
    )
    assert code == 0 and '"completed"' in out
    assert state.audit_uploads == [
        {"name": "call.wav", "bytes": 12, "agent_id": next(iter(state.agents)), "language": "kn-IN"}
    ]
    assert (
        invoke("audit", str(tmp_path / "missing.wav"), "--agent", "x", "--language", "kn-IN")[0]
        == 2
    )


def test_dlq_list_and_replay(logged_in: str, state: State) -> None:
    dl = add_dead_letter(state)
    code, out = invoke("dlq", "list")
    assert code == 0 and dl in out and "1 dead letter(s)" in out
    code, out = invoke("dlq", "replay", dl)
    assert code == 0 and state.dlq[dl]["status"] == "replayed"
    assert "0 dead letter(s)" in invoke("dlq", "list")[1]


def test_doctor_reports_down_dependencies(logged_in: str, state: State) -> None:
    code, out = invoke("doctor")
    assert code == 0 and "ok   db: ok" in out and "ok   kafka: ok" in out
    state.kafka = "down: broker unreachable"
    code, out = invoke("doctor")
    assert code == 1 and "DOWN kafka" in out
