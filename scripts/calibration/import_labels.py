#!/usr/bin/env python3
"""EVAL-06 step 3: import the owner's blind labels and compute judge-vs-human agreement.

Reads labelling/EVAL-06/labels.csv (filled by the owner) and labelling/EVAL-06/.key.json (label id ->
call id), validates every row, posts each one through the real human-review API
(POST /calls/{call_id}/review), then reads GET /calibration and writes
proof/EVAL-06/calibration.json and calibration.md (kappa, Spearman, per-dimension MAE, n, and the
calls where judge and human disagree).

Two label modes, decided by the file (every row must use the same one):
- full: passed, critical and all seven 0-4 dimension scores per row;
- pass/fail only: passed and critical, all seven dimension cells empty. Reviews are posted without
  dimensions (the API accepts that and stores no human overall score), so GET /calibration reports kappa
  and n, while Spearman and per-dimension MAE are "not provided by owner".
Either way the numbers are also recomputed offline from proof/EVAL-06/judge_results.json with the
endpoint's own function (pareeksha.evaluation.calibration.compute_calibration) as a cross-check.

    python3 scripts/calibration/import_labels.py [--labels PATH] [--key PATH] [--reviewer preetham]
        [--owner-raw PATH] [--extra-md PATH]
    python3 scripts/calibration/import_labels.py --normalise-owner RAW OUT

--normalise-owner maps the owner's raw sheet to the importer's format with the owner's stated rules:
passed "passed" -> yes, "fail"/"partial" -> no; critical kept as yes/no; dimension cells dropped (they
were not 0-4 scores and are not converted); notes kept as written.

Env: PAREEKSHA_API_URL, PAREEKSHA_API_KEY (or .env), as in scripts/verify/vapi.py.
A row already imported for this reviewer (409 from the API) is reported and left as it is.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "labelling" / "EVAL-06"
PROOF = ROOT / "proof" / "EVAL-06"

# rubric-2026-10-v1 (backend/pareeksha/seed/data/rubric-2026-10-v1.yaml), in rubric order.
DIMENSIONS = (
    "task_completion",
    "policy_compliance",
    "factual_accuracy",
    "language_handling",
    "conversation_flow",
    "empathy_tone",
    "escalation",
)
COLUMNS = ("label_id", "passed", "critical", *DIMENSIONS, "notes")
YES, NO = {"yes", "y", "true", "1"}, {"no", "n", "false", "0"}
#: The owner's words for the verdict (EVAL-06 decision relayed by the orchestrator, 2026-10-30).
OWNER_PASSED = {"passed": "yes", "fail": "no", "partial": "no"}
NOT_PROVIDED = "not provided by owner"

sys.path.insert(0, str(ROOT / "backend"))
from pareeksha.evaluation.calibration import (  # noqa: E402  same code path as GET /calibration
    LabelPair,
    cohen_kappa,
    compute_calibration,
)


class LabelError(ValueError):
    """Every problem found in the label file, one per line."""


@dataclass(frozen=True)
class Label:
    label_id: str
    call_id: str
    passed: bool
    critical: bool
    scores: dict[str, int]
    notes: str = ""

    def review_body(self, reviewer: str) -> dict[str, Any]:
        """Body of POST /calls/{call_id}/review (backend/pareeksha/schemas/calls.py ReviewCreate)."""
        return {
            "reviewer": reviewer,
            "passed": self.passed,
            "critical_failure": self.critical,
            "dimensions": {k: {"score": v} for k, v in self.scores.items()},
            "notes": self.notes,
        }


def _yes_no(value: str, column: str, where: str, problems: list[str]) -> bool:
    v = value.strip().lower()
    if v in YES:
        return True
    if v in NO:
        return False
    problems.append(f"{where}: {column} must be yes or no, got {value!r}")
    return False


def parse_labels(rows: list[dict[str, str]], key: dict[str, str]) -> list[Label]:
    """Validate the CSV rows against the key; raise LabelError listing every problem.

    Every key id must be labelled exactly once; passed/critical are yes/no. A row gives either all
    seven dimension scores as integers 0-4 (the API needs all seven to compute the human overall score
    that Spearman uses) or none of them (pass/fail only), and every row must use the same mode.
    """
    problems: list[str] = []
    labels: list[Label] = []
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        lid = (row.get("label_id") or "").strip()
        where = f"line {line} ({lid or 'no label_id'})"
        if not lid:
            problems.append(f"{where}: label_id is empty")
            continue
        if lid not in key:
            problems.append(f"{where}: label_id is not in the key")
            continue
        if lid in seen:
            problems.append(f"{where}: label_id appears more than once")
            continue
        seen.add(lid)
        passed = _yes_no(row.get("passed") or "", "passed", where, problems)
        critical = _yes_no(row.get("critical") or "", "critical", where, problems)
        scores: dict[str, int] = {}
        raws = {dim: (row.get(dim) or "").strip() for dim in DIMENSIONS}
        if any(raws.values()):
            for dim, raw in raws.items():
                if raw not in {"0", "1", "2", "3", "4"}:
                    problems.append(f"{where}: {dim} must be an integer 0-4, got {raw!r}")
                    continue
                scores[dim] = int(raw)
        labels.append(
            Label(lid, key[lid], passed, critical, scores, (row.get("notes") or "").strip())
        )
    modes = {bool(lab.scores) for lab in labels}
    if len(modes) > 1:
        problems.append(
            "mixed modes: some rows have dimension scores and some have none; "
            "give all seven scores on every row, or leave them empty on every row"
        )
    missing = sorted(set(key) - seen)
    if missing:
        problems.append(f"not labelled: {', '.join(missing)}")
    if problems:
        raise LabelError("\n".join(problems))
    return labels


def label_mode(labels: list[Label]) -> str:
    return "full" if labels and all(lab.scores for lab in labels) else "pass_fail_only"


def normalise_owner_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """The owner's raw sheet -> importer rows: passed via OWNER_PASSED, critical yes/no as written,
    dimension cells emptied (not converted), notes unchanged. Raises LabelError on any other value."""
    problems: list[str] = []
    out: list[dict[str, str]] = []
    for line, row in enumerate(rows, start=2):
        lid = (row.get("label_id") or "").strip()
        passed = (row.get("passed") or "").strip().lower()
        critical = (row.get("critical") or "").strip().lower()
        if passed not in OWNER_PASSED:
            problems.append(
                f"line {line} ({lid}): passed {row.get('passed')!r} is not one of "
                f"{', '.join(sorted(OWNER_PASSED))}"
            )
        if critical not in {"yes", "no"}:
            problems.append(f"line {line} ({lid}): critical {row.get('critical')!r} is not yes/no")
        out.append(
            {
                "label_id": lid,
                "passed": OWNER_PASSED.get(passed, ""),
                "critical": critical,
                **dict.fromkeys(DIMENSIONS, ""),
                "notes": row.get("notes") or "",
            }
        )
    if problems:
        raise LabelError("\n".join(problems))
    return out


def identical_rows(rows: list[dict[str, str]]) -> list[list[str]]:
    """Groups (2 or more) of label ids whose every cell except label_id is identical."""
    groups: dict[tuple[str, ...], list[str]] = {}
    for row in rows:
        groups.setdefault(tuple(row.get(c) or "" for c in COLUMNS[1:]), []).append(row["label_id"])
    return [ids for ids in groups.values() if len(ids) > 1]


def label_pairs(labels: list[Label], judge: dict[str, dict[str, Any]]) -> list[LabelPair]:
    """The pairs GET /calibration builds (backend/pareeksha/api/routers/system.py), from the exported
    judge rows instead of the DB; the human score exists only when all seven dimensions do."""
    from pareeksha.evaluation.scoring import overall_score

    pairs = []
    for lab in labels:
        ev = judge[lab.call_id]
        pairs.append(
            LabelPair(
                judge_passed=bool(ev["passed"]),
                human_passed=lab.passed,
                judge_score=None if ev.get("overall_score") is None else float(ev["overall_score"]),
                human_score=overall_score(lab.scores)
                if set(lab.scores) == set(DIMENSIONS)
                else None,
                judge_dimensions={
                    k: int(v["score"]) for k, v in (ev.get("dimensions") or {}).items()
                },
                human_dimensions=dict(lab.scores),
            )
        )
    return pairs


def agreement(labels: list[Label], judge: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """2x2 tables (judge x human) and raw agreement for passed and for critical."""

    def table(jv: list[bool], hv: list[bool]) -> dict[str, Any]:
        n = len(jv)
        cells = {
            f"judge_{'pass' if j else 'fail'}_human_{'pass' if h else 'fail'}": sum(
                1 for a, b in zip(jv, hv) if a == j and b == h
            )
            for j in (True, False)
            for h in (True, False)
        }
        kappa = cohen_kappa(jv, hv)
        return {
            "n": n,
            **cells,
            "agreement": round(sum(a == b for a, b in zip(jv, hv)) / n, 4),
            "judge_yes": sum(jv),
            "human_yes": sum(hv),
            "kappa": None if kappa is None else round(kappa, 4),
        }

    passed = table(
        [bool(judge[lab.call_id]["passed"]) for lab in labels], [lab.passed for lab in labels]
    )
    critical = table(
        [bool(judge[lab.call_id]["critical_failure"]) for lab in labels],
        [lab.critical for lab in labels],
    )
    critical = {k.replace("_pass", "_yes").replace("_fail", "_no"): v for k, v in critical.items()}
    return {"passed": passed, "critical": critical}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = tuple(h.strip() for h in reader.fieldnames or ())
        absent = [c for c in COLUMNS if c not in header]
        if absent:
            raise LabelError(f"{path}: missing columns {', '.join(absent)}")
        return [{(k or "").strip(): v or "" for k, v in r.items()} for r in reader]


def read_key(path: Path) -> dict[str, str]:
    """``{"L01": "<call uuid>", ...}`` from the packet's .key.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping = data.get("labels", data)
    return {str(k): str(v["call_id"] if isinstance(v, dict) else v) for k, v in mapping.items()}


@dataclass
class Disagreement:
    label_id: str
    call_id: str
    judge_passed: bool | None
    human_passed: bool
    judge_critical: bool | None
    human_critical: bool
    dimension_gaps: dict[str, tuple[int, int]] = field(
        default_factory=dict
    )  # dim -> (judge, human)

    @property
    def pass_fail(self) -> bool:
        return self.judge_passed is not None and self.judge_passed != self.human_passed


def disagreements(
    labels: list[Label], evaluations: dict[str, dict[str, Any]], min_gap: int = 2
) -> list[Disagreement]:
    """Calls where judge and human differ on pass/fail or critical, or by >= ``min_gap`` on a dimension."""
    out: list[Disagreement] = []
    for lab in labels:
        ev = evaluations.get(lab.call_id) or {}
        dims = ev.get("dimensions") or {}
        gaps = {
            d: (int(dims[d]["score"]), lab.scores[d])
            for d in DIMENSIONS
            if isinstance(dims.get(d), dict)
            and d in lab.scores
            and abs(int(dims[d]["score"]) - lab.scores[d]) >= min_gap
        }
        d = Disagreement(
            lab.label_id,
            lab.call_id,
            ev.get("passed"),
            lab.passed,
            ev.get("critical_failure"),
            lab.critical,
            gaps,
        )
        if (
            d.pass_fail
            or (d.judge_critical is not None and d.judge_critical != d.human_critical)
            or gaps
        ):
            out.append(d)
    return out


class Api:
    def __init__(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts" / "verify"))
        import vapi

        self.base = vapi.api_url()
        self.token = vapi.setting("PAREEKSHA_API_KEY")

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        req = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode()
                return r.status, json.loads(text) if text else None
        except urllib.error.HTTPError as exc:
            text = exc.read().decode()
            try:
                return exc.code, json.loads(text)
            except json.JSONDecodeError:
                return exc.code, text


def _judge_reasons(ev: dict[str, Any]) -> str:
    """The judge's summary plus each dimension it scored below 4, as stored."""
    parts = [ev.get("summary") or ""]
    for dim in DIMENSIONS:
        d = (ev.get("dimensions") or {}).get(dim) or {}
        if isinstance(d, dict) and d.get("score", 4) < 4:
            parts.append(f"{dim} {d['score']}: {d.get('reason', '')}")
    return " / ".join(p for p in parts if p)


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def render_md(report: dict[str, Any], extra: str = "") -> str:
    cal, off, agr = report["calibration_api"], report["calibration_offline"], report["agreement"]
    imp, mode = report["import"], report["mode"]
    na = mode == "pass_fail_only"
    rho = NOT_PROVIDED if na else cal.get("spearman_overall")
    p, c = agr["passed"], agr["critical"]
    lines = [
        "# EVAL-06 calibration: judge vs owner labels",
        "",
        f"Labels: `{imp['labels_file']}` ({imp['labels']} rows, mode **{mode}**), imported as reviewer "
        f"`{imp['reviewer']}` through `POST /calls/{{id}}/review` ({imp['posted']} posted, "
        f"{imp['already']} already present), then read back from `GET /calibration`.",
    ]
    if na:
        lines += [
            "",
            "The owner gave no 0-4 dimension scores, so the reviews were posted without "
            "dimensions (no scores were invented) and Spearman / per-dimension MAE are "
            f"**{NOT_PROVIDED}**.",
        ]
    lines += [
        "",
        "| metric | GET /calibration | offline recompute (same function, judge_results.json) |",
        "|---|---|---|",
        f"| n | {cal.get('n')} | {off['n']} |",
        f"| Cohen's kappa (pass/fail) | {cal.get('kappa_pass_fail')} | {off['kappa_pass_fail']} |",
        f"| Spearman rho (overall score) | {rho} | {NOT_PROVIDED if na else off['spearman_overall']} |",
        f"| MAE per dimension | {NOT_PROVIDED if na else cal.get('dimension_mae')} | "
        f"{NOT_PROVIDED if na else off['dimension_mae']} |",
    ]
    kappa = cal.get("kappa_pass_fail")
    verdict = "n/a" if kappa is None else ("meets" if kappa >= 0.6 else "below")
    lines += [
        "",
        f"Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **{verdict}**.",
        "",
        "## Pass/fail (judge rows x owner columns)",
        "",
        "| | owner pass | owner fail |",
        "|---|---|---|",
        f"| judge pass | {p['judge_pass_human_pass']} | {p['judge_pass_human_fail']} |",
        f"| judge fail | {p['judge_fail_human_pass']} | {p['judge_fail_human_fail']} |",
        "",
        f"Owner passed {p['human_yes']}/{p['n']}, judge passed {p['judge_yes']}/{p['n']}; raw agreement "
        f"{p['agreement']}, kappa {p['kappa']}.",
        "",
        "## Critical (judge rows x owner columns)",
        "",
        "| | owner critical | owner not critical |",
        "|---|---|---|",
        f"| judge critical | {c['judge_yes_human_yes']} | {c['judge_yes_human_no']} |",
        f"| judge not critical | {c['judge_no_human_yes']} | {c['judge_no_human_no']} |",
        "",
        f"Owner critical {c['human_yes']}/{c['n']}, judge critical {c['judge_yes']}/{c['n']}; raw "
        f"agreement {c['agreement']}, kappa {c['kappa']}.",
    ]
    if report["identical_rows"]:
        lines += ["", "## Identical rows", ""]
        for ids in report["identical_rows"]:
            lines.append(
                f"- {', '.join(ids)} ({len(ids)} rows) carry identical values in every column "
                "of the owner's sheet, including the note."
            )
    lines += [
        "",
        f"## Disagreements ({len(report['disagreements'])})",
        "",
        "Pass/fail or critical differ"
        + ("" if na else ", or a dimension differs by 2 or more")
        + ". "
        "Judge reasons are its stored summary plus every dimension it scored below 4.",
        "",
        "| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |",
        "|---|---|---|---|---|",
    ]
    for d in report["disagreements"]:
        lines.append(
            f"| {d['label_id']} | {d['judge_passed']}/{d['judge_critical']}/{d['judge_score']} | "
            f"{d['human_passed']}/{d['human_critical']} | {_cell(d['judge_reasons'])} | "
            f"{_cell(d['owner_note']) or '-'} |"
        )
    text = "\n".join(lines) + "\n"
    return text + ("\n" + extra.strip() + "\n" if extra.strip() else "")


def build_report(
    labels: list[Label],
    judge: dict[str, dict[str, Any]],
    cal: dict[str, Any],
    imported: dict[str, Any],
    owner_rows: list[dict[str, str]] | None,
) -> dict[str, Any]:
    off = compute_calibration(label_pairs(labels, judge))
    mode = label_mode(labels)
    dis = []
    for d in disagreements(labels, judge):
        ev = judge[d.call_id]
        lab = next(lab for lab in labels if lab.label_id == d.label_id)
        dis.append(
            {
                **d.__dict__,
                "dimension_gaps": {
                    k: {"judge": j, "human": h} for k, (j, h) in d.dimension_gaps.items()
                },
                "judge_score": ev.get("overall_score"),
                "judge_failure_types": ev.get("failure_types"),
                "judge_reasons": _judge_reasons(ev),
                "owner_note": lab.notes,
            }
        )
    return {
        "mode": mode,
        "calibration_api": cal,
        "calibration_offline": {
            "n": off.n,
            "kappa_pass_fail": off.kappa_pass_fail,
            "spearman_overall": off.spearman_overall,
            "dimension_mae": off.dimension_mae,
        },
        "not_provided_by_owner": ["spearman_overall", "dimension_mae"]
        if mode == "pass_fail_only"
        else [],
        "agreement": agreement(labels, judge),
        "identical_rows": identical_rows(owner_rows) if owner_rows else [],
        "import": imported,
        "disagreements": dis,
    }


def read_judge(path: Path) -> dict[str, dict[str, Any]]:
    return {r["call_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--labels", type=Path, default=PACKET / "labels.csv")
    ap.add_argument("--key", type=Path, default=PACKET / ".key.json")
    ap.add_argument("--reviewer", default="preetham")
    ap.add_argument("--out", type=Path, default=PROOF)
    ap.add_argument("--judge", type=Path, default=PROOF / "judge_results.json")
    ap.add_argument(
        "--owner-raw", type=Path, help="owner's raw sheet, for the identical-rows check"
    )
    ap.add_argument("--extra-md", type=Path, help="markdown appended to calibration.md")
    ap.add_argument("--normalise-owner", nargs=2, type=Path, metavar=("RAW", "OUT"))
    args = ap.parse_args(argv)
    if args.normalise_owner:
        raw, out = args.normalise_owner
        try:
            rows = normalise_owner_rows(read_csv(raw))
        except LabelError as exc:
            print(f"{raw} cannot be normalised:\n{exc}", file=sys.stderr)
            return 2
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} rows -> {out}")
        return 0
    try:
        labels = parse_labels(read_csv(args.labels), read_key(args.key))
    except LabelError as exc:
        print(f"labels.csv is not valid, nothing was imported:\n{exc}", file=sys.stderr)
        return 2
    judge = read_judge(args.judge)
    absent = [lab.label_id for lab in labels if lab.call_id not in judge]
    if absent:
        print(f"no judge result in {args.judge} for {', '.join(absent)}", file=sys.stderr)
        return 2
    api = Api()
    posted, already = 0, 0
    for lab in labels:
        status, body = api.call(
            "POST", f"/calls/{lab.call_id}/review", lab.review_body(args.reviewer)
        )
        if status == 201:
            posted += 1
        elif status == 409 and "already reviewed" in json.dumps(body):
            already += 1
        else:
            print(
                f"{lab.label_id} ({lab.call_id}): POST review -> {status} {body}", file=sys.stderr
            )
            return 1
        status, call = api.call("GET", f"/calls/{lab.call_id}")
        live = (call or {}).get("evaluation") or {}
        if status != 200 or live.get("id") != judge[lab.call_id]["evaluation_id"]:
            print(
                f"{lab.label_id}: the call's live evaluation is not the exported one ({status})",
                file=sys.stderr,
            )
            return 1
    status, cal = api.call("GET", "/calibration")
    if status != 200:
        print(f"GET /calibration -> {status} {cal}", file=sys.stderr)
        return 1
    imported = {
        "reviewer": args.reviewer,
        "posted": posted,
        "already": already,
        "labels": len(labels),
        "labels_file": str(
            args.labels.relative_to(ROOT) if args.labels.is_relative_to(ROOT) else args.labels
        ),
    }
    owner_rows = read_csv(args.owner_raw) if args.owner_raw else None
    report = build_report(labels, judge, cal, imported, owner_rows)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "calibration.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    )
    extra = args.extra_md.read_text(encoding="utf-8") if args.extra_md else ""
    (args.out / "calibration.md").write_text(render_md(report, extra))
    print(
        json.dumps(
            {k: report[k] for k in ("mode", "calibration_api", "calibration_offline")}
            | {"agreement": report["agreement"], "disagreements": len(report["disagreements"])},
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
