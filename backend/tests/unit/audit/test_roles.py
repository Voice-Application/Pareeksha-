"""Role detection: first-speaker rule plus the LLM check."""

from __future__ import annotations

import json

import pytest

from pareeksha.audit.roles import detect_roles, heuristic_roles
from pareeksha.audit.turns import LabelledSegment
from pareeksha.llm.base import LLMPurpose, LLMRetryableError
from tests.unit.evaluation.fakes import ScriptedProvider, client_for

SEGMENTS = [
    LabelledSegment("spk_0", 0, 3000, "namaste, yeh Shree Finance se call hai, call recorded hai"),
    LabelledSegment("spk_1", 3500, 5000, "haan boliye, mera number 9876543210 hai"),
    LabelledSegment("spk_0", 5500, 8000, "aapki EMI chaar hazaar do sau hai"),
]


def verdict(roles: dict[str, str], confidence: str = "high", reason: str = "greets") -> str:
    return json.dumps({"speaker_roles": roles, "confidence": confidence, "reason": reason})


def test_first_speaker_is_the_agent() -> None:
    assert heuristic_roles(SEGMENTS) == {"spk_0": "agent", "spk_1": "caller"}
    assert heuristic_roles([]) == {}


async def test_no_client_falls_back_to_the_heuristic_and_says_so() -> None:
    d = await detect_roles(SEGMENTS, None)
    assert d.method == "heuristic" and d.roles == {"spk_0": "agent", "spk_1": "caller"}
    assert "not configured" in d.note and d.llm is None and d.agrees_with_heuristic is None


async def test_no_speech_gives_empty_roles() -> None:
    assert (await detect_roles([], None)).roles == {}
    provider = ScriptedProvider([])
    assert (await detect_roles([], client_for(provider))).note == "no speech"
    assert provider.requests == []


async def test_confident_llm_agreement_is_used_and_prompt_masks_pii() -> None:
    provider = ScriptedProvider([verdict({"spk_0": "agent", "spk_1": "caller"})])
    d = await detect_roles(
        SEGMENTS, client_for(provider), agent_name="Shree Finance Bot", language="hi-IN"
    )
    assert d.method == "llm" and d.agrees_with_heuristic is True
    assert d.llm_confidence == "high" and d.input_tokens == 1000 and d.est_cost is not None
    request = provider.requests[0]
    assert request.purpose is LLMPurpose.ROLE_DETECT and request.temperature == 0.0
    prompt = request.messages[0].content
    assert "Shree Finance Bot" in prompt and "hi-IN" in prompt and "spk_1 | 3500" in prompt
    assert "9876543210" not in prompt  # PII is masked before the text leaves the platform


async def test_confident_llm_override_wins_over_first_speaker_rule() -> None:
    provider = ScriptedProvider([verdict({"spk_0": "caller", "spk_1": "agent"}, "medium", "x")])
    d = await detect_roles(SEGMENTS, client_for(provider))
    assert d.method == "llm" and d.roles == {"spk_0": "caller", "spk_1": "agent"}
    assert d.agrees_with_heuristic is False and "overrides" in d.note
    assert d.heuristic == {"spk_0": "agent", "spk_1": "caller"}
    event = d.to_event()
    assert event["event"] == "role_detection" and event["method"] == "llm"


async def test_low_confidence_keeps_the_heuristic() -> None:
    provider = ScriptedProvider([verdict({"spk_0": "caller", "spk_1": "agent"}, "low")])
    d = await detect_roles(SEGMENTS, client_for(provider))
    assert d.method == "heuristic" and d.roles == {"spk_0": "agent", "spk_1": "caller"}
    assert d.llm == {"spk_0": "caller", "spk_1": "agent"} and "low" in d.note


async def test_verdict_with_wrong_keys_is_repaired_once() -> None:
    provider = ScriptedProvider(
        [verdict({"spk_0": "agent"}), verdict({"spk_0": "agent", "spk_1": "caller"})]
    )
    d = await detect_roles(SEGMENTS, client_for(provider))
    assert d.method == "llm" and len(provider.requests) == 2
    assert "exactly the keys" in provider.requests[1].messages[-1].content


async def test_two_speakers_with_the_same_role_are_invalid() -> None:
    bad = verdict({"spk_0": "agent", "spk_1": "agent"})
    provider = ScriptedProvider([bad, bad, bad])
    d = await detect_roles(SEGMENTS, client_for(provider))
    assert d.method == "heuristic" and "unusable" in d.note


async def test_single_speaker_may_have_a_single_role() -> None:
    one = [LabelledSegment("spk_0", 0, 2000, "hello, who is this")]
    provider = ScriptedProvider([verdict({"spk_0": "caller"})])
    d = await detect_roles(one, client_for(provider))
    assert d.roles == {"spk_0": "caller"} and d.method == "llm"


async def test_missing_key_degrades_to_heuristic() -> None:
    from pareeksha.llm.client import LLMClient
    from pareeksha.llm.config import LLMConfigError

    class NoKeyProvider(ScriptedProvider):
        async def complete_json(self, request):  # type: ignore[no-untyped-def]
            raise LLMConfigError("DEEPSEEK_API_KEY is not set")

    client = LLMClient(NoKeyProvider([]), client_for(ScriptedProvider([])).settings)
    d = await detect_roles(SEGMENTS, client)
    assert d.method == "heuristic" and "unavailable" in d.note


async def test_retryable_provider_errors_propagate_for_the_consumer_to_retry() -> None:
    provider = ScriptedProvider([LLMRetryableError("503")])
    with pytest.raises(LLMRetryableError):
        await detect_roles(SEGMENTS, client_for(provider))
