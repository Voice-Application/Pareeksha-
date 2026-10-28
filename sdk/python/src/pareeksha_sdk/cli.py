"""``pareeksha`` command line (docs/10 section 3.2).

Exit codes: 0 success, 1 the thing under test failed (threshold, regression suite, run failed),
2 the tool could not do its job (bad config, API error, timeout, not logged in).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from pareeksha_sdk.apply import apply_config, resolve_suite
from pareeksha_sdk.client import Pareeksha
from pareeksha_sdk.config import (
    ProjectConfig,
    ScenarioSelector,
    Suite,
    load_config,
    load_profile,
    save_profile,
)
from pareeksha_sdk.errors import ApiError, PareekshaError
from pareeksha_sdk.models import Run
from pareeksha_sdk.summary import Verdict, judge_run, render_summary

app = typer.Typer(help="Pareeksha: crash-test voice agents.", no_args_is_help=True)
dlq_app = typer.Typer(help="Inspect and replay dead letters.", no_args_is_help=True)
app.add_typer(dlq_app, name="dlq")

EXIT_FAILED = 1
EXIT_ERROR = 2

ConfigOpt = Annotated[Path, typer.Option("--config", "-f", help="pareeksha.yaml")]


def _fail(message: str, code: int = EXIT_ERROR) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code)


@contextmanager
def _client() -> Iterator[Pareeksha]:
    """Open a client from the saved profile and turn SDK errors into exit code 2."""
    try:
        url, key = load_profile()
        client = Pareeksha(url, key)
    except PareekshaError as exc:
        raise _fail(str(exc)) from exc
    try:
        yield client
    except ApiError as exc:
        raise _fail(f"API error: {exc}") from exc
    except PareekshaError as exc:
        raise _fail(str(exc)) from exc
    finally:
        client.close()


def _progress(run: Run) -> None:
    p = run.progress
    typer.echo(f"  {run.status}: {p.evaluated}/{p.total} evaluated, {p.error} error", err=True)


def _write_summaries(text: str, summary_file: Path | None) -> None:
    targets = [summary_file] if summary_file else []
    env_target = os.environ.get("GITHUB_STEP_SUMMARY")
    if env_target:
        targets.append(Path(env_target))
    for target in targets:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(text)


def _finish(
    client: Pareeksha,
    title: str,
    run: Run,
    verdict: Verdict,
    fail_under: float | None,
    summary_file: Path | None,
) -> None:
    items = client.runs.items(run.id)
    web = os.environ.get("PAREEKSHA_WEB_URL")
    url = f"{web.rstrip('/')}/runs/{run.id}" if web else None
    _write_summaries(
        render_summary(title, run, verdict, items, fail_under=fail_under, run_url=url),
        summary_file,
    )
    s = run.summary
    rate = "n/a" if s.pass_rate is None else f"{s.pass_rate * 100:.1f}%"
    typer.echo(f"run {run.id}: {run.status}, pass rate {rate}, critical {s.critical_failures}")
    for reason in verdict.reasons:
        typer.echo(f"FAIL: {reason}", err=True)
    if not verdict.ok:
        raise typer.Exit(EXIT_FAILED)


@app.command()
def login(
    url: Annotated[str, typer.Option(help="API base URL, e.g. http://localhost:8000")],
    key: Annotated[str, typer.Option(help="API key (pk_live_...)")],
) -> None:
    """Save the API URL and key to ~/.config/pareeksha/config.toml."""
    try:
        Pareeksha(url, key).health()
    except Exception as exc:
        raise _fail(f"cannot reach {url}: {exc}") from exc
    path = save_profile(url, key)
    typer.echo(f"logged in; profile saved to {path}")


@app.command()
def apply(config: ConfigOpt = Path("pareeksha.yaml")) -> None:
    """Upsert agent, scenarios, personas and noise profiles from pareeksha.yaml by name."""
    cfg = _load(config)
    with _client() as client:
        report = apply_config(client, cfg)
    for line in report.lines():
        typer.echo(line)
    typer.echo(f"{report.changed} change(s)")


def _load(path: Path) -> ProjectConfig:
    try:
        return load_config(path)
    except PareekshaError as exc:
        raise _fail(str(exc)) from exc


@app.command()
def run(
    agent: Annotated[str | None, typer.Option(help="Agent name (default: agent in config)")] = None,
    tags: Annotated[str | None, typer.Option(help="Comma-separated scenario tags")] = None,
    suite: Annotated[str | None, typer.Option(help="Suite name from pareeksha.yaml")] = None,
    persona: Annotated[list[str] | None, typer.Option(help="Persona name (repeatable)")] = None,
    noise: Annotated[list[str] | None, typer.Option(help="Noise profile (repeatable)")] = None,
    config: ConfigOpt = Path("pareeksha.yaml"),
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = False,
    fail_under: Annotated[float | None, typer.Option(help="Min pass rate in percent")] = None,
    timeout: Annotated[float, typer.Option(help="Seconds to wait for the run")] = 1800,
    poll: Annotated[float, typer.Option(help="Seconds between status polls")] = 3.0,
    summary_file: Annotated[Path | None, typer.Option(help="Append a Markdown summary")] = None,
) -> None:
    """Create a run; with --wait (implied by --fail-under) block and exit 1 below the threshold."""
    spec = Suite(
        scenarios=ScenarioSelector(tags=[t for t in (tags or "").split(",") if t]),
        personas=persona or [],
        noise_profiles=noise or [],
    )
    agent_name = agent
    if suite:
        cfg = _load(config)
        if suite not in cfg.suites:
            raise _fail(f"suite {suite!r} not found in {config}")
        spec = cfg.suites[suite]
        agent_name = agent or str(cfg.agent["name"])
        fail_under = spec.fail_under if fail_under is None else fail_under
    if not agent_name:
        raise _fail("--agent is required (or use --suite with a config that names the agent)")
    with _client() as client:
        resolved = resolve_suite(client, agent_name, spec)
        created = client.runs.create(
            resolved.agent.id,
            list(resolved.scenario_ids),
            list(resolved.persona_ids),
            list(resolved.noise_profile_ids),
            name=f"cli:{suite or 'adhoc'}",
            repeats=spec.repeats,
            max_concurrency=spec.max_concurrency,
        )
        typer.echo(f"created run {created.id} ({created.item_count} items)")
        if not (wait or fail_under is not None):
            return
        finished = client.runs.wait(
            created.id, timeout_s=timeout, poll_s=poll, on_progress=_progress
        )
        verdict = judge_run(finished, fail_under=fail_under)
        _finish(
            client, f"{agent_name} / {suite or 'run'}", finished, verdict, fail_under, summary_file
        )


@app.command()
def regress(
    agent: Annotated[str, typer.Option(help="Agent name")],
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = True,
    timeout: Annotated[float, typer.Option(help="Seconds to wait for the run")] = 1800,
    poll: Annotated[float, typer.Option(help="Seconds between status polls")] = 3.0,
    summary_file: Annotated[Path | None, typer.Option(help="Append a Markdown summary")] = None,
) -> None:
    """Run the blocking regression suite; exit 1 if the suite fails."""
    with _client() as client:
        agent_obj = client.agents.get_by_name(agent)
        created = client.runs.create_regression(agent_obj.id, name="cli:regress")
        typer.echo(f"created regression run {created.id} ({created.item_count} items)")
        if not wait:
            return
        finished = client.runs.wait(
            created.id, timeout_s=timeout, poll_s=poll, on_progress=_progress
        )
        verdict = judge_run(finished, require_suite=True)
        _finish(client, f"{agent} / regression", finished, verdict, None, summary_file)


@app.command()
def audit(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    agent: Annotated[str, typer.Option(help="Agent name (rubric context)")],
    language: Annotated[str, typer.Option(help="e.g. kn-IN or kn-IN,en-IN")],
    timeout: Annotated[float, typer.Option(help="Seconds to wait for the result")] = 600,
    poll: Annotated[float, typer.Option(help="Seconds between status polls")] = 3.0,
) -> None:
    """Upload a recording and print the evaluation."""
    with _client() as client:
        agent_obj = client.agents.get_by_name(agent)
        ref = client.audits.create(file, agent_obj.id, language)
        typer.echo(f"uploaded; call {ref.call_id}", err=True)
        call = client.audits.wait(ref.call_id, timeout_s=timeout, poll_s=poll)
    typer.echo(call.model_dump_json(indent=2))
    if call.status == "error":
        raise typer.Exit(EXIT_FAILED)


@dlq_app.command("list")
def dlq_list(status: str = "open") -> None:
    """List dead letters."""
    with _client() as client:
        items = client.dlq.list(status)
    for d in items:
        typer.echo(f"{d.id}  {d.original_topic}  attempts={d.attempts}  {d.error}")
    typer.echo(f"{len(items)} dead letter(s)")


@dlq_app.command("replay")
def dlq_replay(dead_letter_id: str) -> None:
    """Re-publish one dead letter."""
    with _client() as client:
        client.dlq.replay(dead_letter_id)
    typer.echo(f"replay requested for {dead_letter_id}")


@app.command()
def doctor() -> None:
    """Check API, database and Kafka connectivity; exit 1 if any is down."""
    down = False
    with _client() as client:
        health = client.health()
        for name, value in (("db", health.db), ("kafka", health.kafka)):
            ok = value == "ok"
            down |= not ok
            typer.echo(f"{'ok  ' if ok else 'DOWN'} {name}: {value}")
        typer.echo("ok   api: reachable and key accepted")
        metrics = client.metrics_summary()
        dlq_open, backlog = metrics.get("dlq_open"), metrics.get("outbox_backlog")
        typer.echo(f"info dlq_open={dlq_open} outbox_backlog={backlog}")
    typer.echo("n/a  gnani, gemini: the API exposes no connectivity probe for these yet", err=True)
    if down:
        raise typer.Exit(EXIT_FAILED)


if __name__ == "__main__":  # pragma: no cover
    app()
