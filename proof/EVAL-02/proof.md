# EVAL-02 proof: metrics, checks, Indian numeral parser, PII masking

Built (all under `backend/pareeksha/evaluation/`, no network, no DB):
- `numbers.py`: Indian numeral parser (digits incl. Indian grouping and Devanagari/Kannada digits, `4k`, `2.5 lakh`; English, Hindi, Kannada words; core romanised Hindi/Kannada). API: `extract_numbers`, `extract_amounts`, `parse_number`, `normalize_numbers`.
- `pii.py`: `mask_pii` / `mask_pii_detailed` (mobile, Aadhaar-like, PAN-like, email, Luhn card, spoken digit strings).
- `metrics.py`: docs/08 section 6 metrics (latency p50/p95, greeting latency, barge-in, silence gaps, talk ratio, repeats, caller WER). `compute_metrics`.
- `checks.py`: `deterministic_checks` rows for all 6 check_types (disclosure_present, forbidden_absent, language_match, tool_calls_expected, no_loop, amount_confirmed) and `run_checks`.
- `types.py`: Turn / CheckResult / Disclosure / ForbiddenPhrase / ToolCall dataclasses (independent of TL-01 contracts).
- Tests: `backend/tests/evaluation/test_{numbers,pii,metrics,checks}.py`.

Reproduce (Python 3.13; needs pytest, rapidfuzz, ruff):

    pip install pytest rapidfuzz ruff
    cd backend && python3 -m pytest tests/evaluation -v && ruff check . && ruff format --check .

Expected: `108 passed`, `All checks passed!`, formatter reports files unchanged. Real output: `pytest.log`, `ruff.log` in this folder.

Spec cases covered: `4000` == `4,000` == `four thousand` == `चार हज़ार` == `ನಾಲ್ಕು ಸಾವಿರ` == `naalku saavira`; lakh/crore; "Caller said 4000; agent confirmed 40000" gives amount_confirmed failed (API spec example); PII strings for phone/Aadhaar/PAN (FR-EV-9).

Heuristics and limits are documented in module docstrings (numbers.py LIMITS; metrics.py conventions; checks.py matching rules).
Commit SHA: see the final report / `git log task/EVAL-02`.
