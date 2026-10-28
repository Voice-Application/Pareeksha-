"""Exportable HTML report of one run (``GET /runs/{id}/report``, F19).

One self-contained page (inline CSS, no scripts or external requests): header, summary figures,
the score distribution and the scenario x persona x noise-profile matrix. Every value is escaped.
"""

from __future__ import annotations

import uuid
from html import escape

from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.runs import service
from pareeksha.schemas.runs import RunItemOut, RunOut

_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1a1a1a;--muted:#667;--line:#d8dbe0;
--ok:#146c2e;--bad:#b3261e}
@media(prefers-color-scheme:dark){
:root{--bg:#14161a;--fg:#e8e8ea;--muted:#9aa;--line:#2c3038;--ok:#6fd08c;--bad:#ff8a80}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);
margin:0 auto;max-width:1000px;padding:24px 16px}
h1{font-size:1.4rem;margin:0}h2{font-size:1.1rem;margin-top:2rem}.muted{color:var(--muted)}
dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
dt{color:var(--muted);font-size:.8rem}dd{margin:0;font-size:1.3rem}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}
.ok{color:var(--ok)}.bad{color:var(--bad)}.scroll{overflow-x:auto}
"""


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _num(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.1f}{suffix}"


def _verdict(item: RunItemOut) -> str:
    if item.passed is None:
        return '<span class="muted">-</span>'
    if item.critical_failure:
        return '<span class="bad">critical failure</span>'
    return '<span class="ok">pass</span>' if item.passed else '<span class="bad">fail</span>'


def render(run: RunOut, items: list[RunItemOut]) -> str:
    s = run.summary
    figures = [
        ("Status", run.status),
        ("Calls", str(run.progress.total)),
        ("Evaluated", str(run.progress.evaluated)),
        ("Errors", str(run.progress.error)),
        ("Pass rate", _pct(s.pass_rate)),
        ("Critical failures", "n/a" if s.critical_failures is None else str(s.critical_failures)),
        ("Mean score", _num(s.score_mean)),
        ("Latency p95", "n/a" if s.latency_p95_ms is None else f"{s.latency_p95_ms} ms"),
    ]
    if s.suite_passed is not None:
        figures.append(("Suite", "passed" if s.suite_passed else "failed"))
    dl = "".join(f"<div><dt>{escape(k)}</dt><dd>{escape(v)}</dd></div>" for k, v in figures)
    failures = (
        "".join(f"<li>{escape(name)}: {count}</li>" for name, count in s.top_failure_types)
        or '<li class="muted">none recorded</li>'
    )
    buckets = "".join(
        f"<tr><td>{i * 10}-{min(i * 10 + 9, 100)}</td><td>{n}</td></tr>"
        for i, n in enumerate(s.score_distribution)
    )
    distribution = (
        f"<h2>Score distribution</h2><table><tr><th>Score</th><th>Calls</th></tr>{buckets}</table>"
        if buckets
        else ""
    )
    rows = "".join(
        "<tr>"
        f"<td>{escape(i.scenario)}</td><td>{escape(i.persona)}</td>"
        f"<td>{escape(i.noise_profile)}</td><td>{escape(i.status)}</td>"
        f"<td>{_num(i.overall_score)}</td><td>{_verdict(i)}</td></tr>"
        for i in items
    )
    title = escape(run.name or f"Run {run.id}")
    created = run.created_at.isoformat(timespec="seconds")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title} - Pareeksha report</title><style>{_CSS}</style></head><body>"
        f"<h1>{title}</h1>"
        f'<p class="muted">Run {run.id} · {escape(run.kind)} · created {escape(created)}</p>'
        f"<dl>{dl}</dl><h2>Top failure types</h2><ul>{failures}</ul>{distribution}"
        '<h2>Matrix</h2><div class="scroll"><table><tr><th>Scenario</th><th>Persona</th>'
        f"<th>Noise profile</th><th>Status</th><th>Score</th><th>Result</th></tr>{rows}"
        "</table></div></body></html>"
    )


async def build(session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID) -> str:
    run = await service.get_run(session, project_id, run_id)
    return render(run, await service.all_items(session, project_id, run_id))
