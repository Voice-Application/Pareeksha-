"""One designer chat turn: build the fenced prompt, call the LLM, validate and clean the answer."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.client import LLMClient
from pareeksha.llm.prompts import prompt_hash, render_prompt
from pareeksha.schemas.designer import (
    DesignerChatRequest,
    DesignerChatResponse,
    DesignerDraft,
    ExistingPersona,
)

PROMPT = "designer_v1"
#: A normal draft (8 to 12 scenarios of about 230 tokens, plus agent, personas and noise ids) is
#: about 4 000 tokens; 5 000 leaves headroom and caps what one chat turn can cost.
MAX_OUTPUT_TOKENS = 5000


def draft_problems(
    draft: DesignerDraft, persona_ids: set[uuid.UUID], noise_ids: set[uuid.UUID]
) -> str | None:
    """Why the draft is unusable (sent back to the model once), or ``None``.

    Unknown persona / noise ids are not a problem by themselves (``prune_unknown`` drops them),
    unless nothing valid is left.
    """
    tools = {t.name for t in draft.agent.expected_tools}
    for s in draft.scenarios:
        for call in s.expected_tool_calls:
            name = call.get("name") if isinstance(call, dict) else None
            if name not in tools:
                return (
                    f"scenario '{s.title}' expects tool {name!r}, which agent.expected_tools does "
                    f"not declare (declared: {sorted(tools)}); add the tool or remove the call"
                )
    kept_personas = [
        p
        for p in draft.personas
        if not isinstance(p, ExistingPersona) or p.existing_id in persona_ids
    ]
    if not kept_personas:
        return "personas has no valid entry: existing_id must be an id from the persona library"
    if not any(n in noise_ids for n in draft.noise_profile_ids):
        return "noise_profile_ids has no valid entry: use ids from the noise profile library"
    return None


def prune_unknown(
    draft: DesignerDraft, persona_ids: set[uuid.UUID], noise_ids: set[uuid.UUID]
) -> tuple[DesignerDraft, int]:
    """Drop persona / noise ids that are not in the project; also the number dropped."""
    personas = [
        p
        for p in draft.personas
        if not isinstance(p, ExistingPersona) or p.existing_id in persona_ids
    ]
    noise = [n for n in draft.noise_profile_ids if n in noise_ids]
    dropped = (len(draft.personas) - len(personas)) + (len(draft.noise_profile_ids) - len(noise))
    if not dropped:
        return draft, 0
    return draft.model_copy(update={"personas": personas, "noise_profile_ids": noise}), dropped


def build_messages(
    request: DesignerChatRequest,
    personas: Sequence[dict[str, Any]],
    noise_profiles: Sequence[dict[str, Any]],
) -> list[ChatMessage]:
    """System prompt (rules + library + current draft) and the history, user turns fenced.

    The fence carries a random token, so pasted text cannot close it early.
    """
    fence = f"USER_INPUT_{uuid.uuid4().hex[:12]}"
    system = render_prompt(
        PROMPT,
        fence=fence,
        personas=list(personas),
        noise_profiles=list(noise_profiles),
        draft=request.draft.model_dump(mode="json") if request.draft else None,
    )
    messages = [ChatMessage(role="system", content=system)]
    for turn in request.messages:
        content = f"<<<{fence}\n{turn.content}\n{fence}>>>" if turn.role == "user" else turn.content
        messages.append(ChatMessage(role=turn.role, content=content))
    return messages


async def chat_turn(
    client: LLMClient,
    request: DesignerChatRequest,
    personas: Sequence[dict[str, Any]],
    noise_profiles: Sequence[dict[str, Any]],
) -> DesignerChatResponse:
    """Raises the client's ``JSONGenerationError`` if the answer is still unusable after the one
    repair retry, and its ``LLMError`` subclasses for provider failures."""
    persona_ids = {uuid.UUID(str(p["id"])) for p in personas}
    noise_ids = {uuid.UUID(str(n["id"])) for n in noise_profiles}

    def check(turn: DesignerChatResponse) -> str | None:
        if turn.ready and turn.draft is None:
            return "ready is true but draft is null"
        return draft_problems(turn.draft, persona_ids, noise_ids) if turn.draft else None

    result = await client.generate_json(
        purpose=LLMPurpose.DESIGNER,
        messages=build_messages(request, personas, noise_profiles),
        schema=DesignerChatResponse,
        prompt_hash=prompt_hash(PROMPT),
        max_output_tokens=MAX_OUTPUT_TOKENS,
        timeout_s=120.0,
        semantic_check=check,
    )
    turn = result.parsed
    reply = turn.reply
    draft = turn.draft
    if draft is not None:
        draft, dropped = prune_unknown(draft, persona_ids, noise_ids)
        if dropped:
            reply += (
                f"\n\n(Note: I removed {dropped} persona / noise profile reference(s) that are not "
                "in this project's library.)"
            )
    ready = bool(turn.ready and draft is not None and draft.agent.endpoint_url)
    return DesignerChatResponse(reply=reply, questions=turn.questions, draft=draft, ready=ready)
