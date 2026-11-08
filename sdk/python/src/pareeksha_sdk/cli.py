"""``pareeksha`` command line (docs/10 section 3.2).

Exit codes: 0 success, 1 the thing under test failed (threshold, regression suite, run failed),
2 the tool could not do its job (bad config, API error, timeout, not logged in).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

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
prompt_app = typer.Typer(help="Prompt-agent versions.", no_args_is_help=True)
app.add_typer(prompt_app, name="prompt")
kb_app = typer.Typer(help="Knowledge bases for RAG testing.", no_args_is_help=True)
app.add_typer(kb_app, name="kb")
questions_app = typer.Typer(help="Ground-truth questions.", no_args_is_help=True)
kb_app.add_typer(questions_app, name="questions")
rag_app = typer.Typer(help="RAG matrices, reports and pricing.", no_args_is_help=True)
app.add_typer(rag_app, name="rag")

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
    label = "ERROR" if verdict.errored else "FAIL"
    for reason in verdict.reasons:
        typer.echo(f"{label}: {reason}", err=True)
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


@prompt_app.command("push")
def prompt_push(
    agent: Annotated[str, typer.Option(help="Agent name")],
    file: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="System prompt file")],
    provider: Annotated[str, typer.Option(help="e.g. openai, anthropic, gemini, ollama")],
    model: Annotated[str, typer.Option(help="Model id")],
    tools: Annotated[Path | None, typer.Option(help="JSON file with a list of tools")] = None,
    temperature: Annotated[float | None, typer.Option(help="Sampling temperature")] = None,
    base_url: Annotated[str | None, typer.Option(help="Provider base URL")] = None,
    note: Annotated[str | None, typer.Option(help="Version note")] = None,
) -> None:
    """Create a prompt version and make it active."""
    try:
        system_prompt = file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _fail(f"{file}: cannot read prompt file: {exc}") from exc
    fields: dict[str, Any] = {
        "system_prompt": system_prompt,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "temperature": temperature,
        "note": note,
    }
    if tools is not None:
        try:
            tools_text = tools.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise _fail(f"{tools}: cannot read tools file: {exc}") from exc
        try:
            fields["tools"] = json.loads(tools_text)
        except ValueError as exc:  # JSONDecodeError
            raise _fail(f"{tools}: invalid JSON: {exc}") from exc
        if not isinstance(fields["tools"], list):
            raise _fail(f"{tools}: expected a JSON list of tools")
    with _client() as client:
        agent_obj = client.agents.get_by_name(agent)
        result = client.create_prompt_version(
            agent_obj.id, **{k: v for k, v in fields.items() if v is not None}
        )
    if result.get("unchanged"):
        typer.echo(f"unchanged (still v{result['version']})")
    else:
        typer.echo(f"created v{result['version']} (active)")


@prompt_app.command("versions")
def prompt_versions(agent: Annotated[str, typer.Option(help="Agent name")]) -> None:
    """List prompt versions, newest first."""
    with _client() as client:
        versions = client.list_prompt_versions(client.agents.get_by_name(agent).id)
    for v in versions:
        typer.echo(f"v{v['version']}  {v.get('provider')}/{v.get('model')}  {v.get('note') or ''}")


@prompt_app.command("activate")
def prompt_activate(agent: Annotated[str, typer.Option(help="Agent name")], version: int) -> None:
    """Make an existing version the active one."""
    with _client() as client:
        client.activate_prompt_version(client.agents.get_by_name(agent).id, version)
    typer.echo(f"v{version} is now active")


@prompt_app.command("set-key")
def prompt_set_key(agent: Annotated[str, typer.Option(help="Agent name")]) -> None:
    """Store the LLM API key (env PAREEKSHA_AGENT_API_KEY or hidden prompt; write-only)."""
    key = os.environ.get("PAREEKSHA_AGENT_API_KEY") or typer.prompt("API key", hide_input=True)
    with _client() as client:
        client.agents.update(
            client.agents.get_by_name(agent).id, {"adapter_secrets": {"api_key": key}}
        )
    typer.echo("API key saved")


KbOpt = Annotated[str, typer.Option(help="Knowledge base name")]


def _env_key(var: str | None) -> str | None:
    """Read a key from the named env var; the key itself is never echoed."""
    if var is None:
        return None
    value = os.environ.get(var)
    if not value:
        raise _fail(f"environment variable {var} is not set")
    return value


@kb_app.command("create")
def kb_create(
    name: Annotated[str, typer.Argument(help="Knowledge base name")],
    local_only: Annotated[bool, typer.Option(help="Never send its text to a hosted LLM")] = False,
    description: Annotated[str, typer.Option(help="Description")] = "",
    embedding_key_env: Annotated[
        str | None, typer.Option(help="Env var holding the embedding API key")
    ] = None,
    reranker_key_env: Annotated[
        str | None, typer.Option(help="Env var holding the reranker API key")
    ] = None,
) -> None:
    """Create a knowledge base (keys are read from the named env vars, never from arguments)."""
    secrets = {
        "embedding_api_key": _env_key(embedding_key_env),
        "reranker_api_key": _env_key(reranker_key_env),
    }
    fields: dict[str, Any] = {"description": description}
    if any(secrets.values()):
        fields["secrets"] = {k: v for k, v in secrets.items() if v}
    with _client() as client:
        kb = client.kb.create(name, local_only=local_only, **fields)
    typer.echo(f"created knowledge base {kb['name']} ({kb['id']})")


@kb_app.command("set-keys")
def kb_set_keys(kb: KbOpt) -> None:
    """Replace the stored embedding/reranker keys (hidden prompts; blank clears that key)."""
    secrets = {
        "embedding_api_key": typer.prompt(
            "Embedding API key", default="", hide_input=True, show_default=False
        ),
        "reranker_api_key": typer.prompt(
            "Reranker API key", default="", hide_input=True, show_default=False
        ),
    }
    with _client() as client:
        client.kb.update(
            client.kb.get_by_name(kb)["id"], secrets={k: v for k, v in secrets.items() if v}
        )
    typer.echo("keys saved")


@kb_app.command("upload")
def kb_upload(
    files: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, readable=True)],
    kb: KbOpt,
) -> None:
    """Upload documents (txt, md, html, csv, json, pdf, docx)."""
    with _client() as client:
        kb_id = client.kb.get_by_name(kb)["id"]
        for file in files:
            doc = client.kb.upload(kb_id, file)
            state = "already there" if doc["unchanged"] else "uploaded"
            typer.echo(f"{state}: {file.name} ({doc['char_count']} chars)")


@kb_app.command("index")
def kb_index(
    kb: KbOpt,
    strategy: Annotated[
        str, typer.Option(help="fixed, recursive or sentence_window")
    ] = "recursive",
    size: Annotated[int, typer.Option(help="Chunk size in characters")] = 800,
    overlap: Annotated[int, typer.Option(help="Chunk overlap in characters")] = 100,
    embedding: Annotated[str, typer.Option(help="provider:model")] = (
        "local:intfloat/multilingual-e5-large"
    ),
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = False,
    timeout: Annotated[float, typer.Option(help="Seconds to wait for the build")] = 1800,
    poll: Annotated[float, typer.Option(help="Seconds between status polls")] = 2.0,
) -> None:
    """Build an index; with --wait block until it is ready or failed (exit 1 on failure)."""
    provider, _, model = embedding.partition(":")
    if not model:
        raise _fail("--embedding must look like provider:model")
    with _client() as client:
        kb_id = client.kb.get_by_name(kb)["id"]
        index = client.kb.create_index(
            kb_id,
            chunking={"strategy": strategy, "size": size, "overlap": overlap},
            embedding={"provider": provider, "model": model},
        )
        if index["unchanged"]:
            typer.echo(f"using existing index v{index['version']}")
            return
        typer.echo(f"building index v{index['version']} ({index['id']})")
        if not wait:
            return
        index = client.kb.wait_index(kb_id, index["id"], timeout_s=timeout, poll_s=poll)
    if index["status"] == "failed":
        typer.echo(f"index v{index['version']} failed: {index.get('error')}", err=True)
        raise typer.Exit(EXIT_FAILED)
    typer.echo(f"index v{index['version']} ready: {index['chunk_count']} chunks")
    typer.echo(json.dumps(index.get("stats") or {}, sort_keys=True))


@questions_app.command("generate")
def kb_questions_generate(
    kb: KbOpt,
    agent: Annotated[str, typer.Option(help="Agent name")],
    count: Annotated[int, typer.Option(help="How many questions (1-50)")] = 10,
    unanswerable_share: Annotated[float, typer.Option(help="Share the KB cannot answer")] = 0.2,
) -> None:
    """Generate draft ground-truth questions from the documents."""
    with _client() as client:
        result = client.kb.generate_questions(
            client.kb.get_by_name(kb)["id"],
            client.agents.get_by_name(agent).id,
            count,
            unanswerable_share,
        )
    typer.echo(f"generating; draft {result['draft_id']}")


@questions_app.command("import")
def kb_questions_import(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    kb: KbOpt,
    agent: Annotated[str, typer.Option(help="Agent name")],
) -> None:
    """Import questions from CSV (question, expected_answer, source_document, source_quote)."""
    with _client() as client:
        result = client.kb.import_questions(
            client.kb.get_by_name(kb)["id"], client.agents.get_by_name(agent).id, file
        )
    typer.echo(f"imported {result['created']} question(s)")
    for u in result["unmatched"]:
        typer.echo(f"  skipped row {u['row']}: {u['reason']}", err=True)


@rag_app.command("run")
def rag_run(
    agent: Annotated[str, typer.Option(help="Agent name")],
    kb: KbOpt,
    config: Annotated[
        Path,
        typer.Option("--config", "-f", exists=True, dir_okay=False, help="JSON RagConfig list"),
    ],
    tags: Annotated[str, typer.Option(help="Comma-separated scenario tags")] = "rag",
    persona: Annotated[list[str] | None, typer.Option(help="Persona name (repeatable)")] = None,
    noise: Annotated[list[str] | None, typer.Option(help="Noise profile (repeatable)")] = None,
    baselines: Annotated[bool, typer.Option("--baselines/--no-baselines")] = True,
    repeats: Annotated[int, typer.Option(help="Repeats per item")] = 1,
    confirm_over_budget: Annotated[bool, typer.Option(help="Run even if over budget")] = False,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = False,
    timeout: Annotated[float, typer.Option(help="Seconds to wait for the runs")] = 3600,
    poll: Annotated[float, typer.Option(help="Seconds between status polls")] = 3.0,
) -> None:
    """Create a RAG matrix (one run per config plus the baselines) and print its id."""
    try:
        configs = json.loads(config.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise _fail(f"{config}: invalid JSON: {exc}") from exc
    if not isinstance(configs, list) or not all(isinstance(c, dict) for c in configs):
        raise _fail(f"{config}: expected a JSON list of RagConfig objects")
    spec = Suite(
        scenarios=ScenarioSelector(tags=[t for t in tags.split(",") if t]),
        personas=persona or [],
        noise_profiles=noise or [],
    )
    with _client() as client:
        kb_id = client.kb.get_by_name(kb)["id"]
        resolved = resolve_suite(client, agent, spec)
        body = {
            "agent_id": str(resolved.agent.id),
            "configs": [{"kb_id": kb_id, **c} for c in configs],
            "baselines": {"no_rag": baselines, "full_context": baselines},
            "scenario_ids": list(resolved.scenario_ids),
            "persona_ids": list(resolved.persona_ids),
            "noise_profile_ids": list(resolved.noise_profile_ids),
            "repeats": repeats,
            "confirm_over_budget": confirm_over_budget,
        }
        try:
            matrix = client.rag.create_matrix(body)
        except ApiError as exc:
            if exc.code != "rag_index_missing":
                raise
            typer.echo("missing indexes (run `pareeksha kb index` first):", err=True)
            for m in exc.details.get("missing", []):
                typer.echo(f"  {m.get('label')}: {json.dumps(m, sort_keys=True)}", err=True)
            raise typer.Exit(EXIT_ERROR) from exc
        typer.echo(f"matrix {matrix['id']}")
        if wait:
            runs = client.rag.wait_matrix(matrix["id"], timeout_s=timeout, poll_s=poll)
            for r in runs:
                typer.echo(f"  run {r.id}: {r.status}", err=True)


_COLUMNS = (
    "label",
    "n",
    "hit-rate (CI)",
    "MRR",
    "faithfulness",
    "hallucination (CI)",
    "retr p50/p95 ms",
    "₹/conv",
    "savings vs full ctx",
)


def _num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _with_ci(value: float | None, ci: list[float] | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f} [{ci[0]:.2f}-{ci[1]:.2f}]" if ci else f"{value:.2f}"


def report_table(report: dict[str, Any]) -> str:
    """Fixed-width table of the report rows followed by the recommendation line."""
    body = []
    for r in report["rows"]:
        ret, gen, lat = r["retrieval"], r["generation"], r["latency_ms"]
        saving = r.get("savings_vs_full_context")
        body.append(
            (
                r["label"],
                str(r["n_calls"]),
                _with_ci(ret.get("hit_rate"), ret.get("hit_rate_ci")),
                _num(ret.get("mrr")),
                _num(gen.get("faithfulness")),
                _with_ci(gen.get("hallucination_rate"), gen.get("hallucination_ci")),
                f"{_num(lat.get('retrieval_p50'), 0)}/{_num(lat.get('retrieval_p95'), 0)}",
                _num(r.get("cost_per_conversation_inr"), 4),
                "-" if saving is None else f"{saving['pct']:.1f}%",
            )
        )
    widths = [max(len(row[i]) for row in [_COLUMNS, *body]) for i in range(len(_COLUMNS))]
    lines = [
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
        for row in [_COLUMNS, *body]
    ]
    rec = report["recommendation"]
    lines.append("")
    lines.append(f"Recommendation: {rec['label'] or 'none'} - {rec['reason']}")
    return "\n".join(lines)


@rag_app.command("report")
def rag_report(
    matrix_id: str,
    monthly: Annotated[int, typer.Option(help="Conversations per month for savings")] = 10_000,
    as_json: Annotated[bool, typer.Option("--json", help="Print the raw report")] = False,
) -> None:
    """Print the comparison table for a RAG matrix."""
    with _client() as client:
        report = client.rag.report(matrix_id, monthly)
    typer.echo(json.dumps(report, indent=2) if as_json else report_table(report))


@rag_app.command("pricing")
def rag_pricing() -> None:
    """Show entered prices (INR per 1M tokens) and models still unpriced."""
    with _client() as client:
        pricing = client.rag.pricing()
    for p in pricing["prices"]:
        out = "" if p.get("output_per_m_inr") is None else f" out {p['output_per_m_inr']}"
        typer.echo(f"{p['kind']}  {p['provider']}/{p['model']}  in {p['input_per_m_inr']}{out}")
    for u in pricing["unpriced"]:
        typer.echo(f"UNPRICED {u['kind']}  {u['provider']}/{u['model']}")


@rag_app.command("set-price")
def rag_set_price(
    kind: Annotated[str, typer.Option(help="llm, embedding or rerank")],
    provider: Annotated[str, typer.Option(help="Provider name")],
    model: Annotated[str, typer.Option(help="Model id")],
    input_per_m: Annotated[float, typer.Option(help="INR per 1M input tokens")],
    output_per_m: Annotated[float | None, typer.Option(help="INR per 1M output tokens")] = None,
) -> None:
    """Enter or update one price."""
    price = {"kind": kind, "provider": provider, "model": model, "input_per_m_inr": input_per_m}
    if output_per_m is not None:
        price["output_per_m_inr"] = output_per_m
    with _client() as client:
        client.rag.set_prices([price])
    typer.echo(f"price saved for {kind} {provider}/{model}")


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
