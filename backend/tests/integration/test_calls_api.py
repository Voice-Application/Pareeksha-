"""GET /calls, /calls/{id}, /calls/{id}/audio/{track} (API-04). Real app, real Postgres."""

from __future__ import annotations

import io
import uuid
import wave
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.conftest import Tenant, new_tenant
from tests.integration.api04_support import (
    Factory,
    new_rubric,
    seed_full_call,
    seed_run,
)
from tests.integration.runs_support import API


def _wav(seconds: float = 0.5) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(bytes(range(256)) * int(16000 * seconds * 2 / 256))
    return buf.getvalue()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------------- detail


async def test_call_detail_returns_every_part_of_the_call(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, data_dir: Path
) -> None:
    rubric = await new_rubric(session_factory)
    seeded = await seed_full_call(
        session_factory,
        tenant,
        None,
        rubric,
        needs_review=True,
        recordings={"recording_mixed": "audio/m.wav", "recording_caller": "audio/c.wav"},
    )
    body = (await api.get(f"{API}/calls/{seeded.call_id}", headers=tenant.read)).json()

    assert body["id"] == str(seeded.call_id)
    assert (body["source"], body["status"], body["language"]) == (
        "simulation",
        "completed",
        "kn-IN",
    )
    assert (body["end_reason"], body["duration_ms"]) == ("goal_achieved", 84200)
    # recordings: URLs only for the tracks that exist
    assert body["recordings"] == {
        "mixed": f"{API}/calls/{seeded.call_id}/audio/mixed",
        "caller": f"{API}/calls/{seeded.call_id}/audio/caller",
        "agent": None,
        "original": None,
    }
    assert [t["idx"] for t in body["turns"]] == [0, 1]
    caller_turn = body["turns"][1]
    assert caller_turn["ground_truth_text"] == "Sir, naanu already pay maadidini"
    assert caller_turn["agent_heard_text"] == "naalvattu saavira"
    assert caller_turn["is_barge_in"] is True and caller_turn["stt_confidence"] == 0.912
    assert body["turns"][0]["text"] == "Namaskara"
    assert body["tool_calls"] == [
        {
            "seq": 0,
            "name": "record_promise_to_pay",
            "arguments": {"amount": 40000},
            "result": {"ok": True},
            "at_ms": 11200,
            "turn_idx": 1,
        }
    ]
    assert body["metrics"]["first_greeting_ms"] == 820
    assert body["metrics"]["caller_asr_wer"] == 0.18
    assert body["metrics"]["barge_in_attempts"] == 2 and body["metrics"]["turn_count"] == 2
    checks = {c["check_type"]: c for c in body["checks"]}
    assert checks["disclosure_present"]["passed"] is False
    assert checks["disclosure_present"]["evidence_turns"] == [0, 2]
    assert checks["no_loop"]["passed"] is True
    evaluation = body["evaluation"]
    assert evaluation["id"] == str(seeded.evaluation_id)
    assert evaluation["rubric_version"].startswith("test-")
    assert evaluation["overall_score"] == 40.0 and evaluation["passed"] is False
    assert evaluation["critical_failure"] is True and evaluation["needs_human_review"] is True
    assert evaluation["review_reasons"] == ["critical_failure"]
    assert evaluation["failure_types"] == ["wrong_fact"]
    assert evaluation["dimensions"]["task_completion"] == {
        "score": 1,
        "evidence_turns": [1],
        "reason": "Wrong amount.",
    }
    assert evaluation["confidence"] == "high" and evaluation["judge_model"] == "deepseek-v4-pro"


async def test_call_without_evaluation_or_recordings_and_upload_speaker_map(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    rubric = await new_rubric(session_factory)
    seeded = await seed_full_call(
        session_factory, tenant, None, rubric, source="upload", score=None
    )
    body = (await api.get(f"{API}/calls/{seeded.call_id}", headers=tenant.read)).json()
    assert body["evaluation"] is None
    assert body["run_id"] is None and body["recordings"] == {
        "mixed": None, "caller": None, "agent": None, "original": None,
    }  # fmt: skip
    assert body["speaker_map"] == {"spk_0": "agent", "spk_1": "caller"}


async def test_call_of_a_run_reports_run_id_and_latest_evaluation(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    seeded = await seed_run(api, session_factory, tenant, scores=[(72.5, False)])
    call = seeded.calls[0]
    body = (await api.get(f"{API}/calls/{call.call_id}", headers=tenant.read)).json()
    assert body["run_id"] == str(seeded.run_id) and body["run_item_id"] == str(call.run_item_id)
    assert body["evaluation"]["overall_score"] == 72.5


async def test_unknown_and_foreign_calls_are_404(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    rubric = await new_rubric(session_factory)
    other = await new_tenant(session_factory)
    foreign = await seed_full_call(session_factory, other, None, rubric)
    for call_id in (uuid.uuid4(), foreign.call_id):
        response = await api.get(f"{API}/calls/{call_id}", headers=tenant.read)
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
        audio = await api.get(f"{API}/calls/{call_id}/audio/mixed", headers=tenant.read)
        assert audio.status_code == 404


async def test_calls_need_a_key(api: AsyncClient) -> None:
    assert (await api.get(f"{API}/calls")).status_code == 401
    assert (await api.get(f"{API}/calls/{uuid.uuid4()}")).status_code == 401


# ---------------------------------------------------------------------------------- list


async def test_list_filters_and_paging(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    rubric = await new_rubric(session_factory)
    other = await new_tenant(session_factory)
    await seed_full_call(session_factory, other, None, rubric)  # never visible to `tenant`
    sim = await seed_run(api, session_factory, tenant, scores=[(90, True), (30, False)])
    up_review = await seed_full_call(
        session_factory, tenant, None, rubric, source="upload", needs_review=True,
        started_ago=timedelta(hours=1),
    )  # fmt: skip
    up_done = await seed_full_call(
        session_factory, tenant, None, rubric, source="import", needs_review=True, reviewed=True,
        started_ago=timedelta(hours=2),
    )  # fmt: skip
    pending = await seed_full_call(
        session_factory, tenant, None, rubric, source="upload", status="transcribing", score=None,
        started_ago=timedelta(hours=3),
    )  # fmt: skip

    async def ids(query: str) -> set[str]:
        response = await api.get(f"{API}/calls?limit=200&{query}", headers=tenant.read)
        assert response.status_code == 200, response.text
        return {c["id"] for c in response.json()["items"]}

    everything = await ids("")
    assert len(everything) == 5
    assert await ids("source=simulation") == {str(c.call_id) for c in sim.calls}
    assert await ids("source=upload&source=import") == {
        str(up_review.call_id), str(up_done.call_id), str(pending.call_id),
    }  # fmt: skip
    assert await ids("status=transcribing") == {str(pending.call_id)}
    assert await ids(f"run_id={sim.run_id}") == {str(c.call_id) for c in sim.calls}
    assert await ids("needs_review=true") == {str(up_review.call_id), str(up_done.call_id)}
    # the human-review queue
    assert await ids("needs_review=true&reviewed=false") == {str(up_review.call_id)}
    assert await ids("reviewed=true") == {str(up_done.call_id)}
    assert await ids("needs_review=false&source=simulation") == {str(c.call_id) for c in sim.calls}

    full = (await api.get(f"{API}/calls?limit=200", headers=tenant.read)).json()["items"]
    row = next(c for c in full if c["id"] == str(up_review.call_id))
    assert row["overall_score"] == 40.0 and row["passed"] is False
    assert row["critical_failure"] is True and row["needs_human_review"] is True
    assert row["review_reasons"] == ["critical_failure"] and row["failure_types"] == ["wrong_fact"]
    assert row["human_reviewed"] is False and row["source"] == "upload"
    unscored = next(c for c in full if c["id"] == str(pending.call_id))
    assert unscored["overall_score"] is None and unscored["needs_human_review"] is None

    # newest first, paged by cursor without repeats or gaps
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await api.get(f"{API}/calls", params=params, headers=tenant.read)).json()
        assert len(page["items"]) <= 2
        seen += [c["id"] for c in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5 and set(seen) == everything
    assert seen[-3:] == [str(up_review.call_id), str(up_done.call_id), str(pending.call_id)]


async def test_list_filters_by_agent_and_rejects_bad_values(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    seeded = await seed_run(api, session_factory, tenant, scores=[(80, True)])
    listed = await api.get(f"{API}/calls?agent_id={seeded.fx.agent_id}", headers=tenant.read)
    assert [c["id"] for c in listed.json()["items"]] == [str(seeded.calls[0].call_id)]
    none = await api.get(f"{API}/calls?agent_id={uuid.uuid4()}", headers=tenant.read)
    assert none.json() == {"items": [], "next_cursor": None}
    assert (await api.get(f"{API}/calls?source=phone", headers=tenant.read)).status_code == 400
    assert (await api.get(f"{API}/calls?cursor=nope", headers=tenant.read)).status_code == 400


# ---------------------------------------------------------------------------------- audio


async def _call_with_audio(
    tenant: Tenant, factory: Factory, data_dir: Path, **tracks: str
) -> tuple[uuid.UUID, bytes]:
    audio = _wav()
    for rel in tracks.values():
        (data_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (data_dir / rel).write_bytes(audio)
    rubric = await new_rubric(factory)
    seeded = await seed_full_call(
        factory, tenant, None, rubric, recordings={f"recording_{k}": v for k, v in tracks.items()}
    )
    return seeded.call_id, audio


async def test_audio_full_download_and_content_type(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, data_dir: Path
) -> None:
    call_id, audio = await _call_with_audio(
        tenant, session_factory, data_dir, mixed="calls/a/mixed.wav", agent="calls/a/agent.wav"
    )
    response = await api.get(f"{API}/calls/{call_id}/audio/mixed", headers=tenant.read)
    assert response.status_code == 200 and response.content == audio
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content[:4] == b"RIFF"
    agent = await api.get(f"{API}/calls/{call_id}/audio/agent", headers=tenant.read)
    assert agent.status_code == 200


async def test_audio_range_requests(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, data_dir: Path
) -> None:
    call_id, audio = await _call_with_audio(
        tenant, session_factory, data_dir, mixed="calls/b/mixed.wav"
    )
    url = f"{API}/calls/{call_id}/audio/mixed"
    size = len(audio)

    async def ranged(value: str) -> tuple[int, bytes, str | None]:
        r = await api.get(url, headers={**tenant.read, "Range": value})
        return r.status_code, r.content, r.headers.get("content-range")

    assert await ranged("bytes=0-99") == (206, audio[:100], f"bytes 0-99/{size}")
    assert await ranged("bytes=100-") == (206, audio[100:], f"bytes 100-{size - 1}/{size}")
    assert await ranged("bytes=-50") == (206, audio[-50:], f"bytes {size - 50}-{size - 1}/{size}")
    # the end is clamped to the file
    assert await ranged(f"bytes=10-{size + 500}") == (
        206,
        audio[10:],
        f"bytes 10-{size - 1}/{size}",
    )
    status, _, content_range = await ranged(f"bytes={size}-")
    assert status == 416 and content_range == f"bytes */{size}"
    assert (await api.get(url, headers={**tenant.read, "Range": f"bytes={size}-"})).json()["error"][
        "code"
    ] == "range_not_satisfiable"
    assert (await ranged("bytes=-0"))[0] == 416
    # a syntax we do not understand is ignored: the whole file
    assert (await ranged("items=1-2"))[:2] == (200, audio)
    assert (await ranged("bytes=0-1,5-6"))[:2] == (200, audio)


async def test_audio_missing_track_file_and_path_escape(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: Factory,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = data_dir.parent / f"secret-{uuid.uuid4().hex}.wav"
    secret.write_bytes(b"not for you")
    rubric = await new_rubric(session_factory)
    seeded = await seed_full_call(
        session_factory,
        tenant,
        None,
        rubric,
        recordings={
            "recording_mixed": "calls/missing.wav",  # row exists, file does not
            "recording_caller": f"../{secret.name}",  # outside DATA_DIR
        },
    )
    base = f"{API}/calls/{seeded.call_id}/audio"
    no_track = await api.get(f"{base}/agent", headers=tenant.read)
    assert (
        no_track.status_code == 404 and "no agent recording" in no_track.json()["error"]["message"]
    )
    assert (await api.get(f"{base}/mixed", headers=tenant.read)).status_code == 404
    escaped = await api.get(f"{base}/caller", headers=tenant.read)
    assert escaped.status_code == 404 and b"not for you" not in escaped.content
    assert (await api.get(f"{base}/bogus", headers=tenant.read)).status_code == 400
    monkeypatch.delenv("DATA_DIR")
    assert (await api.get(f"{base}/mixed", headers=tenant.read)).status_code == 404
