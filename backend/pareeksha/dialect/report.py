"""Aggregation of ``asr_results`` into a report, bias suggestions and the standalone HTML page.

Aggregates are ``{dialect: {condition: {engine: {n, speakers, wer, wer_ci, cer, cer_ci,
entity_acc, intent_preserved_rate}}}}`` where ``condition`` is the noise profile name. WER and CER
are pooled (total errors / total reference units), and their 95 % intervals come from a
speaker-grouped bootstrap (``stats.speaker_bootstrap_ci``).
"""

from __future__ import annotations

import html
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pareeksha.dialect.metrics import char_edits, entity_hits, word_edits
from pareeksha.dialect.stats import DEFAULT_RESAMPLES, DEFAULT_SEED, speaker_bootstrap_ci

TOP_ERRORS = 20
BIAS_LIMIT = 20
#: A reference word must be misrecognised at least this often to be suggested for ``bias_list``.
MIN_WORD_MISSES = 3
MIN_TERM_MISSES = 2


@dataclass(frozen=True)
class ResultRow:
    """One ``asr_results`` row joined with its sample and noise profile."""

    dialect: str
    condition: str
    engine: str
    speaker_id: str
    ref_norm: str
    hyp_norm: str
    entity_total: int
    entity_correct: int
    intent_preserved: bool | None
    substitutions: Sequence[tuple[str, str]] = ()
    domain_terms: Sequence[str] = ()


@dataclass
class Aggregation:
    aggregates: dict[str, dict[str, dict[str, dict[str, Any]]]] = field(default_factory=dict)
    top_errors: list[dict[str, Any]] = field(default_factory=list)
    bias_suggestions: list[str] = field(default_factory=list)


def _group(rows: Sequence[ResultRow]) -> dict[tuple[str, str, str], list[ResultRow]]:
    groups: dict[tuple[str, str, str], list[ResultRow]] = defaultdict(list)
    for r in rows:
        groups[(r.dialect, r.condition, r.engine)].append(r)
    return groups


def aggregate_cell(
    rows: Sequence[ResultRow], *, resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED
) -> dict[str, Any]:
    """Metrics of one dialect x condition x engine cell."""
    w: list[tuple[str, float, float]] = []
    c: list[tuple[str, float, float]] = []
    for r in rows:
        we, wn = word_edits(r.ref_norm, r.hyp_norm)
        ce, cn = char_edits(r.ref_norm, r.hyp_norm)
        w.append((r.speaker_id, float(we), float(wn)))
        c.append((r.speaker_id, float(ce), float(cn)))

    def pooled(items: list[tuple[str, float, float]]) -> float:
        den = sum(d for _, _, d in items)
        return sum(n for _, n, _ in items) / den if den else 0.0

    ent_total = sum(r.entity_total for r in rows)
    intents = [r.intent_preserved for r in rows if r.intent_preserved is not None]
    return {
        "n": len(rows),
        "speakers": len({r.speaker_id for r in rows}),
        "wer": round(pooled(w), 4),
        "wer_ci": [round(x, 4) for x in speaker_bootstrap_ci(w, resamples=resamples, seed=seed)],
        "cer": round(pooled(c), 4),
        "cer_ci": [round(x, 4) for x in speaker_bootstrap_ci(c, resamples=resamples, seed=seed)],
        "entity_acc": round(sum(r.entity_correct for r in rows) / ent_total, 4)
        if ent_total
        else None,
        "intent_preserved_rate": round(sum(intents) / len(intents), 4) if intents else None,
    }


def top_errors(rows: Sequence[ResultRow], limit: int = TOP_ERRORS) -> list[dict[str, Any]]:
    """Most frequent misrecognised reference words (substitutions and deletions)."""
    counts: Counter[tuple[str, str]] = Counter()
    for r in rows:
        counts.update((ref, hyp) for ref, hyp in r.substitutions if ref)
    return [
        {"ref": ref, "hyp": hyp, "count": n}
        for (ref, hyp), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    ]


def bias_suggestions(rows: Sequence[ResultRow], limit: int = BIAS_LIMIT) -> list[str]:
    """Terms worth putting on the agent's ``bias_list`` (FR-DI-6): domain terms the engine missed
    most often, then reference words it kept getting wrong."""
    missed_terms: Counter[str] = Counter()
    for r in rows:
        _, missed = entity_hits(r.ref_norm, r.hyp_norm, r.domain_terms)
        missed_terms.update(m for m in missed if not m.replace(".", "", 1).isdigit())
    word_misses: Counter[str] = Counter()
    for r in rows:
        word_misses.update(ref for ref, _ in r.substitutions if ref)
    out = [t for t, n in missed_terms.most_common() if n >= MIN_TERM_MISSES]
    out += [w for w, n in word_misses.most_common() if n >= MIN_WORD_MISSES and w not in out]
    return out[:limit]


def aggregate(
    rows: Sequence[ResultRow], *, resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED
) -> Aggregation:
    result = Aggregation(top_errors=top_errors(rows), bias_suggestions=bias_suggestions(rows))
    for (dialect, condition, engine), cell_rows in sorted(_group(rows).items()):
        result.aggregates.setdefault(dialect, {}).setdefault(condition, {})[engine] = (
            aggregate_cell(cell_rows, resamples=resamples, seed=seed)
        )
    return result


# ---------------------------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------------------------

_CSS = """
:root{--bg:#fafaf7;--fg:#1c1b19;--muted:#6b675f;--line:#dedbd2;--card:#fff}
@media (prefers-color-scheme:dark){
:root{--bg:#161614;--fg:#ecebe6;--muted:#9a968c;--line:#34332f;--card:#1e1e1b}}
*{box-sizing:border-box}body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,sans-serif}main{max-width:1040px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}
h3{font-size:15px;margin:20px 0 6px}
.muted{color:var(--muted)}.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line)}
th,td{padding:8px 10px;border:1px solid var(--line);text-align:left;vertical-align:top}
td.cell{text-align:center;min-width:130px}td.cell small{display:block;color:inherit;opacity:.75}
.note{border-left:3px solid var(--line);padding:2px 12px;margin:8px 0}
code{font-family:ui-monospace,monospace}
"""

_METRICS: tuple[tuple[str, str, str | None], ...] = (
    ("wer", "Word error rate", "wer_ci"),
    ("cer", "Character error rate", "cer_ci"),
    ("entity_acc", "Entity accuracy (numbers, amounts, names)", None),
    ("intent_preserved_rate", "Intent preserved (LLM judge)", None),
)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _cell_style(metric: str, value: float | None) -> str:
    """Heat colour: error rates run green to red; accuracies run red to green."""
    if value is None:
        return ""
    bad = value if metric in ("wer", "cer") else 1.0 - value
    bad = max(0.0, min(1.0, bad))
    hue = 130 - 130 * min(1.0, bad / 0.6)
    return f"background:hsl({hue:.0f} 55% 78%);color:#1c1b19"


def _cell(metric: str, ci_key: str | None, agg: dict[str, Any] | None) -> str:
    if agg is None or agg.get(metric) is None:
        return '<td class="cell muted">n/a</td>'
    value = float(agg[metric])
    extra = ""
    if ci_key and agg.get(ci_key):
        lo, hi = agg[ci_key]
        extra = f"<small>95% CI {_pct(lo)} to {_pct(hi)}</small>"
    n = f"n={agg['n']}, {agg.get('speakers', '?')} speaker(s)"
    return (
        f'<td class="cell" style="{_cell_style(metric, value)}"><b>{_pct(value)}</b>{extra}'
        f"<small>{n}</small></td>"
    )


def render_html(
    *,
    dataset_name: str,
    created_at: datetime | None,
    conditions: Sequence[str],
    engines: Sequence[str],
    aggregates: dict[str, dict[str, dict[str, dict[str, Any]]]],
    top_errors_: Sequence[dict[str, Any]],
    bias: Sequence[str],
) -> str:
    """Standalone report: a dialect x condition heatmap per metric and engine, the most
    misrecognised words and the suggested ``bias_list`` terms."""
    e = html.escape
    when = created_at.strftime("%Y-%m-%d %H:%M UTC") if created_at else ""
    dialects = sorted(aggregates)
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>Dialect report - {e(dataset_name)}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        f"<h1>Dialect gap report: {e(dataset_name)}</h1>",
        f'<p class="muted">{e(when)} &middot; engines: {e(", ".join(engines))} &middot; '
        f"conditions: {e(', '.join(conditions))}</p>",
        '<p class="note">Rates are pooled over clips. Intervals are 95% bootstrap intervals that '
        "resample whole speakers, so they are wide when a group has few speakers. Texts are "
        "normalised before scoring (Unicode, digits, spoken numbers, punctuation, loanword "
        "spellings).</p>",
    ]
    for engine in engines:
        parts.append(f"<h2>Engine: {e(engine)}</h2>")
        for metric, title, ci_key in _METRICS:
            parts.append(
                f"<h3>{e(title)}</h3><div class='scroll'><table><thead><tr><th>Dialect</th>"
            )
            parts += [f"<th>{e(c)}</th>" for c in conditions]
            parts.append("</tr></thead><tbody>")
            for dialect in dialects:
                parts.append(f"<tr><th scope='row'>{e(dialect)}</th>")
                for cond in conditions:
                    parts.append(
                        _cell(metric, ci_key, aggregates[dialect].get(cond, {}).get(engine))
                    )
                parts.append("</tr>")
            parts.append("</tbody></table></div>")
    parts.append("<h2>Most misrecognised words</h2>")
    if top_errors_:
        parts.append(
            "<table><thead><tr><th>Reference</th><th>Heard as</th><th>Count</th></tr>"
            "</thead><tbody>"
        )
        for t in top_errors_:
            heard = e(str(t["hyp"])) if t["hyp"] else "<span class='muted'>(missed)</span>"
            parts.append(
                f"<tr><td>{e(str(t['ref']))}</td><td>{heard}</td><td>{int(t['count'])}</td></tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append("<p class='muted'>No recurring errors.</p>")
    parts.append("<h2>Suggested bias_list terms</h2>")
    if bias:
        parts.append("<p>" + ", ".join(f"<code>{e(b)}</code>" for b in bias) + "</p>")
    else:
        parts.append("<p class='muted'>No term was missed often enough to suggest.</p>")
    parts.append("</main></body></html>")
    return "".join(parts)
