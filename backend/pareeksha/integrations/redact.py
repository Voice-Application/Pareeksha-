"""Best-effort secret masking for text and JSON that is stored or returned to API callers.

Used for dead-letter errors and envelopes and for delivery-log excerpts, where an exception message
can echo a validation input, a connector secret or a URL with a token. It masks values by key
name (``secret``, ``token``, ``api_key``, ``authorization``, ``password``, ``signing``), bearer /
basic credentials, ``pk_live_`` style keys, URL userinfo and query-string credentials, and the
``input_value`` that pydantic validation errors print. It is a safety net, not a guarantee:
unlabelled secrets in free text cannot be recognised.
"""

from __future__ import annotations

import re
from typing import Any

MASK = "[REDACTED]"

_SENSITIVE = r"[\w-]*(?:secret|token|api[_-]?key|authorization|password|passwd|signing)[\w-]*"
_VALUE = r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s,;&)}\]]+"

_SENSITIVE_KEY = re.compile(_SENSITIVE, re.IGNORECASE)

_TEXT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(Bearer|Basic)\s+\S+", re.IGNORECASE), rf"\1 {MASK}"),
    (re.compile(r"\b(?:pk|sk|rk)_(?:live|test)_[A-Za-z0-9_]+"), MASK),
    (re.compile(r"(://)[^/\s:@]*:[^/\s@]*@"), rf"\1{MASK}@"),
    # query string: ?token=..., &api_key=..., &X-Amz-Signature=...
    (
        re.compile(
            r"([?&;][\w.-]*(?:secret|token|key|password|passwd|signature|sig|auth|credential)"
            r"[\w.-]*=)[^&\s'\"#]+",
            re.IGNORECASE,
        ),
        rf"\1{MASK}",
    ),
    # key=value, key: value, 'key': 'value', "key": "value"
    (
        re.compile(rf"([\"']?{_SENSITIVE}[\"']?\s*[:=]\s*)(?:{_VALUE})", re.IGNORECASE),
        rf"\1{MASK}",
    ),
    # pydantic: "[type=..., input_value=<repr>, input_type=dict]" and errors() dicts
    (re.compile(r"(?m)(input_value=).*?(?=, input_type=|\]\s*$|$)"), rf"\1{MASK}"),
    (re.compile(rf"([\"']input[\"']\s*:\s*)(?:{_VALUE})"), rf"\1{MASK}"),
)


def redact_text(text: str) -> str:
    """``text`` with credentials masked."""
    for pattern, replacement in _TEXT_RULES:
        text = pattern.sub(replacement, text)
    return text


def redact_json(value: Any) -> Any:
    """A copy of a JSON-like value with sensitive keys' values masked and strings scrubbed.

    Numbers, booleans and null under a sensitive key are kept: ``tokens_used: 12`` is a count."""
    if isinstance(value, dict):
        return {
            k: (
                MASK
                if isinstance(k, str)
                and _SENSITIVE_KEY.fullmatch(k)
                and isinstance(v, str | dict | list)
                and v
                else redact_json(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_json(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
