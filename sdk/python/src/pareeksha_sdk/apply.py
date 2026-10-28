"""``pareeksha apply``: upsert agent, scenarios, personas and noise profiles by name, and resolve
suites to ids. Applying the same file twice makes no write the second time (FR-DX-5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pareeksha_sdk.client import Pareeksha
from pareeksha_sdk.config import ProjectConfig, Suite
from pareeksha_sdk.errors import NotFoundError
from pareeksha_sdk.models import Agent, Named

Action = Literal["created", "updated", "unchanged"]


@dataclass
class ApplyEntry:
    kind: str
    name: str
    action: Action


@dataclass
class ApplyReport:
    entries: list[ApplyEntry] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return sum(1 for e in self.entries if e.action != "unchanged")

    def lines(self) -> list[str]:
        return [f"{e.action:<9} {e.kind}: {e.name}" for e in self.entries]


def _differs(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    return any(existing.get(key) != value for key, value in desired.items())


def apply_config(client: Pareeksha, config: ProjectConfig) -> ApplyReport:
    report = ApplyReport()
    agent = _apply_agent(client, config.agent, report)
    _apply_named(
        client,
        "scenario",
        "scenarios",
        "title",
        config.scenarios,
        report,
        extra={"agent_id": str(agent.id)},
        list_filters={"agent_id": str(agent.id)},
    )
    _apply_named(client, "persona", "personas", "name", config.personas, report)
    _apply_named(client, "noise profile", "noise_profiles", "name", config.noise_profiles, report)
    return report


def _apply_agent(client: Pareeksha, desired: dict[str, Any], report: ApplyReport) -> Agent:
    name = str(desired["name"])
    try:
        existing = client.agents.get_by_name(name)
    except NotFoundError:
        created = client.agents.create(desired)
        report.entries.append(ApplyEntry("agent", name, "created"))
        return created
    if _differs(existing.model_dump(), desired):
        updated = client.agents.update(existing.id, desired)
        report.entries.append(ApplyEntry("agent", name, "updated"))
        return updated
    report.entries.append(ApplyEntry("agent", name, "unchanged"))
    return existing


def _apply_named(
    client: Pareeksha,
    label: str,
    attr: str,
    key: str,
    items: list[dict[str, Any]],
    report: ApplyReport,
    *,
    extra: dict[str, Any] | None = None,
    list_filters: dict[str, Any] | None = None,
) -> None:
    if not items:
        return
    library = getattr(client, attr)
    existing_by_name = {
        (n.name if key == "name" else n.title): n for n in library.list(**(list_filters or {}))
    }
    for item in items:
        desired = {**item, **(extra or {})}
        current: Named | None = existing_by_name.get(str(item[key]))
        if current is None:
            library.create(desired)
            action: Action = "created"
        elif _differs(current.model_dump(), desired):
            library.update(current.id, desired)
            action = "updated"
        else:
            action = "unchanged"
        report.entries.append(ApplyEntry(label, str(item[key]), action))


@dataclass
class ResolvedSuite:
    agent: Agent
    scenario_ids: list[str]
    persona_ids: list[str]
    noise_profile_ids: list[str]


def resolve_suite(client: Pareeksha, agent_name: str, suite: Suite) -> ResolvedSuite:
    """Turn names and tags into ids. Empty persona / noise lists mean "all that exist"."""
    agent = client.agents.get_by_name(agent_name)
    scenarios: dict[str, Named] = {}
    if suite.scenarios.tags:
        for tag in suite.scenarios.tags:
            for s in client.scenarios.list(agent_id=str(agent.id), tag=tag):
                scenarios[str(s.id)] = s
    else:
        for s in client.scenarios.list(agent_id=str(agent.id)):
            scenarios[str(s.id)] = s
    if suite.scenarios.titles:
        known = {s.title: s for s in client.scenarios.list(agent_id=str(agent.id))}
        for title in suite.scenarios.titles:
            if title not in known:
                raise NotFoundError(f"scenario {title!r} not found")
            scenarios[str(known[title].id)] = known[title]
    if not scenarios:
        raise NotFoundError("no scenarios match the selection")
    return ResolvedSuite(
        agent,
        list(scenarios),
        _ids(client.personas.list(), suite.personas, "persona"),
        _ids(client.noise_profiles.list(), suite.noise_profiles, "noise profile"),
    )


def _ids(available: list[Named], wanted: list[str], kind: str) -> list[str]:
    if not wanted:
        if not available:
            raise NotFoundError(f"no {kind}s exist")
        return [str(n.id) for n in available]
    by_name = {n.name: n for n in available}
    missing = [w for w in wanted if w not in by_name]
    if missing:
        raise NotFoundError(f"{kind}(s) not found: {missing}")
    return [str(by_name[w].id) for w in wanted]
