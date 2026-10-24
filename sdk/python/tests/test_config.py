from __future__ import annotations

from pathlib import Path

import pytest

from pareeksha_sdk.config import load_config, load_profile, save_profile
from pareeksha_sdk.errors import ConfigError
from pareeksha_sdk.models import Run
from pareeksha_sdk.summary import judge_run, render_summary

EXAMPLE = Path(__file__).parents[1] / "pareeksha.example.yaml"


def test_example_config_loads() -> None:
    cfg = load_config(EXAMPLE)
    assert cfg.agent["name"] == "EMI Reminder Bot"
    assert cfg.suites["pr_check"].fail_under == 80
    assert len(cfg.scenarios) == 2


def test_file_reference_is_inlined(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "sys.md").write_text("You are an EMI bot.\n")
    (tmp_path / "p.yaml").write_text(
        "version: 1\nagent: {name: A, description: 'file://prompts/sys.md'}\n"
    )
    assert load_config(tmp_path / "p.yaml").agent["description"] == "You are an EMI bot."
    (tmp_path / "q.yaml").write_text(
        "version: 1\nagent: {name: A, description: 'file://nope.md'}\n"
    )
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "q.yaml")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- not a mapping", "mapping"),
        (": : :", "valid YAML"),
        ("version: 1\nagent: {adapter: x}\n", "'name' is required"),
        ("version: 1\nagent: {name: A, bogus: 1}\n", "unknown field"),
        ("version: 1\nagent: {name: A}\nscenarios: [{caller_goal: g}]\n", "'title' is required"),
        (
            "version: 1\nagent: {name: A}\nscenarios: [{title: t}, {title: t}]\n",
            "duplicate",
        ),
        ("version: 1\nagent: {name: A}\npersonas: [{voice: x}]\n", "'name' is required"),
        ("version: 1\nagent: {name: A}\nsuites: {s: {fail_under: 500}}\n", "fail_under"),
        ("version: 1\nagent: {name: A}\nextra: 1\n", "extra"),
    ],
)
def test_invalid_configs(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "x.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_profile_roundtrip_escaping_and_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "c.toml"
    save_profile("http://h", 'k"ey\\1', path)
    monkeypatch.delenv("PAREEKSHA_URL", raising=False)
    monkeypatch.delenv("PAREEKSHA_KEY", raising=False)
    assert load_profile(path) == ("http://h", 'k"ey\\1')
    monkeypatch.setenv("PAREEKSHA_URL", "http://env")
    monkeypatch.setenv("PAREEKSHA_KEY", "envkey")
    assert load_profile(path) == ("http://env", "envkey")
    monkeypatch.delenv("PAREEKSHA_URL")
    monkeypatch.delenv("PAREEKSHA_KEY")
    path.write_text("not = [valid")
    with pytest.raises(ConfigError, match="not logged in"):
        load_profile(path)


def test_default_profile_location(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from pareeksha_sdk.config import profile_path

    monkeypatch.delenv("PAREEKSHA_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert profile_path() == tmp_path / "pareeksha" / "config.toml"


def run_of(**kw: object) -> Run:
    base = {"id": "8a0e6b1e-0000-4000-8000-000000000001", "status": "completed"}
    return Run.model_validate({**base, **kw})


def test_judge_run_rules() -> None:
    ok = run_of(summary={"pass_rate": 0.85})
    assert judge_run(ok, fail_under=80).ok
    assert not judge_run(ok, fail_under=90).ok
    assert "no pass rate" in judge_run(run_of(), fail_under=80).reasons[0]
    assert "partially" in judge_run(run_of(status="partial")).reasons[0]
    assert "cancelled" in judge_run(run_of(status="cancelled")).reasons[0]
    assert "not finished" in judge_run(run_of(status="running")).reasons[0]
    assert not judge_run(ok, require_suite=True).ok
    assert judge_run(run_of(summary={"suite_passed": True}), require_suite=True).ok


def test_render_summary_content() -> None:
    run = run_of(
        summary={
            "pass_rate": 0.5,
            "critical_failures": 2,
            "suite_passed": False,
            "top_failure_types": [["wrong_fact", 3]],
        },
        progress={"total": 4, "evaluated": 4},
    )
    text = render_summary("Bot / suite", run, judge_run(run, fail_under=80), [], fail_under=80)
    assert "FAIL" in text and "wrong_fact: 3" in text and "50.0%" in text
    assert "Regression suite | FAILED" in text and "below 80%" in text
