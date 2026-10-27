"""LLMClient (validation, repair retry, usage logging, cache), prompts, factory, caller brain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jinja2 import UndefinedError
from pydantic import BaseModel

from pareeksha.llm.base import (
    ChatMessage,
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMProvider,
    LLMProviderName,
    LLMPurpose,
    LLMUsage,
)
from pareeksha.llm.caller import CallerBrain, CallerReply, HistoryLine
from pareeksha.llm.client import (
    FileJSONCache,
    InMemoryJSONCache,
    JSONGenerationError,
    LLMClient,
    UsageRecord,
    parse_json_text,
)
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.deepseek import DeepSeekProvider
from pareeksha.llm.factory import build_client, build_provider
from pareeksha.llm.gemini import GeminiProvider
from pareeksha.llm.prompts import prompt_hash, render_prompt
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate


class Out(BaseModel):
    x: int


class FakeProvider(LLMProvider):
    name = LLMProviderName.DEEPSEEK

    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.requests: list[JSONCompletionRequest] = []
        self.closed = False

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        self.requests.append(request)
        return JSONCompletionResult(
            provider=self.name,
            model=request.model,
            text=self.texts.pop(0),
            usage=LLMUsage(input_tokens=100, output_tokens=10),
            latency_ms=5,
        )

    async def aclose(self) -> None:
        self.closed = True


def settings(**kw: object) -> LLMSettings:
    return LLMSettings(
        _env_file=None,
        deepseek_api_key="k",
        cost_deepseek_per_1k_input_tokens=1.0,
        cost_deepseek_per_1k_output_tokens=2.0,
        **kw,  # type: ignore[arg-type]
    )


def make(texts: list[str], **kw: object) -> tuple[LLMClient, FakeProvider, list[UsageRecord]]:
    prov = FakeProvider(texts)
    records: list[UsageRecord] = []
    client = LLMClient(prov, settings(), usage_sink=records.append, **kw)  # type: ignore[arg-type]
    return client, prov, records


MSGS = [ChatMessage(role="user", content="go")]


async def gen(client: LLMClient, **kw: object):  # type: ignore[no-untyped-def]
    return await client.generate_json(
        purpose=LLMPurpose.JUDGE,
        messages=MSGS,
        schema=Out,
        prompt_hash="h",
        **kw,  # type: ignore[arg-type]
    )


async def test_valid_first_try_logs_usage_and_cost() -> None:
    client, prov, records = make(['{"x": 3}'])
    res = await gen(client)
    assert res.parsed.x == 3 and not res.repaired
    assert res.est_cost == pytest.approx(0.1 + 0.02)
    assert len(records) == 1 and records[0].purpose is LLMPurpose.JUDGE
    assert records[0].prompt_hash == "h" and not records[0].repair
    req = prov.requests[0]
    assert req.model == "deepseek-v4-pro" and req.temperature == 0.0
    assert req.json_schema is not None and "x" in req.json_schema["properties"]


async def test_fenced_json_is_accepted() -> None:
    assert parse_json_text('```json\n{"x": 1}\n```') == {"x": 1}
    client, _, _ = make(['```json\n{"x": 4}\n```'])
    assert (await gen(client)).parsed.x == 4


@pytest.mark.parametrize("bad", ["not json", '{"x": "abc"}', '{"y": 1}'])
async def test_one_repair_retry_then_success(bad: str) -> None:
    client, prov, records = make([bad, '{"x": 5}'])
    res = await gen(client)
    assert res.parsed.x == 5 and res.repaired
    assert res.usage.input_tokens == 200 and res.usage.output_tokens == 20
    assert [r.repair for r in records] == [False, True]
    repair_msgs = prov.requests[1].messages
    assert repair_msgs[-2].role == "assistant" and repair_msgs[-2].content == bad
    assert "rejected" in repair_msgs[-1].content


async def test_repair_failure_raises_with_raw_text() -> None:
    client, _, records = make(["nope", "still nope"])
    with pytest.raises(JSONGenerationError) as exc:
        await gen(client)
    assert exc.value.raw_text == "still nope"
    assert len(records) == 2  # both attempts are billed and logged


async def test_semantic_check_triggers_repair() -> None:
    def check(o: Out) -> str | None:
        return "x must be even" if o.x % 2 else None

    client, prov, _ = make(['{"x": 3}', '{"x": 4}'])
    res = await gen(client, semantic_check=check)
    assert res.parsed.x == 4 and res.repaired
    assert "x must be even" in prov.requests[1].messages[-1].content


async def test_async_sink_and_overrides() -> None:
    seen: list[UsageRecord] = []

    async def sink(r: UsageRecord) -> None:
        seen.append(r)

    prov = FakeProvider(['{"x": 1}'])
    client = LLMClient(prov, settings(), usage_sink=sink)
    await gen(client, model="pinned-x", temperature=0.3, thinking=True, max_output_tokens=7)
    assert prov.requests[0].model == "pinned-x" and prov.requests[0].temperature == 0.3
    assert prov.requests[0].thinking and prov.requests[0].max_output_tokens == 7
    assert len(seen) == 1
    await client.aclose()
    assert prov.closed


async def test_cache_reproduces_response_and_skips_provider() -> None:
    cache = InMemoryJSONCache()
    client, prov, records = make(['{"x": 1}', '{"x": 2}'], cache=cache)
    a = await gen(client, cache_salt="seed-1")
    b = await gen(client, cache_salt="seed-1")
    c = await gen(client, cache_salt="seed-2")
    assert (a.parsed.x, b.parsed.x, c.parsed.x) == (1, 1, 2)
    assert b.cache_hit and b.usage.total_tokens == 0
    assert len(prov.requests) == 2
    assert [r.cache_hit for r in records] == [False, True, False]


async def test_corrupt_cache_entry_falls_back_to_provider() -> None:
    cache = InMemoryJSONCache()
    client, prov, _ = make(['{"x": 9}'], cache=cache)
    # poison the entry that the first call would hit
    probe, _, _ = make(['{"x": 0}'], cache=cache)
    await gen(probe, cache_salt="s")
    key = next(iter(cache._data))
    cache.set(key, "garbage")
    assert (await gen(client, cache_salt="s")).parsed.x == 9
    assert len(prov.requests) == 1


def test_prompt_hash_is_sha256_of_unrendered_template() -> None:
    h = prompt_hash("caller_v1")
    assert len(h) == 64 and h == prompt_hash("caller_v1")


def test_render_prompt_keeps_indic_text_and_rejects_missing_vars() -> None:
    out = render_prompt("caller_v1", **caller_ctx([]))
    assert "ಇಎಂಐ" in out  # fixtures rendered unescaped
    ctx = caller_ctx([])
    del ctx["turn_number"]
    with pytest.raises(UndefinedError, match="turn_number"):
        render_prompt("caller_v1", **ctx)


def test_build_provider_selects_by_settings() -> None:
    assert isinstance(build_provider(settings()), DeepSeekProvider)
    g = LLMSettings(_env_file=None, llm_provider=LLMProviderName.GEMINI, gemini_api_key="g")
    assert isinstance(build_provider(g), GeminiProvider)
    with pytest.raises(LLMConfigError):
        build_provider(
            LLMSettings(_env_file=None, llm_provider=LLMProviderName.GEMINI, gemini_api_key=None)
        )
    assert isinstance(build_client(settings()), LLMClient)


PERSONA = PersonaCreate(
    name="Lakshmamma, elderly",
    language="kn-IN",
    code_mix_style="none",
    voice_id="Lakshmi",
    emotion="confused",
    behaviour_notes="Asks to repeat",
)
SCENARIO = ScenarioCreate(
    title="EMI",
    caller_goal="Promise to pay the EMI on Friday",
    fixtures={"emi": "ಇಎಂಐ 4000", "due_date": "Friday"},
    success_criteria="PTP recorded",
)


def caller_ctx(history: list[HistoryLine]) -> dict[str, object]:
    return {"persona": PERSONA, "scenario": SCENARIO, "history": history, "turn_number": 1}


async def test_caller_brain_prompt_and_seeded_reproducibility() -> None:
    cache = InMemoryJSONCache()
    reply = json.dumps({"utterance": "ಹಲೋ", "end_call": False}, ensure_ascii=False)
    client, prov, _ = make([reply, reply], cache=cache)
    brain = CallerBrain(client, seed=7)
    first = await brain.next_utterance(PERSONA, SCENARIO, [])
    again = await brain.next_utterance(PERSONA, SCENARIO, [])
    assert first.parsed == again.parsed == CallerReply(utterance="ಹಲೋ", end_call=False)
    assert again.cache_hit and len(prov.requests) == 1
    req = prov.requests[0]
    assert req.purpose is LLMPurpose.CALLER and req.model == "deepseek-flash"
    assert req.temperature == 0.0  # opening line
    assert "kn-IN" in req.messages[0].content and "Friday" in req.messages[0].content

    other = CallerBrain(client, seed=8)
    await other.next_utterance(PERSONA, SCENARIO, [])
    assert len(prov.requests) == 2  # different seed -> new sample


async def test_caller_brain_later_turn_uses_caller_temperature() -> None:
    client, prov, _ = make(['{"utterance": "ಸರಿ", "end_call": true}'])
    history = [
        HistoryLine("agent", "Namaste, this is about your EMI"),
        HistoryLine("caller", "ಹಲೋ"),
        HistoryLine("agent", "Can you pay Friday?"),
    ]
    res = await CallerBrain(client).next_utterance(PERSONA, SCENARIO, history)
    assert res.parsed.end_call
    assert prov.requests[0].temperature == 0.7
    assert "agent: Can you pay Friday?" in prov.requests[0].messages[0].content
    assert "Turn number: 2" in prov.requests[0].messages[0].content


async def test_file_cache_survives_a_new_client(tmp_path: Path) -> None:
    c1, _, _ = make(['{"x": 7}'], cache=FileJSONCache(tmp_path / "c"))
    await gen(c1, cache_salt="s")
    c2, prov2, _ = make([], cache=FileJSONCache(tmp_path / "c"))
    res = await gen(c2, cache_salt="s")
    assert res.parsed.x == 7 and res.cache_hit and not prov2.requests


async def test_two_repair_attempts_recover_on_the_second_and_sum_usage() -> None:
    def check(o: Out) -> str | None:
        return "x must be even" if o.x % 2 else None

    client, prov, records = make(['{"x": 1}', '{"x": 3}', '{"x": 6}'])
    res = await gen(client, semantic_check=check, repair_attempts=2)
    assert res.parsed.x == 6 and res.repaired
    assert res.usage.input_tokens == 300 and len(records) == 3
    assert prov.requests[2].messages[-2].content == '{"x": 3}'
