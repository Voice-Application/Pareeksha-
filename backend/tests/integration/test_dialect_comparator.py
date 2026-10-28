"""T-FR-DI-5: a comparator engine is evaluated on the same clips and gets its own column."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import psycopg
from httpx import AsyncClient

from pareeksha.dialect.pipeline import DialectDeps
from pareeksha.speech.base import SpeechProviderName, Transcript
from tests.conftest import Tenant
from tests.integration.test_dialect_pipeline import (
    API,
    CLIPS,
    ScriptedSTT,
    make_profiles,
    new_dataset,
    outbox_envelopes,
    run_event,
    upload,
)


class PerfectSTT(ScriptedSTT):
    """A comparator engine that hears the reference exactly."""

    name = SpeechProviderName.DEEPGRAM

    async def transcribe(self, wav: bytes, language: str, **_: Any) -> Transcript:
        t = await super().transcribe(wav, language)
        with wave.open(io.BytesIO(wav)) as w:
            index = round((w.getnframes() / w.getframerate() - 0.5) / 0.1)
        return t.model_copy(update={"text": CLIPS[index][1], "provider": self.name})


async def test_comparator_engine_gets_its_own_column(
    api: AsyncClient,
    tenant: Tenant,
    data_dir: Path,
    pg: psycopg.AsyncConnection[Any],
) -> None:
    profiles = await make_profiles(api, tenant)
    dataset = await new_dataset(api, tenant)
    await upload(api, tenant, dataset)
    ev = await api.post(
        f"{API}/dialect-datasets/{dataset}/evaluate",
        json={
            "noise_profile_ids": [profiles["clean_16k"]],
            "engines": ["gnani-prisma", "deepgram-nova-3"],
        },
        headers=tenant.admin,
    )
    assert ev.json()["expected_results"] == 8  # 4 clips x 1 condition x 2 engines
    report_id = ev.json()["report_id"]
    engines = {SpeechProviderName.GNANI: ScriptedSTT(), SpeechProviderName.DEEPGRAM: PerfectSTT()}
    deps = DialectDeps(data_dir=data_dir, stt_for=lambda n: engines[n], llm_for=lambda _s: None)
    for env in await outbox_envelopes(pg, report_id):
        await run_event(pg, env, deps)
    report = (await api.get(f"{API}/dialect-reports/{report_id}", headers=tenant.read)).json()
    by_engine = report["aggregates"]["kn-north"]["clean_16k"]
    assert set(by_engine) == {"gnani-prisma", "deepgram-nova-3"}
    assert by_engine["deepgram-nova-3"]["wer"] == 0.0 < by_engine["gnani-prisma"]["wer"]
    assert by_engine["gnani-prisma"]["intent_preserved_rate"] is None  # no LLM configured
    html = (await api.get(f"{API}/dialect-reports/{report_id}/html", headers=tenant.read)).text
    assert "Engine: gnani-prisma" in html and "Engine: deepgram-nova-3" in html
    clips = (
        await api.get(
            f"{API}/dialect-reports/{report_id}/clips",
            params={"engine": "deepgram-nova-3"},
            headers=tenant.read,
        )
    ).json()
    assert len(clips["items"]) == 4 and {c["wer"] for c in clips["items"]} == {0.0}
