"""The ``dialect`` consumer's work (TRD section 9): one ``dialect.clip.requested`` per clip x
condition -> degrade offline with the same ``LineSimulator`` -> transcribe -> normalise and score
-> store one ``asr_results`` row per engine; when the report has all of its results, aggregate.

All SQL runs on ``ctx.tx`` (the framework's transaction), so a crash leaves nothing half-written
and a redelivered event finds its rows already there (``asr_results`` is unique per sample,
condition, engine and model).
"""

from __future__ import annotations

import io
import time
import uuid
import wave
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from pareeksha.audio.line_simulator import LineSimulator
from pareeksha.audio.preview import UnsupportedAudioError, decode_wav, encode_wav
from pareeksha.audio.profiles import LineProfile
from pareeksha.dialect.intent import intent_preserved
from pareeksha.dialect.metrics import score_clip
from pareeksha.dialect.report import ResultRow, aggregate, render_html
from pareeksha.events.consumer import Ctx, Outgoing, PermanentError
from pareeksha.events.schemas import DialectClipRequested, Envelope
from pareeksha.llm.client import LLMClient, UsageRecord
from pareeksha.speech.base import (
    SpeechConfigError,
    SpeechPermanentError,
    SpeechProviderName,
    STTProvider,
)

#: Hypotheses are scored raw: no bias words, so the report measures the engine, not the config.
ENGINE_SEPARATOR = "-"


def engine_provider(engine: str) -> SpeechProviderName:
    """``gnani-prisma`` -> gnani; any registered speech provider can be a comparator (FR-DI-5)."""
    prefix = engine.split(ENGINE_SEPARATOR, 1)[0]
    try:
        return SpeechProviderName(prefix)
    except ValueError as exc:
        known = ", ".join(p.value for p in SpeechProviderName)
        raise ValueError(f"unknown engine {engine!r}: must start with one of {known}") from exc


@dataclass
class DialectDeps:
    """Ports of the consumer (replaced by fakes in unit tests, real providers in production)."""

    data_dir: Path
    stt_for: Callable[[SpeechProviderName], STTProvider]
    llm_for: Callable[[Callable[[UsageRecord], Any]], LLMClient | None]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


def clip_seed(sample_id: uuid.UUID, noise_profile_id: uuid.UUID) -> int:
    """Same clip + same condition -> same degradation, on every run and every instance."""
    return uuid.uuid5(sample_id, str(noise_profile_id)).int % 2**32


def degrade(wav: bytes, profile: LineProfile, seed: int) -> bytes:
    """The clip as the line would deliver it (16 kHz in, 16 kHz out)."""
    try:
        audio = decode_wav(wav)
    except UnsupportedAudioError as exc:
        raise PermanentError(f"unreadable clip: {exc}") from exc
    return encode_wav(LineSimulator.simulate(profile, audio, seed))


def wav_seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return float(w.getnframes() / w.getframerate())


def _profile(row: tuple[Any, ...]) -> LineProfile:
    name, rate, codec, bandpass, background, snr, loss, clipping = row
    return LineProfile(
        name=name,
        sample_rate=rate,
        codec=codec,
        pstn_bandpass=bandpass,
        background=background,
        snr_db=None if snr is None else float(snr),
        packet_loss_pct=float(loss),
        clipping=clipping,
    )


async def _one(conn: psycopg.AsyncConnection[Any], sql: str, params: tuple[Any, ...]) -> Any:
    cur = await conn.execute(sql, params)
    return await cur.fetchone()


async def _record_llm_usage(conn: psycopg.AsyncConnection[Any], record: UsageRecord) -> None:
    await conn.execute(
        "INSERT INTO api_usage (provider, operation, units, unit_type, cached, est_cost) "
        "VALUES (%s, %s, %s, 'tokens', %s, %s)",
        (
            record.provider.value,
            f"llm_{record.purpose.value}",
            record.input_tokens + record.output_tokens,
            record.cache_hit,
            record.est_cost,
        ),
    )


async def handle_clip_requested(
    env: Envelope[DialectClipRequested], ctx: Ctx, deps: DialectDeps
) -> list[Outgoing]:
    """Process one clip x condition for every requested engine, then try to close the report."""
    p = env.payload
    conn = ctx.tx
    sample = await _one(
        conn,
        "SELECT audio_path, reference_text, language, domain_terms, consent "
        "FROM dialect_samples WHERE id = %s",
        (p.sample_id,),
    )
    if sample is None:
        raise PermanentError(f"dialect sample {p.sample_id} not found")
    audio_path, reference, language, domain_terms, consent = sample
    if not consent:  # the table CHECK already forbids it; belt and braces (NFR-9)
        raise PermanentError(f"sample {p.sample_id} has no consent")
    profile_row = await _one(
        conn,
        "SELECT name, sample_rate, codec, pstn_bandpass, background_category, snr_db, "
        "packet_loss_pct, clipping FROM noise_profiles WHERE id = %s",
        (p.noise_profile_id,),
    )
    if profile_row is None:
        raise PermanentError(f"noise profile {p.noise_profile_id} not found")

    degraded: bytes | None = None
    for engine in p.engines:
        provider = engine_provider(engine)
        done = await _one(
            conn,
            "SELECT 1 FROM asr_results WHERE sample_id = %s AND noise_profile_id = %s "
            "AND engine = %s",
            (p.sample_id, p.noise_profile_id, engine),
        )
        if done is not None:
            continue
        if degraded is None:
            wav = (deps.data_dir / audio_path).read_bytes()
            degraded = degrade(
                wav, _profile(profile_row), clip_seed(p.sample_id, p.noise_profile_id)
            )
        stt = deps.stt_for(provider)
        t0 = time.monotonic()
        try:
            transcript = await stt.transcribe(degraded, language)
        except (SpeechPermanentError, SpeechConfigError) as exc:
            raise PermanentError(str(exc)) from exc
        latency_ms = round((time.monotonic() - t0) * 1000)
        await conn.execute(
            "INSERT INTO api_usage (provider, operation, units, unit_type, est_cost) "
            "VALUES (%s, %s, %s, 'audio_seconds', %s)",
            (
                provider.value,
                transcript.usage.operation,
                transcript.usage.audio_seconds or wav_seconds(degraded),
                transcript.usage.est_cost,
            ),
        )
        scores = score_clip(reference, transcript.text, domain_terms)

        async def sink(record: UsageRecord) -> None:
            await _record_llm_usage(conn, record)

        verdict = await intent_preserved(
            deps.llm_for(sink),
            reference=reference,
            hypothesis=transcript.text,
            language=language,
            identical=scores.ref_norm == scores.hyp_norm,
        )
        await conn.execute(
            "INSERT INTO asr_results (sample_id, noise_profile_id, engine, engine_model, "
            "hypothesis_text, ref_normalised, hyp_normalised, wer, cer, entity_total, "
            "entity_correct, intent_preserved, substitutions, latency_ms) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (sample_id, noise_profile_id, engine, engine_model) DO NOTHING",
            (
                p.sample_id,
                p.noise_profile_id,
                engine,
                transcript.model or "default",
                transcript.text,
                scores.ref_norm,
                scores.hyp_norm,
                scores.wer,
                scores.cer,
                scores.entity_total,
                scores.entity_correct,
                verdict,
                Jsonb([list(pair) for pair in scores.substitutions]),
                latency_ms,
            ),
        )
    await finalize_report_if_complete(conn, p.report_id, deps)
    return []


async def load_result_rows(
    conn: psycopg.AsyncConnection[Any],
    sample_ids: list[uuid.UUID],
    conditions: list[uuid.UUID],
    engines: list[str],
) -> tuple[list[ResultRow], dict[uuid.UUID, str]]:
    """The report's results as aggregation rows, plus noise profile names by id."""
    cur = await conn.execute(
        "SELECT DISTINCT ON (r.sample_id, r.noise_profile_id, r.engine) "
        "s.dialect_label, n.name, r.engine, s.speaker_id, r.ref_normalised, r.hyp_normalised, "
        "r.entity_total, r.entity_correct, r.intent_preserved, r.substitutions, s.domain_terms "
        "FROM asr_results r JOIN dialect_samples s ON s.id = r.sample_id "
        "JOIN noise_profiles n ON n.id = r.noise_profile_id "
        "WHERE r.sample_id = ANY(%s) AND r.noise_profile_id = ANY(%s) AND r.engine = ANY(%s) "
        "ORDER BY r.sample_id, r.noise_profile_id, r.engine, r.created_at DESC",
        (sample_ids, conditions, engines),
    )
    rows = [
        ResultRow(
            dialect=d,
            condition=c,
            engine=e,
            speaker_id=sp,
            ref_norm=rn,
            hyp_norm=hn,
            entity_total=et,
            entity_correct=ec,
            intent_preserved=ip,
            substitutions=[(a, b) for a, b in subs],
            domain_terms=terms,
        )
        for d, c, e, sp, rn, hn, et, ec, ip, subs, terms in await cur.fetchall()
    ]
    names_cur = await conn.execute(
        "SELECT id, name FROM noise_profiles WHERE id = ANY(%s)", (conditions,)
    )
    return rows, {i: n for i, n in await names_cur.fetchall()}


async def finalize_report_if_complete(
    conn: psycopg.AsyncConnection[Any], report_id: uuid.UUID, deps: DialectDeps
) -> bool:
    """Aggregate and freeze the report once every expected result exists (exactly once: the
    report row is locked, so concurrent consumers serialise and the second one sees it done)."""
    row = await _one(
        conn,
        "SELECT r.dataset_id, r.conditions, r.engines, r.aggregates, r.created_at, d.name "
        "FROM dialect_reports r JOIN dialect_datasets d ON d.id = r.dataset_id "
        "WHERE r.id = %s FOR UPDATE OF r",
        (report_id,),
    )
    if row is None:
        raise PermanentError(f"dialect report {report_id} not found")
    _, conditions, engines, stored, created_at, dataset_name = row
    meta = (stored or {}).get("_meta")
    if meta is None or meta.get("complete"):
        return False
    sample_ids = [uuid.UUID(s) for s in meta["sample_ids"]]
    have = await _one(
        conn,
        "SELECT count(*) FROM (SELECT DISTINCT sample_id, noise_profile_id, engine "
        "FROM asr_results "
        "WHERE sample_id = ANY(%s) AND noise_profile_id = ANY(%s) AND engine = ANY(%s)) t",
        (sample_ids, conditions, engines),
    )
    if have[0] < meta["expected_results"]:
        return False
    rows, names = await load_result_rows(conn, sample_ids, conditions, engines)
    result = aggregate(rows)
    condition_names = [names[c] for c in conditions]
    page = render_html(
        dataset_name=dataset_name,
        created_at=created_at,
        conditions=condition_names,
        engines=engines,
        aggregates=result.aggregates,
        top_errors_=result.top_errors,
        bias=result.bias_suggestions,
    )
    relative = f"dialect/reports/{report_id}.html"
    target = deps.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    stored_meta = {**meta, "complete": True, "completed_at": deps.now().isoformat()}
    await conn.execute(
        "UPDATE dialect_reports SET aggregates = %s, top_errors = %s, bias_suggestions = %s, "
        "html_path = %s WHERE id = %s",
        (
            Jsonb({"_meta": stored_meta, **result.aggregates}),
            Jsonb(result.top_errors),
            result.bias_suggestions,
            relative,
            report_id,
        ),
    )
    return True


def pcm_seconds(samples: np.ndarray, rate: int = 16000) -> float:
    return float(len(samples)) / rate
