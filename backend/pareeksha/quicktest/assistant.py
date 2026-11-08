"""The in-app assistant: explains the app and runs prompt tests from the chat.

One JSON-mode turn per request (stateless; the client sends the history). The model never
retypes a pasted prompt: it points at it (message number plus its first and last words) and
the server cuts the exact text out of the user's message, so what is tested is what was pasted.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.auth import Principal
from pareeksha.api.errors import ApiError
from pareeksha.llm.base import ChatMessage, LLMError, LLMPurpose
from pareeksha.llm.client import JSONGenerationError, LLMClient
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.prompts import prompt_hash, render_prompt
from pareeksha.quicktest import service
from pareeksha.schemas.quick_tests import (
    AssistantAction,
    AssistantReply,
    AssistantRequest,
    AssistantResponse,
    CostEstimate,
    QuickTestCreate,
    QuickTestPlan,
)

PROMPT = "assistant_v1"
#: Pages the assistant may send the user to (prefix match on the path).
PAGES = (
    "/",
    "/test",
    "/knowledge-bases",
    "/runs",
    "/agents",
    "/rag-lab",
    "/designer",
    "/scenarios",
    "/personas",
    "/noise-profiles",
    "/audits",
    "/regression",
    "/dialect",
    "/integrations",
    "/calibration",
    "/dlq",
    "/settings",
    "/calls",
)


def cut(messages: list[Any], source: Any) -> str | None:
    """The text a ``TextSource`` points at, copied from the user's own message (None if absent).

    Start / end markers are matched exactly, then ignoring case; a marker that is not found
    widens the cut to the start / end of the message, so nothing pasted is lost.
    """
    if source is None or source.message >= len(messages):
        return None
    msg = messages[source.message]
    if msg.role != "user":
        return None
    text: str = msg.content
    low = text.lower()
    start = 0
    if source.start:
        i = text.find(source.start)
        i = i if i >= 0 else low.find(source.start.lower())
        start = max(i, 0)
    end = len(text)
    if source.end:
        j = text.rfind(source.end)
        n = len(source.end)
        if j < 0:
            j = low.rfind(source.end.lower())
        if j >= start:
            end = j + n
    out = text[start:end].strip()
    return out or None


def safe_path(path: str) -> str | None:
    """``path`` when it is an in-app page the assistant may open, else None."""
    if not path.startswith("/") or path.startswith("//") or "\\" in path or ".." in path:
        return None
    bare = path.split("?", 1)[0]
    ok = any(bare == p or (p != "/" and bare.startswith(p + "/")) for p in PAGES)
    return path if ok else None


async def _context(
    session: AsyncSession, key: Principal, settings: LLMSettings, request: AssistantRequest
) -> dict[str, Any]:
    """What the assistant knows about the project: recent tests, documents, the key, the page."""
    tests = await service.list_tests(session, key.project_id, limit=5)
    current = None
    if request.quick_test_id is not None:
        row = await service.get_row(session, key.project_id, request.quick_test_id)
        if row is not None:
            out = await service.build_out(session, row)
            current = {
                "id": str(row.id),
                "name": row.name,
                "status": out.status,
                "rules_total": len(out.rules),
                "rules_broken": sum(1 for r in out.rules if r.status == "broken"),
                "broken": [
                    {"text": r.text, "quote": r.evidence[0].quote if r.evidence else ""}
                    for r in out.rules
                    if r.status == "broken"
                ][:6],
            }
    kbs = await service.setup_kbs(session, key.project_id)
    return {
        "tests": [t.model_dump(mode="json") for t in tests],
        "kbs": [k.model_dump(mode="json") for k in kbs],
        "current": current,
        "llm_ready": service.llm_ready(settings),
        "auto_run_limit": f"{service.auto_run_limit():.0f}",
        "page": request.page,
    }


def build_messages(request: AssistantRequest, ctx: dict[str, Any]) -> list[ChatMessage]:
    """System prompt plus the history; user turns fenced and numbered."""
    fence = f"USER_{uuid.uuid4().hex[:12]}"
    messages = [ChatMessage(role="system", content=render_prompt(PROMPT, fence=fence, **ctx))]
    for i, m in enumerate(request.messages):
        if m.role == "user":
            content = f"<<<{fence}\n[message {i}]\n{m.content}\n{fence}>>>"
        else:
            content = m.content
        messages.append(ChatMessage(role=m.role, content=content))
    return messages


async def chat(
    session: AsyncSession,
    key: Principal,
    settings: LLMSettings,
    client: LLMClient,
    request: AssistantRequest,
) -> AssistantResponse:
    """One assistant turn, and the action it asks for (start a test, improve one, open a page)."""
    ctx = await _context(session, key, settings, request)
    kb_ids = {k["id"] for k in ctx["kbs"]}
    test_ids = {t["id"] for t in ctx["tests"]} | (
        {ctx["current"]["id"]} if ctx["current"] else set()
    )

    def check(turn: AssistantReply) -> str | None:
        """Actions name known ids and point at a user message."""
        a = turn.action
        if a is None:
            return None
        if a.type == "start_quick_test":
            if a.prompt_from is None and not a.use_default_rag_prompt:
                return "start_quick_test needs prompt_from (or use_default_rag_prompt with kb_id)"
            if a.prompt_from is not None and cut(request.messages, a.prompt_from) is None:
                return "prompt_from.message must be the number of a user message"
            if a.kb_id is not None and str(a.kb_id) not in kb_ids:
                return f"kb_id must be one of {sorted(kb_ids)} or null"
            if a.use_default_rag_prompt and a.kb_id is None:
                return "use_default_rag_prompt needs a kb_id"
        if a.type == "improve_quick_test" and str(a.quick_test_id) not in test_ids:
            return f"quick_test_id must be one of {sorted(test_ids)}"
        return None

    result = await client.generate_json(
        purpose=LLMPurpose.DESIGNER,
        messages=build_messages(request, ctx),
        schema=AssistantReply,
        prompt_hash=prompt_hash(PROMPT),
        model=settings.caller_model,
        temperature=0.3,
        max_output_tokens=1500,
        timeout_s=90.0,
        semantic_check=check,
    )
    turn = result.parsed
    response = AssistantResponse(reply=turn.reply, suggestions=turn.suggestions[:3])
    action = turn.action
    if action is None:
        return response
    response.action = action.type
    try:
        if action.type == "open_page":
            response.open_path = safe_path(action.path)
        elif action.type == "start_quick_test":
            async with session.begin_nested():  # a failed start leaves no half-made rows
                await _start(session, key, settings, client, request, action, response)
        else:
            async with session.begin_nested():
                await _improve(session, key, settings, client, action, response)
    except ApiError as exc:
        _explain(exc, response)
    except JSONGenerationError:
        response.error = "invalid_output"
        response.reply += "\n\nThe AI model gave an unusable answer for that step; try again."
    except LLMError as exc:
        response.error = "upstream_error"
        response.reply += f"\n\nThe AI service failed ({type(exc).__name__}); please try again."
    return response


async def _start(
    session: AsyncSession,
    key: Principal,
    settings: LLMSettings,
    client: LLMClient,
    request: AssistantRequest,
    action: AssistantAction,
    response: AssistantResponse,
) -> None:
    """Start the test the assistant described (or leave it pending above the cost limit)."""
    prompt = (
        service.DEFAULT_RAG_PROMPT
        if action.use_default_rag_prompt
        else cut(request.messages, action.prompt_from)
    )
    details = cut(request.messages, action.user_details_from) or action.user_details
    body = QuickTestCreate(
        system_prompt=(prompt or "")[:60_000] or service.DEFAULT_RAG_PROMPT,
        user_details=(details or "")[:10_000],
        kb_id=action.kb_id,
        instructions=action.instructions,
    )
    try:
        created = await service.create_quick_test(session, key, settings, client, body)
    except ApiError as exc:
        if exc.code == "confirm_cost":
            response.pending = body.model_copy(
                update={"plan": QuickTestPlan.model_validate(exc.details["plan"])}
            )
            response.estimate = CostEstimate.model_validate(exc.details["estimate"])
            response.reply += f"\n\n{exc.message}"
            return
        raise
    response.quick_test_id = created.id


async def _improve(
    session: AsyncSession,
    key: Principal,
    settings: LLMSettings,
    client: LLMClient,
    action: AssistantAction,
    response: AssistantResponse,
) -> None:
    """Rewrite the test's prompt, and test the rewrite when asked."""
    assert action.quick_test_id is not None  # the semantic check guarantees it
    row = await service.require_row(session, key.project_id, action.quick_test_id)
    improvement = await service.improve(session, client, row, action.instructions)
    if action.retest:
        created = await service.retest(session, key, settings, row, improvement.improved_prompt)
        improvement.retest_id = created.id
        row.improvement = improvement.model_dump(mode="json")
        await session.flush()
        response.quick_test_id = created.id
    else:
        response.quick_test_id = row.id
    response.improvement = improvement


def _explain(exc: ApiError, response: AssistantResponse) -> None:
    """Put a failed action's reason into the reply instead of failing the whole turn."""
    response.error = exc.code
    response.reply += f"\n\nI could not do that: {exc.message}"
