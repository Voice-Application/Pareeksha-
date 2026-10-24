"""Scripted EMI-collections dialog (synthetic lender "Suraksha Finance"; no LLM, deterministic).

``Dialog.respond(text)`` maps what the agent's STT heard to the next agent turn. The five planted
bugs only change the behaviour described in :class:`mock_agent.bugs.Bug`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mock_agent.bugs import Bug

AMOUNT = "4,500"
AMOUNT_SPOKEN = {
    "en-IN": "four thousand five hundred rupees",
    "hi-IN": "चार हज़ार पाँच सौ रुपये",
    "kn-IN": "ನಾಲ್ಕು ಸಾವಿರದ ಐನೂರು ರೂಪಾಯಿ",
}
LANGS = ("en-IN", "hi-IN", "kn-IN")

DISCLOSURE = {
    "en-IN": "This call is being recorded for quality and compliance purposes.",
    "hi-IN": "गुणवत्ता और अनुपालन के लिए यह कॉल रिकॉर्ड की जा रही है।",
    "kn-IN": "ಗುಣಮಟ್ಟ ಮತ್ತು ಅನುಸರಣೆಗಾಗಿ ಈ ಕರೆಯನ್ನು ರೆಕಾರ್ಡ್ ಮಾಡಲಾಗುತ್ತಿದೆ.",
}
GREETING = {
    "en-IN": "Hello, this is Suraksha Finance. Am I speaking with the account holder?",
    "hi-IN": "नमस्ते, मैं सुरक्षा फाइनेंस से बोल रही हूँ। क्या मैं खाताधारक से बात कर रही हूँ?",
    "kn-IN": "ನಮಸ್ಕಾರ, ಇದು ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್. ನಾನು ಖಾತೆದಾರರ ಜೊತೆ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆಯೇ?",
}
ASK_PAY = {
    "en-IN": f"Thank you. Your EMI of rupees {AMOUNT} is overdue by twelve days. When can you pay?",
    "hi-IN": f"धन्यवाद। आपकी {AMOUNT} रुपये की ईएमआई बारह दिन से बकाया है। आप कब भुगतान कर सकते हैं?",
    "kn-IN": f"ಧನ್ಯವಾದ. ನಿಮ್ಮ {AMOUNT} ರೂಪಾಯಿ ಇಎಂಐ ಹನ್ನೆರಡು ದಿನದಿಂದ ಬಾಕಿ ಇದೆ. ಯಾವಾಗ ಪಾವತಿಸಬಹುದು?",
}
CONFIRM = {
    "en-IN": f"Just to confirm, you will pay {AMOUNT_SPOKEN['en-IN']} on that date. Is that right?",
    "hi-IN": f"पुष्टि के लिए, आप उस तारीख को {AMOUNT_SPOKEN['hi-IN']} का भुगतान करेंगे। क्या यह सही है?",
    "kn-IN": f"ದೃಢೀಕರಿಸಲು, ನೀವು ಆ ದಿನ {AMOUNT_SPOKEN['kn-IN']} ಪಾವತಿಸುತ್ತೀರಿ. ಸರಿಯೇ?",
}
CLOSING = {
    "en-IN": "Thank you, I have noted your payment promise. Have a good day. Goodbye.",
    "hi-IN": "धन्यवाद, मैंने आपका भुगतान वादा दर्ज कर लिया है। आपका दिन शुभ हो। नमस्ते।",
    "kn-IN": "ಧನ್ಯವಾದ, ನಿಮ್ಮ ಪಾವತಿ ಭರವಸೆಯನ್ನು ದಾಖಲಿಸಿದ್ದೇನೆ. ಶುಭ ದಿನ. ನಮಸ್ಕಾರ.",
}
REPROMPT = {
    "en-IN": "Sorry, I did not catch that. Could you please repeat?",
    "hi-IN": "क्षमा करें, मैं समझ नहीं पाई। कृपया दोहराइए।",
    "kn-IN": "ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಹೇಳಿ.",
}
WAIVER_REFUSE = {
    "en-IN": "I am not able to waive the late fee myself. I can ask my supervisor to review it.",
    "hi-IN": "मैं लेट फीस खुद माफ़ नहीं कर सकती। मैं अपने सुपरवाइज़र से समीक्षा के लिए कह सकती हूँ।",
    "kn-IN": "ನಾನು ತಡ ಶುಲ್ಕವನ್ನು ನಾನೇ ಮನ್ನಾ ಮಾಡಲಾಗುವುದಿಲ್ಲ. ನನ್ನ ಮೇಲಧಿಕಾರಿಯ ಪರಿಶೀಲನೆಗೆ ಕೇಳಬಹುದು.",
}
# Bug 5: the agent has no authority to waive anything, yet promises it.
WAIVER_PROMISE = {
    "en-IN": "Sure, I will waive the entire late fee for you, no problem at all.",
    "hi-IN": "ज़रूर, मैं आपकी पूरी लेट फीस माफ़ कर दूँगी, कोई समस्या नहीं।",
    "kn-IN": "ಖಂಡಿತ, ನಾನು ನಿಮ್ಮ ಸಂಪೂರ್ಣ ತಡ ಶುಲ್ಕವನ್ನು ಮನ್ನಾ ಮಾಡುತ್ತೇನೆ.",
}

_WAIVER_RE = re.compile(
    r"waive|waiver|late fee|late charge|penalty|penalt|"
    r"माफ|लेट फ|पेनल्टी|जुर्माना|"
    r"ಮನ್ನಾ|ದಂಡ|ಪೆನಾಲ್ಟಿ|ತಡ ಶುಲ್ಕ|ಲೇಟ್ ಫೀ",
    re.IGNORECASE,
)


def detect_language(text: str, fallback: str) -> str:
    """Pick the reply language from the script of the caller's words."""
    if re.search(r"[ಀ-೿]", text):
        return "kn-IN"
    if re.search(r"[ऀ-ॿ]", text):
        return "hi-IN"
    return fallback


@dataclass(frozen=True)
class Reply:
    """One agent turn: what to say, its TTS language, tools called, and whether the call ends."""

    text: str
    language: str
    tool_calls: tuple[tuple[str, dict[str, Any], dict[str, Any]], ...] = ()
    end_call: bool = False
    #: Dialog stage after the agent turn (for tests and evidence).
    stage: str = ""


@dataclass
class Dialog:
    language: str = "en-IN"
    bugs: frozenset[Bug] = frozenset()
    stage: str = "greet"
    reprompts: int = 0
    promised: bool = False
    history: list[str] = field(default_factory=list)

    def _speak_lang(self) -> str:
        """Bug 3: Kannada callers get English replies."""
        if self.language == "kn-IN" and Bug.ENGLISH_TO_KANNADA in self.bugs:
            return "en-IN"
        return self.language

    def opening(self) -> Reply:
        lang = self._speak_lang()
        parts = [] if Bug.NO_DISCLOSURE in self.bugs else [DISCLOSURE[lang]]
        parts.append(GREETING[lang])
        self.stage = "identify"
        return Reply(" ".join(parts), lang, stage=self.stage)

    def _finish(self, lang: str) -> Reply:
        self.stage = "done"
        self.promised = True
        tool = (
            "record_promise_to_pay",
            {"amount_inr": 4500, "when": "caller_stated_date"},
            {"status": "recorded"},
        )
        return Reply(CLOSING[lang], lang, (tool,), end_call=True, stage=self.stage)

    def respond(self, heard: str) -> Reply:
        text = heard.strip()
        self.history.append(text)
        if not text:
            self.reprompts += 1
            if self.reprompts > 2:
                self.stage = "done"
                return Reply(REPROMPT[self._speak_lang()], self._speak_lang(), end_call=True)
            lang = self._speak_lang()
            return Reply(REPROMPT[lang], lang, stage=self.stage)
        self.language = detect_language(text, self.language)
        lang = self._speak_lang()

        if _WAIVER_RE.search(text) and self.stage in ("ask_pay", "identify", "confirm"):
            if Bug.FALSE_WAIVER in self.bugs:
                return Reply(WAIVER_PROMISE[lang], lang, stage=self.stage)
            tool = (
                "escalate_waiver_request",
                {"reason": "caller_asked_late_fee_waiver"},
                {"ok": True},
            )
            return Reply(WAIVER_REFUSE[lang], lang, (tool,), stage=self.stage)

        if self.stage == "identify":
            self.stage = "ask_pay"
            return Reply(ASK_PAY[lang], lang, stage=self.stage)
        if self.stage == "ask_pay":
            if Bug.NO_AMOUNT_CONFIRM in self.bugs:
                return self._finish(lang)
            self.stage = "confirm"
            return Reply(CONFIRM[lang], lang, stage=self.stage)
        if self.stage == "confirm":
            return self._finish(lang)
        return Reply(CLOSING[lang], lang, end_call=True, stage="done")
