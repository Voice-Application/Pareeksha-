"""Versioned Jinja2 prompt templates (``pareeksha/llm/prompts/*.j2``).

``prompt_hash`` is the sha256 of the *unrendered* template file (TRD section 4), so a stored
evaluation can be tied to the exact prompt text that produced it.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _tojson(value: Any) -> str:
    """JSON for prompts: keep Kannada/Hindi readable instead of ``\\uXXXX`` escapes."""
    return json.dumps(value, ensure_ascii=False, default=str)


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=False,
        keep_trailing_newline=True,
    )
    env.filters["tojson"] = _tojson
    return env


def render_prompt(name: str, **context: Any) -> str:
    """Render ``prompts/<name>.j2``; a missing variable raises (no silent blanks)."""
    return _env().get_template(f"{name}.j2").render(**context)


def prompt_hash(name: str) -> str:
    """sha256 hex digest of the unrendered template."""
    return hashlib.sha256((PROMPTS_DIR / f"{name}.j2").read_bytes()).hexdigest()
