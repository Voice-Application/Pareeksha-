"""Seed the database. Every step is get-or-create on a natural key and never overwrites a row, so
running it twice (or after a user edited a seeded row) changes nothing.

* personas: ``data/personas.yaml`` (docs/08-evaluation-rubric.md section 8), validated with
  ``PersonaCreate``;
* noise profiles: the 8 definitions in ``pareeksha.audio.profiles.BUILTIN_PROFILES``, so the
  profiles the DSP runs and the ones the API lists can never differ;
* rubric: ``data/rubric-2026-10-v1.yaml``, made the active rubric unless one is already active;
* the mock EMI agent and its scenarios;
* the demo API key (admin scope). ``PAREEKSHA_API_KEY`` in the environment pins the key (only its
  hash is stored); otherwise a key is generated and returned once, on the run that creates it.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.auth import DISPLAY_PREFIX_LEN, KEY_PREFIX, generate_api_key, hash_api_key
from pareeksha.audio.profiles import BUILTIN_PROFILES
from pareeksha.db.models import (
    Agents,
    ApiKeys,
    NoiseProfiles,
    Personas,
    Projects,
    RubricVersions,
    Scenarios,
)
from pareeksha.schemas.agents import AgentCreate
from pareeksha.schemas.personas import NoiseProfileCreate, PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

DATA_DIR = Path(__file__).parent / "data"
PROJECT_NAME = "Pareeksha"
DEMO_KEY_NAME = "demo"
DEMO_KEY_SCOPES = ["admin"]

#: What each shipped noise profile represents (docs/08-evaluation-rubric.md section 7).
NOISE_DESCRIPTIONS: dict[str, str] = {
    "clean_16k": "Baseline / app call",
    "pstn_8k_alaw": "Clean phone line",
    "pstn_office_babble_15db": "Caller at work",
    "pstn_street_10db": "Roadside",
    "pstn_market_5db": "Vegetable market",
    "mobile_bus_5db": "Inside a BMTC bus",
    "mobile_weak_signal": "Patchy signal, loud mic",
    "auto_rickshaw_0db": "Adversarial: auto-rickshaw at 0 dB",
}


@dataclass
class SeedResult:
    """What a seed run created; ``demo_key`` is set only when this run generated the key."""

    created: dict[str, int] = field(default_factory=dict)
    existing: dict[str, int] = field(default_factory=dict)
    project_id: str = ""
    demo_key: str | None = None

    def count(self, what: str, created: bool) -> None:
        bucket = self.created if created else self.existing
        bucket[what] = bucket.get(what, 0) + 1


def _load(name: str) -> Any:
    return yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))


def rubric_prompt_hash(
    version: str, pass_threshold: float, dimensions: list[dict[str, Any]]
) -> str:
    """sha256 of the canonical rubric definition (the judge template hash joins it in EVAL-03)."""
    canonical = json.dumps(
        {"version": version, "pass_threshold": pass_threshold, "dimensions": dimensions},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _project(session: AsyncSession) -> Projects:
    project = (
        await session.scalars(select(Projects).where(Projects.name == PROJECT_NAME).limit(1))
    ).one_or_none()
    if project is None:
        project = Projects(name=PROJECT_NAME)
        session.add(project)
        await session.flush()
    return project


async def _seed_personas(session: AsyncSession, project: Projects, out: SeedResult) -> None:
    for raw in _load("personas.yaml"):
        persona = PersonaCreate.model_validate(raw)
        found = await session.scalar(
            select(Personas.id).where(
                Personas.project_id == project.id, Personas.name == persona.name
            )
        )
        if found is None:
            session.add(Personas(project_id=project.id, is_seed=True, **persona.model_dump()))
        out.count("personas", found is None)


async def _seed_noise_profiles(session: AsyncSession, project: Projects, out: SeedResult) -> None:
    for name, line in BUILTIN_PROFILES.items():
        found = await session.scalar(
            select(NoiseProfiles.id).where(
                NoiseProfiles.project_id == project.id, NoiseProfiles.name == name
            )
        )
        if found is None:
            profile = NoiseProfileCreate(
                name=name,
                sample_rate=line.sample_rate,  # type: ignore[arg-type]
                codec=line.codec,  # type: ignore[arg-type]
                pstn_bandpass=line.pstn_bandpass,
                background_category=line.background,
                snr_db=line.snr_db,
                packet_loss_pct=line.packet_loss_pct,
                clipping=line.clipping,
                description=NOISE_DESCRIPTIONS.get(name, ""),
            )
            session.add(NoiseProfiles(project_id=project.id, **profile.model_dump()))
        out.count("noise_profiles", found is None)


async def _seed_rubric(session: AsyncSession, out: SeedResult) -> None:
    spec = _load("rubric-2026-10-v1.yaml")
    version: str = spec["version"]
    found = await session.scalar(select(RubricVersions.id).where(RubricVersions.version == version))
    if found is None:
        dimensions = [
            {**d, "anchors": {str(k): v for k, v in d["anchors"].items()}}
            for d in spec["dimensions"]
        ]
        has_active = await session.scalar(
            select(RubricVersions.id).where(RubricVersions.is_active.is_(True)).limit(1)
        )
        session.add(
            RubricVersions(
                version=version,
                dimensions=dimensions,
                pass_threshold=spec["pass_threshold"],
                prompt_hash=rubric_prompt_hash(version, spec["pass_threshold"], dimensions),
                is_active=has_active is None,
            )
        )
    out.count("rubric_versions", found is None)


async def _seed_agent(session: AsyncSession, project: Projects, out: SeedResult) -> None:
    agent = AgentCreate.model_validate(_load("agent_emi.yaml"))
    row = (
        await session.scalars(
            select(Agents).where(Agents.project_id == project.id, Agents.name == agent.name)
        )
    ).one_or_none()
    out.count("agents", row is None)
    if row is None:
        row = Agents(project_id=project.id, **agent.model_dump(mode="json"))
        session.add(row)
        await session.flush()
    for raw in _load("scenarios_emi.yaml"):
        scenario = ScenarioCreate.model_validate({**raw, "agent_id": row.id})
        found = await session.scalar(
            select(Scenarios.id).where(
                Scenarios.project_id == project.id,
                Scenarios.agent_id == row.id,
                Scenarios.title == scenario.title,
            )
        )
        if found is None:
            session.add(Scenarios(project_id=project.id, source="manual", **scenario.model_dump()))
        out.count("scenarios", found is None)


async def _seed_demo_key(session: AsyncSession, project: Projects, out: SeedResult) -> None:
    pinned = os.environ.get("PAREEKSHA_API_KEY", "").strip()
    if pinned:
        if not pinned.startswith(KEY_PREFIX) or len(pinned) < DISPLAY_PREFIX_LEN + 8:
            raise ValueError(f"PAREEKSHA_API_KEY must look like {KEY_PREFIX}<random>")
        key_hash = hash_api_key(pinned)
        found = await session.scalar(select(ApiKeys.id).where(ApiKeys.key_hash == key_hash))
        if found is None:
            session.add(
                ApiKeys(
                    project_id=project.id,
                    name=DEMO_KEY_NAME,
                    prefix=pinned[:DISPLAY_PREFIX_LEN],
                    key_hash=key_hash,
                    scopes=DEMO_KEY_SCOPES,
                )
            )
        out.count("api_keys", found is None)
        return
    found = await session.scalar(
        select(ApiKeys.id).where(
            ApiKeys.project_id == project.id,
            ApiKeys.name == DEMO_KEY_NAME,
            ApiKeys.revoked_at.is_(None),
        )
    )
    if found is None:
        key, prefix, key_hash = generate_api_key()
        session.add(
            ApiKeys(
                project_id=project.id,
                name=DEMO_KEY_NAME,
                prefix=prefix,
                key_hash=key_hash,
                scopes=DEMO_KEY_SCOPES,
            )
        )
        out.demo_key = key
    out.count("api_keys", found is None)


async def seed_database(factory: async_sessionmaker[AsyncSession]) -> SeedResult:
    """Seed everything in one transaction."""
    out = SeedResult()
    async with factory() as session, session.begin():
        project = await _project(session)
        out.project_id = str(project.id)
        await _seed_personas(session, project, out)
        await _seed_noise_profiles(session, project, out)
        await _seed_rubric(session, out)
        await _seed_agent(session, project, out)
        await _seed_demo_key(session, project, out)
    return out
