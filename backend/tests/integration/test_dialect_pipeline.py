"""EVAL-05 end to end against the real app and Postgres (no Kafka needed here: the consumer's
handler is driven directly with the events the API wrote to the outbox).

Only the speech engine and the LLM are test doubles; the audio degradation, normalisation,
metrics, bootstrap, aggregation, HTML report and every SQL statement are the production code. The
live run (real Kafka, real Gnani, real DeepSeek) is captured in proof/EVAL-05.
"""

from __future__ import annotations

import io
import json
import uuid
import wave
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pytest
from httpx import AsyncClient

from pareeksha.audio.profiles import get_profile
from pareeksha.dialect.pipeline import DialectDeps, clip_seed, degrade, handle_clip_requested
from pareeksha.events.consumer import Ctx, PermanentError
from pareeksha.events.schemas import AnyEnvelope, DialectClipRequested, parse_envelope
from pareeksha.llm.base import (
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMProvider,
    LLMProviderName,
    LLMUsage,
)
from pareeksha.llm.client import LLMClient, UsageRecord
from pareeksha.llm.config import LLMSettings
from pareeksha.speech.base import (
    SpeechPermanentError,
    SpeechProviderName,
    SpeechUsage,
    STTCapabilities,
    STTProvider,
    Transcript,
)
from tests.conftest import Tenant
from tests.unit.dialect.test_manifest_consent import HEADER

API = "/api/v1"

# (file, reference, hypothesis under noise, dialect, speaker, domain terms)
CLIPS = [
    ("a1.wav", "ನಿಮ್ಮ ಕಂತು ಐದು ಸಾವಿರ ರೂಪಾಯಿ", "ನಿಮ್ಮ ಕಾಂತು 5000 ರೂಪಾಯಿ", "kn-north", "s1", "ಕಂತು"),
    ("a2.wav", "ಬಾಕಿ ಮೂರು ತಿಂಗಳು ಇದೆ", "ಬಾಕಿ ಮೂರು ತಿಂಗಳು ಇದೆ", "kn-north", "s2", ""),
    ("b1.wav", "आपकी ईएमआई पाँच हज़ार है", "आपकी ईएमआई 5000 है", "hi-delhi", "s3", ""),
    ("b2.wav", "भुगतान कल तक करें", "भुगतान कल तक करो", "hi-delhi", "s4", ""),
]


def wav_bytes(seconds: float, rate: int = 16000) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    pcm = (np.sin(2 * np.pi * 220 * t) * 9000).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def clip_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, (name, *_rest) in enumerate(CLIPS):
            z.writestr(name, wav_bytes(0.5 + 0.1 * i))  # the duration identifies the clip
    return buf.getvalue()


def manifest(consent: dict[str, str] | None = None) -> bytes:
    lines = [
        f"{f},{ref},kn-IN,{d},{sp},{(consent or {}).get(f, 'true')},{terms}"
        for f, ref, _hyp, d, sp, terms in CLIPS
    ]
    return (HEADER + "\n".join(lines) + "\n").encode()


class ScriptedSTT(STTProvider):
    """Returns the scripted hypothesis for a clip (identified by its duration)."""

    name = SpeechProviderName.GNANI
    capabilities = STTCapabilities(
        streaming=False, word_timings=False, word_confidence=False, diarization=False
    )

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.calls = 0
        self.fail_with = fail_with

    async def transcribe(self, wav: bytes, language: str, **_: Any) -> Transcript:
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        with wave.open(io.BytesIO(wav)) as w:
            seconds = w.getnframes() / w.getframerate()
        index = round((seconds - 0.5) / 0.1)
        return Transcript(
            provider=SpeechProviderName.GNANI,
            model="scripted-1",
            text=CLIPS[index][2],
            language=language,
            duration_s=seconds,
            usage=SpeechUsage(
                provider=SpeechProviderName.GNANI,
                operation="stt_rest",
                audio_seconds=seconds,
                est_cost=0.01,
            ),
        )

    async def aclose(self) -> None:
        return None


class ScriptedLLM(LLMProvider):
    name = LLMProviderName.DEEPSEEK

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        self.prompts.append(request.messages[-1].content)
        preserved = "5000" in request.messages[-1].content
        return JSONCompletionResult(
            provider=LLMProviderName.DEEPSEEK,
            model=request.model,
            text=json.dumps({"preserved": preserved, "reason": "scripted"}),
            usage=LLMUsage(input_tokens=100, output_tokens=10),
            latency_ms=1,
        )

    async def aclose(self) -> None:
        return None


def deps_for(data_dir: Path, stt: STTProvider, llm: ScriptedLLM | None = None) -> DialectDeps:
    def llm_for(sink: Callable[[UsageRecord], Any]) -> LLMClient | None:
        if llm is None:
            return None
        return LLMClient(
            llm, LLMSettings(deepseek_api_key="x", deepseek_judge_model="m"), usage_sink=sink
        )

    return DialectDeps(data_dir=data_dir, stt_for=lambda _name: stt, llm_for=llm_for)


async def run_event(
    conn: psycopg.AsyncConnection[Any], env: AnyEnvelope, deps: DialectDeps
) -> None:
    ctx = Ctx(tx=conn, group="dialect", topic=env.topic.value, partition=0, offset=0, attempt=1)
    async with conn.transaction():
        await handle_clip_requested(env, ctx, deps)  # type: ignore[arg-type]


async def outbox_envelopes(conn: psycopg.AsyncConnection[Any], report_id: str) -> list[AnyEnvelope]:
    cur = await conn.execute(
        "SELECT envelope FROM outbox_events WHERE topic = 'pareeksha.dialect.clip.requested.v1' "
        "AND envelope->'payload'->>'report_id' = %s ORDER BY created_at, id",
        (report_id,),
    )
    return [parse_envelope(row[0]) for row in await cur.fetchall()]


async def usage_counts(conn: psycopg.AsyncConnection[Any]) -> dict[str, int]:
    cur = await conn.execute(
        "SELECT operation, count(*) FROM api_usage "
        "WHERE operation IN ('stt_rest','llm_asr_intent') GROUP BY operation"
    )
    return {op: int(n) for op, n in await cur.fetchall()}


async def make_profiles(api: AsyncClient, tenant: Tenant) -> dict[str, str]:
    ids: dict[str, str] = {}
    bodies: dict[str, dict[str, Any]] = {
        "clean_16k": {"sample_rate": 16000},
        "pstn_8k_alaw": {
            "sample_rate": 8000,
            "codec": "alaw",
            "pstn_bandpass": True,
            "background_category": "street_traffic",
            "snr_db": 10,
        },
    }
    for name, body in bodies.items():
        r = await api.post(
            f"{API}/noise-profiles", json={"name": name, **body}, headers=tenant.admin
        )
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
    return ids


async def upload(
    api: AsyncClient, tenant: Tenant, dataset_id: str, consent: dict[str, str] | None = None
) -> Any:
    return await api.post(
        f"{API}/dialect-datasets/{dataset_id}/samples",
        files={
            "manifest": ("m.csv", manifest(consent), "text/csv"),
            "clips": ("clips.zip", clip_zip(), "application/zip"),
        },
        headers=tenant.admin,
    )


async def new_dataset(api: AsyncClient, tenant: Tenant, name: str = "Kannada v1") -> str:
    r = await api.post(f"{API}/dialect-datasets", json={"name": name}, headers=tenant.admin)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_dataset_lifecycle_and_consent_enforced_end_to_end(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, data_dir: Path
) -> None:
    dataset = await new_dataset(api, tenant)
    dup = await api.post(
        f"{API}/dialect-datasets", json={"name": "Kannada v1"}, headers=tenant.admin
    )
    assert dup.status_code == 409

    r = await upload(api, tenant, dataset, consent={"a2.wav": "false", "b2.wav": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 2
    assert body["rejected"] == [
        {"row": 2, "reason": "consent must be true"},
        {"row": 4, "reason": "consent must be true"},
    ]
    stored = sorted((data_dir / "dialect" / dataset).glob("*.wav"))
    assert len(stored) == 2  # rejected rows' audio is never written to disk

    listing = (await api.get(f"{API}/dialect-datasets", headers=tenant.read)).json()
    assert [(d["name"], d["sample_count"]) for d in listing["items"]] == [("Kannada v1", 2)]
    assert (await api.get(f"{API}/dialect-datasets", headers=other_tenant.read)).json()[
        "items"
    ] == []
    other = await upload(api, other_tenant, dataset)
    assert other.status_code == 404  # another project's dataset
    scope = await api.post(f"{API}/dialect-datasets", json={"name": "x"}, headers=tenant.read)
    assert scope.status_code == 403


async def test_evaluate_validation(api: AsyncClient, tenant: Tenant, data_dir: Path) -> None:
    profiles = await make_profiles(api, tenant)
    dataset = await new_dataset(api, tenant)
    ev = f"{API}/dialect-datasets/{dataset}/evaluate"
    body = {"noise_profile_ids": [profiles["clean_16k"]], "engines": ["gnani-prisma"]}
    assert (await api.post(ev, json=body, headers=tenant.admin)).status_code == 409  # no samples
    assert (await upload(api, tenant, dataset)).status_code == 200
    bad_engine = await api.post(ev, json={**body, "engines": ["whisper"]}, headers=tenant.admin)
    assert bad_engine.status_code == 400
    ghost = await api.post(
        ev, json={**body, "noise_profile_ids": [str(uuid.uuid4())]}, headers=tenant.admin
    )
    assert ghost.status_code == 404
    unknown = await api.post(
        f"{API}/dialect-datasets/{uuid.uuid4()}/evaluate", json=body, headers=tenant.admin
    )
    assert unknown.status_code == 404
    assert (
        await api.get(f"{API}/dialect-reports/{uuid.uuid4()}", headers=tenant.read)
    ).status_code == 404


async def test_full_report_from_outbox_events(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    data_dir: Path,
    pg: psycopg.AsyncConnection[Any],
) -> None:
    profiles = await make_profiles(api, tenant)
    dataset = await new_dataset(api, tenant)
    assert (await upload(api, tenant, dataset)).json()["accepted"] == 4
    accepted = await api.post(
        f"{API}/dialect-datasets/{dataset}/evaluate",
        json={"noise_profile_ids": list(profiles.values()), "engines": ["gnani-prisma"]},
        headers=tenant.admin,
    )
    assert accepted.status_code == 202, accepted.text
    report_id = accepted.json()["report_id"]
    assert accepted.json()["expected_results"] == 8  # 4 clips x 2 conditions x 1 engine

    events = await outbox_envelopes(pg, report_id)
    assert len(events) == 8
    payloads = [e.payload for e in events if isinstance(e.payload, DialectClipRequested)]
    assert len(payloads) == 8 and len({p.sample_id for p in payloads}) == 4
    assert all(
        e.partition_key() == str(e.payload.sample_id)
        for e in events
        if isinstance(e.payload, DialectClipRequested)
    )

    pending = (await api.get(f"{API}/dialect-reports/{report_id}", headers=tenant.read)).json()
    assert pending["progress"] == {"done": 0, "expected_results": 8}
    assert pending["aggregates"] == {} and pending["html"] is None
    html_early = await api.get(f"{API}/dialect-reports/{report_id}/html", headers=tenant.read)
    assert html_early.status_code == 404

    before = await usage_counts(pg)
    stt, llm = ScriptedSTT(), ScriptedLLM()
    deps = deps_for(data_dir, stt, llm)
    for env in events[:-1]:
        await run_event(pg, env, deps)
    mid = (await api.get(f"{API}/dialect-reports/{report_id}", headers=tenant.read)).json()
    assert mid["progress"] == {"done": 7, "expected_results": 8}
    assert mid["aggregates"] == {}  # not frozen before the last result
    await run_event(pg, events[-1], deps)
    assert stt.calls == 8

    done = (await api.get(f"{API}/dialect-reports/{report_id}", headers=tenant.read)).json()
    assert done["progress"] == {"done": 8, "expected_results": 8}
    assert set(done["aggregates"]) == {"kn-north", "hi-delhi"}
    cell = done["aggregates"]["kn-north"]["clean_16k"]["gnani-prisma"]
    assert cell["n"] == 2 and len(cell["wer_ci"]) == 2
    assert cell["wer_ci"][0] <= cell["wer"] <= cell["wer_ci"][1]
    assert cell["entity_acc"] == 0.6667  # 5000 and 3 heard; ಕಂತು heard as ಕಾಂತು
    assert cell["intent_preserved_rate"] == 1.0  # the scripted judge says yes: "5000" in prompt
    assert {t["ref"] for t in done["top_errors"]} >= {"ಕಂತು"}
    assert done["html"] == f"/api/v1/dialect-reports/{report_id}/html"

    page = await api.get(f"{API}/dialect-reports/{report_id}/html", headers=tenant.read)
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "kn-north" in page.text and "95% CI" in page.text and "Kannada v1" in page.text
    (data_dir / "dialect" / "reports" / f"{report_id}.html").unlink()  # worker volume not shared
    rebuilt = await api.get(f"{API}/dialect-reports/{report_id}/html", headers=tenant.read)
    assert rebuilt.status_code == 200 and "95% CI" in rebuilt.text

    clips = (await api.get(f"{API}/dialect-reports/{report_id}/clips", headers=tenant.read)).json()
    wers = [c["wer"] for c in clips["items"]]
    assert len(wers) == 8 and wers == sorted(wers, reverse=True)  # worst first
    only = (
        await api.get(
            f"{API}/dialect-reports/{report_id}/clips",
            params={"dialect": "hi-delhi", "condition": "pstn_8k_alaw", "engine": "gnani-prisma"},
            headers=tenant.read,
        )
    ).json()
    assert len(only["items"]) == 2 and {c["dialect_label"] for c in only["items"]} == {"hi-delhi"}
    first = (
        await api.get(
            f"{API}/dialect-reports/{report_id}/clips", params={"limit": 3}, headers=tenant.read
        )
    ).json()
    assert len(first["items"]) == 3 and first["next_cursor"]
    rest = (
        await api.get(
            f"{API}/dialect-reports/{report_id}/clips",
            params={"limit": 3, "cursor": first["next_cursor"]},
            headers=tenant.read,
        )
    ).json()
    assert [c["sample_id"] for c in rest["items"]] != [c["sample_id"] for c in first["items"]]
    bad = await api.get(
        f"{API}/dialect-reports/{report_id}/clips", params={"cursor": "zz"}, headers=tenant.read
    )
    assert bad.status_code == 400

    reports = (
        await api.get(f"{API}/dialect-reports", params={"dataset_id": dataset}, headers=tenant.read)
    ).json()
    assert [r["id"] for r in reports["items"]] == [report_id]
    assert reports["items"][0]["progress"]["done"] == 8
    assert (await api.get(f"{API}/dialect-reports", headers=other_tenant.read)).json()[
        "items"
    ] == []
    assert (
        await api.get(f"{API}/dialect-reports/{report_id}", headers=other_tenant.read)
    ).status_code == 404

    after = await usage_counts(pg)
    assert after.get("llm_asr_intent", 0) - before.get("llm_asr_intent", 0) == len(llm.prompts)
    assert after.get("stt_rest", 0) - before.get("stt_rest", 0) == 8
    # identical normalised texts need no model call: 8 results, fewer LLM calls
    assert 0 < len(llm.prompts) < 8


async def test_redelivered_event_adds_nothing_and_report_is_aggregated_once(
    api: AsyncClient, tenant: Tenant, data_dir: Path, pg: psycopg.AsyncConnection[Any]
) -> None:
    profiles = await make_profiles(api, tenant)
    dataset = await new_dataset(api, tenant)
    await upload(api, tenant, dataset)
    ev = await api.post(
        f"{API}/dialect-datasets/{dataset}/evaluate",
        json={"noise_profile_ids": [profiles["clean_16k"]], "engines": ["gnani-prisma"]},
        headers=tenant.admin,
    )
    report_id = ev.json()["report_id"]
    stt = ScriptedSTT()
    deps = deps_for(data_dir, stt)
    events = await outbox_envelopes(pg, report_id)
    for env in events:
        await run_event(pg, env, deps)
    assert stt.calls == 4
    html_before = (data_dir / "dialect" / "reports" / f"{report_id}.html").read_text("utf-8")
    for env in events:  # the whole stream again
        await run_event(pg, env, deps)
    assert stt.calls == 4  # nothing transcribed twice
    count = await (
        await pg.execute(
            "SELECT count(*) FROM asr_results r JOIN dialect_samples s ON s.id = r.sample_id "
            "WHERE s.dataset_id = %s",
            (dataset,),
        )
    ).fetchone()
    assert count is not None and count[0] == 4
    assert (data_dir / "dialect" / "reports" / f"{report_id}.html").read_text(
        "utf-8"
    ) == html_before
    flags = await (
        await pg.execute(
            "SELECT aggregates->'_meta'->>'complete' FROM dialect_reports WHERE id = %s",
            (report_id,),
        )
    ).fetchone()
    assert flags == ("true",)


async def test_engine_failures_are_classified_for_the_retry_policy(
    api: AsyncClient, tenant: Tenant, data_dir: Path, pg: psycopg.AsyncConnection[Any]
) -> None:
    profiles = await make_profiles(api, tenant)
    dataset = await new_dataset(api, tenant)
    await upload(api, tenant, dataset)
    ev = await api.post(
        f"{API}/dialect-datasets/{dataset}/evaluate",
        json={"noise_profile_ids": [profiles["clean_16k"]], "engines": ["gnani-prisma"]},
        headers=tenant.admin,
    )
    first = (await outbox_envelopes(pg, ev.json()["report_id"]))[0]
    with pytest.raises(PermanentError):  # bad credentials / unsupported audio: straight to the DLQ
        await run_event(pg, first, deps_for(data_dir, ScriptedSTT(SpeechPermanentError("401"))))
    with pytest.raises(TimeoutError):  # transient: the framework retries it
        await run_event(pg, first, deps_for(data_dir, ScriptedSTT(TimeoutError())))
    count = await (
        await pg.execute(
            "SELECT count(*) FROM asr_results r JOIN dialect_samples s ON s.id = r.sample_id "
            "WHERE s.dataset_id = %s",
            (dataset,),
        )
    ).fetchone()
    assert count is not None and count[0] == 0


async def test_missing_sample_or_profile_is_permanent(
    api: AsyncClient, tenant: Tenant, data_dir: Path, pg: psycopg.AsyncConnection[Any]
) -> None:
    profiles = await make_profiles(api, tenant)
    dataset = await new_dataset(api, tenant)
    await upload(api, tenant, dataset)
    ev = await api.post(
        f"{API}/dialect-datasets/{dataset}/evaluate",
        json={"noise_profile_ids": [profiles["clean_16k"]], "engines": ["gnani-prisma"]},
        headers=tenant.admin,
    )
    env = (await outbox_envelopes(pg, ev.json()["report_id"]))[0]
    payload = env.payload
    assert isinstance(payload, DialectClipRequested)
    deps = deps_for(data_dir, ScriptedSTT())
    for change in ({"sample_id": uuid.uuid4()}, {"noise_profile_id": uuid.uuid4()}):
        bad = env.model_copy(update={"payload": payload.model_copy(update=change)})
        with pytest.raises(PermanentError):
            await run_event(pg, bad, deps)


def test_degradation_is_deterministic_per_clip_and_condition_and_differs_between_conditions() -> (
    None
):
    wav = wav_bytes(1.0)
    sample, cond = uuid.uuid4(), uuid.uuid4()
    pstn = get_profile("pstn_street_10db")
    a = degrade(wav, pstn, clip_seed(sample, cond))
    assert a == degrade(wav, pstn, clip_seed(sample, cond))
    assert a != degrade(wav, pstn, clip_seed(sample, uuid.uuid4()))
    clean = degrade(wav, get_profile("clean_16k"), 0)
    assert clean != a
    with wave.open(io.BytesIO(a)) as w:  # still 16 kHz mono and as long as the input
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (16000, 1, 16000)
    with pytest.raises(PermanentError):
        degrade(b"garbage", pstn, 1)
