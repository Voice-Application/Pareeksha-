"""Run verdicts and the Markdown summary written to ``$GITHUB_STEP_SUMMARY``."""

from __future__ import annotations

from dataclasses import dataclass, field

from pareeksha_sdk.models import Run, RunItem


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    #: The run itself broke (failed / partial): there is no verdict on the agent under test.
    errored: bool = False


def judge_run(run: Run, *, fail_under: float | None = None, require_suite: bool = False) -> Verdict:
    """Decide pass/fail for a finished run.

    ``fail_under`` is a pass-rate percentage. ``require_suite`` is for regression runs, where the
    server's ``suite_passed`` is the verdict.
    """
    reasons: list[str] = []
    errored = False
    if run.status == "failed":
        reasons.append("run had infrastructure errors, no verdict")
        errored = True
    elif run.status == "cancelled":
        reasons.append(f"run {run.status}")
    elif run.status == "partial":
        reasons.append("run finished partially (some items errored)")
        errored = True
    elif not run.is_final:
        reasons.append(f"run not finished ({run.status})")
    if require_suite and run.summary.suite_passed is not True:
        reasons.append("regression suite failed")
    if fail_under is not None:
        rate = run.summary.pass_rate
        if rate is None:
            reasons.append("no pass rate available")
        elif rate * 100 < fail_under:
            reasons.append(f"pass rate {rate * 100:.1f}% is below {fail_under:g}%")
    return Verdict(ok=not reasons, reasons=reasons, errored=errored)


def render_summary(
    title: str,
    run: Run,
    verdict: Verdict,
    items: list[RunItem] | None = None,
    *,
    fail_under: float | None = None,
    run_url: str | None = None,
) -> str:
    s = run.summary
    mark = "PASS" if verdict.ok else "ERROR" if verdict.errored else "FAIL"
    lines = [f"## Pareeksha: {title} - {mark}", ""]
    rate = "n/a" if s.pass_rate is None else f"{s.pass_rate * 100:.1f}%"
    score = "n/a" if s.score_mean is None else f"{s.score_mean:.1f}"
    crit = "n/a" if s.critical_failures is None else s.critical_failures
    review = "n/a" if s.needs_review is None else s.needs_review
    lines += [
        "| Metric | Value |",
        "|---|---|",
        f"| Status | {run.status} |",
        f"| Pass rate | {rate}"
        + (f" (threshold {fail_under:g}%)" if fail_under is not None else "")
        + " |",
        f"| Mean score | {score} |",
        f"| Critical failures | {crit} |",
        f"| Needs human review | {review} |",
        f"| Items | {run.progress.evaluated}/{run.progress.total} evaluated, "
        f"{run.progress.error} error |",
    ]
    if s.suite_passed is not None:
        lines.append(f"| Regression suite | {'passed' if s.suite_passed else 'FAILED'} |")
    if verdict.reasons:
        lines += ["", "**Why it failed**", *[f"- {r}" for r in verdict.reasons]]
    if s.top_failure_types:
        lines += ["", "**Top failure types**", *[f"- {t}: {n}" for t, n in s.top_failure_types]]
    failing = [i for i in items or [] if i.passed is False or i.critical_failure]
    if failing:
        lines += [
            "",
            "**Failing cells**",
            "",
            "| Scenario | Persona | Noise | Score | Critical |",
            "|---|---|---|---|---|",
        ]
        for i in failing:
            score_cell = "n/a" if i.overall_score is None else f"{i.overall_score:.0f}"
            lines.append(
                f"| {i.scenario} | {i.persona} | {i.noise_profile} | {score_cell} | "
                f"{'yes' if i.critical_failure else 'no'} |"
            )
    if run_url:
        lines += ["", f"[Open run]({run_url})"]
    return "\n".join(lines) + "\n"
