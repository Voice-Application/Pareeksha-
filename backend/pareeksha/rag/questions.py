"""Ground-truth RAG questions: quote location, passage sampling, LLM generation, CSV parsing."""

from __future__ import annotations

import csv
import io
import random
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel

from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.client import LLMClient
from pareeksha.llm.prompts import prompt_hash, render_prompt
from pareeksha.schemas.rag import RagExpectation
from pareeksha.schemas.scenarios import ScenarioCreate

PROMPT = "rag_questions_v1"
PASSAGE_CHARS = 1200
MAX_CSV_ROWS = 1000
CSV_COLUMNS = ("question", "expected_answer", "source_document", "source_quote")
UNANSWERABLE_CRITERIA = "The agent says it does not have that information and does not invent one."


def _normalise(text: str) -> tuple[str, list[int]]:
    """Whitespace collapsed to one space, case folded; ``map[i]`` = original index of char ``i``."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                index.append(i)
        else:
            for folded in ch.casefold():
                out.append(folded)
                index.append(i)
    return "".join(out), index


def locate_quote(doc_text: str, quote: str) -> tuple[int, int] | None:
    """``(start, end)`` of ``quote`` in ``doc_text``: exact first, then whitespace/case-insensitive
    with offsets mapped back to the original text. ``None`` if it is not there."""
    if not quote.strip():
        return None
    at = doc_text.find(quote)
    if at >= 0:
        return at, at + len(quote)
    hay, index = _normalise(doc_text)
    needle = _normalise(quote)[0].strip()
    at = hay.find(needle) if needle else -1
    if at < 0:
        return None
    return index[at], index[at + len(needle) - 1] + 1


@dataclass(frozen=True)
class Passage:
    document_id: UUID
    filename: str
    start: int
    end: int
    text: str


def _windows(text: str) -> list[tuple[int, int]]:
    """Non-overlapping ~PASSAGE_CHARS windows whose edges fall on whitespace."""
    spans: list[tuple[int, int]] = []
    pos, n = 0, len(text)
    while pos < n:
        end = min(pos + PASSAGE_CHARS, n)
        if end < n:
            cut = text.rfind(" ", pos, end)
            cut = max(cut, text.rfind("\n", pos, end))
            if cut > pos:
                end = cut
        chunk = text[pos:end]
        start = pos + len(chunk) - len(chunk.lstrip())
        if chunk.strip():
            spans.append((start, pos + len(chunk.rstrip())))
        pos = max(end, pos + 1)
    return spans


def sample_passages(
    docs: Sequence[tuple[UUID, str, str]], count: int, rng: random.Random
) -> list[Passage]:
    """Up to ``count`` passages, spread round-robin across documents, deterministic for ``rng``."""
    pools: list[list[Passage]] = []
    for doc_id, filename, text in docs:
        pool = [Passage(doc_id, filename, a, b, text[a:b]) for a, b in _windows(text)]
        rng.shuffle(pool)
        if pool:
            pools.append(pool)
    rng.shuffle(pools)
    picked: list[Passage] = []
    while pools and len(picked) < count:
        for pool in list(pools):
            picked.append(pool.pop())
            if not pool:
                pools.remove(pool)
            if len(picked) == count:
                break
    return picked


class RagQuestion(BaseModel):
    passage: int | None = None  # 1-based; null for unanswerable questions
    question: str
    reference_answer: str = ""
    quote: str = ""
    answerable: bool = True


class RagQuestionBatch(BaseModel):
    questions: list[RagQuestion]


def split_counts(count: int, unanswerable_share: float) -> tuple[int, int]:
    """(answerable, unanswerable) for a requested ``count``."""
    unanswerable = min(count, round(count * unanswerable_share))
    return count - unanswerable, unanswerable


async def generate_questions(
    client: LLMClient,
    kb_name: str,
    kb_description: str,
    passages: Sequence[Passage],
    n_answerable: int,
    n_unanswerable: int,
) -> RagQuestionBatch:
    want = n_answerable + n_unanswerable
    prompt = render_prompt(
        PROMPT,
        kb={"name": kb_name, "description": kb_description},
        passages=[
            {"n": i, "filename": p.filename, "text": p.text} for i, p in enumerate(passages, 1)
        ],
        n_answerable=n_answerable,
        n_unanswerable=n_unanswerable,
    )

    def check(b: RagQuestionBatch) -> str | None:
        if len(b.questions) != want:
            return f"expected exactly {want} questions, got {len(b.questions)}"
        got = sum(q.answerable for q in b.questions)
        if got != n_answerable:
            return f"expected {n_answerable} answerable questions, got {got}"
        for q in b.questions:
            if q.answerable and (q.passage is None or not 1 <= q.passage <= len(passages)):
                return f"answerable question {q.question!r} needs a valid passage number"
        return None

    result = await client.generate_json(
        purpose=LLMPurpose.SCENARIO_GEN,
        messages=[ChatMessage(role="user", content=prompt)],
        schema=RagQuestionBatch,
        prompt_hash=prompt_hash(PROMPT),
        max_output_tokens=6000,
        thinking=False,
        timeout_s=180.0,
        semantic_check=check,
    )
    return result.parsed


def question_scenario(
    agent_id: UUID | None,
    question: str,
    reference_answer: str,
    expectation: RagExpectation,
) -> ScenarioCreate:
    """The scenario shape used by both generation and CSV import."""
    return ScenarioCreate(
        agent_id=agent_id,
        title=question[:300],
        caller_goal=f"Ask the agent: {question}",
        success_criteria=reference_answer
        or (UNANSWERABLE_CRITERIA if not expectation.answerable else "Answer matches the source."),
        tags=["rag", "answerable" if expectation.answerable else "unanswerable"],
        max_turns=4,
        rag_expectation=expectation,
    )


class CsvError(Exception):
    pass


def parse_csv(data: bytes) -> list[dict[str, str]]:
    """Rows keyed by the four required columns (extra columns ignored)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvError("file is not UTF-8 text") from exc
    reader = csv.DictReader(io.StringIO(text))
    names = {(h or "").strip().lower(): h for h in reader.fieldnames or []}
    missing = [c for c in CSV_COLUMNS if c not in names]
    if missing:
        raise CsvError(f"missing columns: {', '.join(missing)}")
    rows: list[dict[str, str]] = []
    try:
        for raw in reader:
            if len(rows) >= MAX_CSV_ROWS:
                raise CsvError(f"more than {MAX_CSV_ROWS} rows")
            rows.append({c: (raw.get(names[c]) or "").strip() for c in CSV_COLUMNS})
    except csv.Error as exc:
        raise CsvError(f"malformed CSV: {exc}") from exc
    return rows
