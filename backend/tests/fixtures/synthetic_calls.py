"""Synthetic EMI-reminder calls for evaluator tests and the EVAL-03 acceptance run.

All data is invented (no real people, numbers or voices).
"""

from __future__ import annotations

import uuid

from pareeksha.evaluation.evaluator import CallSnapshot
from pareeksha.evaluation.judge import AgentInfo
from pareeksha.evaluation.types import Disclosure, ForbiddenPhrase, ToolCall, Turn
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

AGENT = AgentInfo(
    name="Shree Finance EMI Reminder Bot",
    description=(
        "Calls borrowers about an EMI due date, states the correct amount, and records a "
        "promise-to-pay (date and amount) with the record_ptp tool. Must say the call is recorded."
    ),
    mandatory_disclosures=(
        Disclosure(id="recorded", text="This call is recorded", within_turns=1),
    ),
    forbidden_phrases=(ForbiddenPhrase(id="threat", text="we will send recovery agents"),),
)
PERSONA = PersonaCreate(
    name="Rohit, millennial",
    language="hi-IN",
    code_mix_style="heavy",
    voice_id="Shubham",
    emotion="neutral",
)
SCENARIO = ScenarioCreate(
    title="Promise to pay on Friday",
    caller_goal="Confirm the EMI amount and promise to pay it on Friday",
    fixtures={"emi_amount": 4200, "due_date": "Friday"},
    success_criteria="Agent states 4200 and records a promise to pay 4200 on Friday",
    must_say=["This call is recorded"],
    expected_tool_calls=[{"name": "record_ptp", "args": {"amount": 4200, "date": "Friday"}}],
)

CALL_ID_WRONG_AMOUNT = uuid.UUID("11111111-1111-4111-8111-111111111111")
CALL_ID_CLEAN = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _turns(rows: list[tuple[str, str, str | None]]) -> list[Turn]:
    out: list[Turn] = []
    t = 0
    for i, (speaker, text, said) in enumerate(rows):
        dur = 2500 if speaker == "agent" else 1500
        out.append(
            Turn(
                idx=i,
                speaker=speaker,
                start_ms=t + 600,
                end_ms=t + 600 + dur,
                text=text,
                text_masked=text,
                ground_truth_text=said if speaker == "caller" else None,
                agent_heard_text=text if speaker == "caller" else None,
                language_detected="hi-IN",
            )
        )
        t += 600 + dur
    return out


def wrong_amount_call() -> CallSnapshot:
    """Planted bug: the agent states and records 4,500 instead of 4,200 and never discloses
    that the call is recorded. The caller even objects once."""
    turns = _turns(
        [
            (
                "agent",
                "Namaste, Shree Finance se baat kar rahe hain, aapki EMI ke baare mein.",
                None,
            ),
            ("caller", "Haan boliye.", "Haan boliye."),
            ("agent", "Aapki EMI rupees 4,500 hai, jo Friday ko due hai.", None),
            ("caller", "Mera EMI toh 4200 hai na? Mera number 9876543210 hai.", None),
            ("agent", "Nahi sir, 4,500 sahi hai. Kya main 4,500 ka promise record kar doon?", None),
            ("caller", "Theek hai, Friday ko pay kar dunga.", None),
            ("agent", "Dhanyavaad, record kar liya.", None),
        ]
    )
    return CallSnapshot(
        call_id=CALL_ID_WRONG_AMOUNT,
        agent=AGENT,
        turns=turns,
        language="hi-IN",
        scenario=SCENARIO,
        persona=PERSONA,
        tool_calls=[ToolCall("record_ptp", {"amount": 4500, "date": "Friday"}, 6)],
        expected_language="hi-IN",
        allowed_languages=("hi-IN", "en-IN"),
        expected_tool_calls=SCENARIO.expected_tool_calls,
        expected_amounts={"emi_amount": 4200},
    )


def clean_call() -> CallSnapshot:
    turns = _turns(
        [
            ("agent", "Namaste, Shree Finance se bol rahe hain. This call is recorded.", None),
            ("caller", "Haan boliye.", None),
            (
                "agent",
                "Aapki EMI rupees 4,200 hai, jo Friday ko due hai. Kya aap Friday ko pay karenge?",
                None,
            ),
            ("caller", "Haan, Friday ko pay kar dunga.", None),
            ("agent", "Dhanyavaad. Maine Friday ko 4,200 ka promise record kar liya hai.", None),
        ]
    )
    return CallSnapshot(
        call_id=CALL_ID_CLEAN,
        agent=AGENT,
        turns=turns,
        language="hi-IN",
        scenario=SCENARIO,
        persona=PERSONA,
        tool_calls=[ToolCall("record_ptp", {"amount": 4200, "date": "Friday"}, 4)],
        expected_language="hi-IN",
        allowed_languages=("hi-IN", "en-IN"),
        expected_tool_calls=SCENARIO.expected_tool_calls,
        expected_amounts={"emi_amount": 4200},
    )
