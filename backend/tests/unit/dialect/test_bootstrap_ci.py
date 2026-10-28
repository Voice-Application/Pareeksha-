"""T-FR-DI-4: speaker-grouped bootstrap CIs, aggregation and the HTML report."""

from __future__ import annotations

import html.parser
from datetime import UTC, datetime

import numpy as np
import pytest

from pareeksha.dialect.report import ResultRow, aggregate, render_html
from pareeksha.dialect.stats import speaker_bootstrap_ci


def test_interval_brackets_the_pooled_estimate_and_is_deterministic() -> None:
    items = [(f"s{i % 12}", float((i * 7) % 13), 10.0 + i % 5) for i in range(60)]
    lo, hi = speaker_bootstrap_ci(items, seed=1)
    point = sum(n for _, n, _ in items) / sum(d for _, _, d in items)
    assert lo <= point <= hi
    assert (lo, hi) == speaker_bootstrap_ci(items, seed=1)
    assert (lo, hi) != speaker_bootstrap_ci(items, seed=2)


def test_resampling_unit_is_the_speaker_not_the_clip() -> None:
    """Many clips from few speakers must give a wider interval than the same clips treated as
    independent speakers: that is the point of grouping."""
    rng = np.random.default_rng(0)
    speaker_error = {f"s{i}": rng.uniform(0.0, 0.8) for i in range(5)}
    grouped = [(s, float(round(e * 20)), 20.0) for s, e in speaker_error.items() for _ in range(40)]
    ungrouped = [(f"c{i}", n, d) for i, (_, n, d) in enumerate(grouped)]
    g_lo, g_hi = speaker_bootstrap_ci(grouped, seed=3)
    u_lo, u_hi = speaker_bootstrap_ci(ungrouped, seed=3)
    assert (g_hi - g_lo) > 3 * (u_hi - u_lo)


def test_single_speaker_collapses_to_the_point_estimate() -> None:
    assert speaker_bootstrap_ci([("only", 3.0, 10.0), ("only", 1.0, 10.0)]) == (0.2, 0.2)


def test_empty_input() -> None:
    assert speaker_bootstrap_ci([]) == (0.0, 0.0)


def test_interval_narrows_with_more_speakers() -> None:
    def width(n_speakers: int) -> float:
        rng = np.random.default_rng(7)
        items = [(f"s{i}", float(rng.binomial(20, 0.3)), 20.0) for i in range(n_speakers)]
        lo, hi = speaker_bootstrap_ci(items, seed=5)
        return hi - lo

    assert width(8) > width(200)


def row(dialect: str, cond: str, speaker: str, ref: str, hyp: str, **kw: object) -> ResultRow:
    return ResultRow(
        dialect=dialect,
        condition=cond,
        engine="gnani-prisma",
        speaker_id=speaker,
        ref_norm=ref,
        hyp_norm=hyp,
        entity_total=int(kw.get("entity_total", 0)),  # type: ignore[call-overload]
        entity_correct=int(kw.get("entity_correct", 0)),  # type: ignore[call-overload]
        intent_preserved=kw.get("intent"),  # type: ignore[arg-type]
    )


def sample_rows() -> list[ResultRow]:
    out: list[ResultRow] = []
    for dialect, err in (("kn-north", 1), ("hi-delhi", 0)):
        for cond in ("clean_16k", "pstn_8k_alaw"):
            for i in range(8):
                hyp = "a b c d" if (i < err * 4 or cond == "clean_16k") else "a b c x"
                out.append(row(dialect, cond, f"{dialect}-s{i % 4}", "a b c d", hyp))
    return out


def test_aggregation_pools_per_dialect_condition_engine_cell() -> None:
    agg = aggregate(sample_rows(), resamples=200).aggregates
    assert set(agg) == {"kn-north", "hi-delhi"}
    clean = agg["kn-north"]["clean_16k"]["gnani-prisma"]
    assert clean["n"] == 8 and clean["speakers"] == 4 and clean["wer"] == 0.0
    noisy = agg["hi-delhi"]["pstn_8k_alaw"]["gnani-prisma"]
    assert noisy["wer"] == pytest.approx(0.25)  # one word of four wrong in every clip
    lo, hi = noisy["wer_ci"]
    assert lo <= noisy["wer"] <= hi
    assert noisy["entity_acc"] is None  # no entities in the reference


def test_entity_accuracy_and_intent_rate_are_pooled() -> None:
    rows = [
        row("d", "c", "s1", "x", "x", entity_total=2, entity_correct=2, intent=True),
        row("d", "c", "s2", "x", "y", entity_total=2, entity_correct=0, intent=False),
        row("d", "c", "s3", "x", "x"),
    ]
    cell = aggregate(rows, resamples=50).aggregates["d"]["c"]["gnani-prisma"]
    assert cell["entity_acc"] == 0.5
    assert cell["intent_preserved_rate"] == 0.5


class _Collect(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def test_html_report_renders_a_cell_with_ci_and_n_for_every_dialect_and_condition() -> None:
    result = aggregate(sample_rows(), resamples=100)
    page = render_html(
        dataset_name="Kannada <dialects> v1",
        created_at=datetime(2026, 10, 27, tzinfo=UTC),
        conditions=["clean_16k", "pstn_8k_alaw"],
        engines=["gnani-prisma"],
        aggregates=result.aggregates,
        top_errors_=[
            {"ref": "ಕಂತು", "hyp": "ಕಾಂತು", "count": 9},
            {"ref": "d", "hyp": "", "count": 2},
        ],
        bias=["ಕಂತು", "NEFT"],
    )
    parsed = _Collect()
    parsed.feed(page)
    text = " ".join(parsed.text)
    assert page.startswith("<!doctype html>")
    assert "Kannada &lt;dialects&gt; v1" in page  # escaped, not injected
    assert "<dialects>" not in page
    assert text.count("95% CI") >= 8  # WER + CER cells: 2 dialects x 2 conditions x 2 metrics
    assert "n=8, 4 speaker(s)" in text
    assert "(missed)" in text and "ಕಾಂತು" in text and "NEFT" in text
    assert "prefers-color-scheme" in page  # dark mode
    assert "<script" not in page  # standalone, nothing to load
