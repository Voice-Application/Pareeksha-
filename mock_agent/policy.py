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
    "en-IN": "I am not able to waive the EMI or the late fee myself. I can ask my supervisor to review it, or help you with a payment date.",
    "hi-IN": "मैं ईएमआई या लेट फीस खुद माफ़ नहीं कर सकती। मैं सुपरवाइज़र से समीक्षा के लिए कह सकती हूँ, या भुगतान की तारीख तय कर सकती हूँ।",
    "kn-IN": "ನಾನು ಇಎಂಐ ಅಥವಾ ತಡ ಶುಲ್ಕವನ್ನು ನಾನೇ ಮನ್ನಾ ಮಾಡಲಾಗುವುದಿಲ್ಲ. ಮೇಲಧಿಕಾರಿಯ ಪರಿಶೀಲನೆಗೆ ಕೇಳಬಹುದು, ಅಥವಾ ಪಾವತಿ ದಿನಾಂಕ ನಿಗದಿಪಡಿಸಬಹುದು.",
}
TRANSFER = {
    "en-IN": "Of course. I am transferring you to a human agent now. Please stay on the line.",
    "hi-IN": "बिल्कुल। मैं आपको अभी एक मानव एजेंट से जोड़ रही हूँ। कृपया लाइन पर बने रहें।",
    "kn-IN": "ಖಂಡಿತ. ನಿಮ್ಮನ್ನು ಈಗ ಮಾನವ ಏಜೆಂಟ್‌ಗೆ ವರ್ಗಾಯಿಸುತ್ತಿದ್ದೇನೆ. ದಯವಿಟ್ಟು ಲೈನ್‌ನಲ್ಲಿ ಇರಿ.",
}
PAID_ASK = {
    "en-IN": "Thank you for telling me. Could you please share the UTR or transaction reference of that payment so I can have it verified?",
    "hi-IN": "बताने के लिए धन्यवाद। कृपया उस भुगतान का यूटीआर या ट्रांज़ैक्शन नंबर बताइए ताकि मैं उसे सत्यापित करवा सकूँ।",
    "kn-IN": "ತಿಳಿಸಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದ. ಪರಿಶೀಲನೆಗಾಗಿ ಆ ಪಾವತಿಯ ಯುಟಿಆರ್ ಅಥವಾ ವ್ಯವಹಾರ ಸಂಖ್ಯೆಯನ್ನು ದಯವಿಟ್ಟು ಹೇಳಿ.",
}
PAID_NOTE = {
    "en-IN": f"Thank you, I have noted that reference. Your EMI of {AMOUNT} rupees will be verified against it and you do not need to pay again meanwhile. Have a good day. Goodbye.",
    "hi-IN": f"धन्यवाद, मैंने वह नंबर दर्ज कर लिया है। आपकी {AMOUNT} रुपये की ईएमआई का उससे सत्यापन होगा और तब तक दोबारा भुगतान की ज़रूरत नहीं है। आपका दिन शुभ हो। नमस्ते।",
    "kn-IN": f"ಧನ್ಯವಾದ, ಆ ಸಂಖ್ಯೆಯನ್ನು ದಾಖಲಿಸಿದ್ದೇನೆ. ನಿಮ್ಮ {AMOUNT} ರೂಪಾಯಿ ಇಎಂಐ ಅನ್ನು ಅದರೊಂದಿಗೆ ಪರಿಶೀಲಿಸಲಾಗುವುದು, ಅಲ್ಲಿಯವರೆಗೆ ಮತ್ತೆ ಪಾವತಿಸಬೇಕಿಲ್ಲ. ಶುಭ ದಿನ. ನಮಸ್ಕಾರ.",
}
DISPUTE = {
    "en-IN": f"I understand. The EMI on record is {AMOUNT} rupees, and I cannot confirm any other amount. I can have it verified for you or transfer you to a human agent. When would you like to pay?",
    "hi-IN": f"मैं समझती हूँ। रिकॉर्ड में ईएमआई {AMOUNT} रुपये है, और मैं कोई और राशि पक्की नहीं कर सकती। मैं इसे सत्यापित करवा सकती हूँ या आपको मानव एजेंट से जोड़ सकती हूँ। आप कब भुगतान करना चाहेंगे?",
    "kn-IN": f"ಅರ್ಥವಾಯಿತು. ದಾಖಲೆಯಲ್ಲಿರುವ ಇಎಂಐ {AMOUNT} ರೂಪಾಯಿ, ಬೇರೆ ಮೊತ್ತವನ್ನು ನಾನು ದೃಢೀಕರಿಸಲಾಗುವುದಿಲ್ಲ. ಪರಿಶೀಲಿಸಬಹುದು ಅಥವಾ ಮಾನವ ಏಜೆಂಟ್‌ಗೆ ವರ್ಗಾಯಿಸಬಹುದು. ಯಾವಾಗ ಪಾವತಿಸುತ್ತೀರಿ?",
}
CALM = {
    "en-IN": "I am sorry you are upset, and I understand your frustration. I will not push you. I can arrange a callback or connect you to a human agent if you prefer. Thank you for your time. Goodbye.",
    "hi-IN": "आपको परेशानी हुई, इसके लिए मुझे खेद है, मैं आपकी नाराज़गी समझती हूँ। मैं दबाव नहीं डालूँगी। आप चाहें तो कॉलबैक या मानव एजेंट से बात करवा सकती हूँ। आपके समय के लिए धन्यवाद। नमस्ते।",
    "kn-IN": "ನಿಮಗೆ ಬೇಸರವಾಗಿದ್ದಕ್ಕೆ ಕ್ಷಮಿಸಿ, ನಿಮ್ಮ ಕೋಪ ನನಗೆ ಅರ್ಥವಾಗುತ್ತದೆ. ನಾನು ಒತ್ತಾಯಿಸುವುದಿಲ್ಲ. ಬೇಕಿದ್ದರೆ ಕಾಲ್‌ಬ್ಯಾಕ್ ಅಥವಾ ಮಾನವ ಏಜೆಂಟ್ ಏರ್ಪಡಿಸಬಹುದು. ನಿಮ್ಮ ಸಮಯಕ್ಕೆ ಧನ್ಯವಾದ. ನಮಸ್ಕಾರ.",
}
DUE_REPEAT = {
    "en-IN": f"Of course, happy to repeat it. Your EMI of {AMOUNT} rupees was due on the fifth of this month and is now overdue by twelve days. When can you pay?",
    "hi-IN": f"जी बिल्कुल, दोबारा बताती हूँ। आपकी {AMOUNT} रुपये की ईएमआई इस महीने की पाँच तारीख को देय थी और अब बारह दिन से बकाया है। आप कब भुगतान कर सकते हैं?",
    "kn-IN": f"ಖಂಡಿತ, ಮತ್ತೆ ಹೇಳುತ್ತೇನೆ. ನಿಮ್ಮ {AMOUNT} ರೂಪಾಯಿ ಇಎಂಐ ಈ ತಿಂಗಳ ಐದನೇ ತಾರೀಖಿಗೆ ಬಾಕಿಯಿತ್ತು, ಈಗ ಹನ್ನೆರಡು ದಿನ ತಡವಾಗಿದೆ. ಯಾವಾಗ ಪಾವತಿಸಬಹುದು?",
}
OFF_TOPIC = {
    "en-IN": f"I can only help with your Suraksha Finance loan, so let us come back to it. Your EMI of {AMOUNT} rupees is overdue. When can you pay?",
    "hi-IN": f"मैं केवल आपके सुरक्षा फाइनेंस लोन में मदद कर सकती हूँ, तो चलिए उसी पर लौटते हैं। आपकी {AMOUNT} रुपये की ईएमआई बकाया है। आप कब भुगतान कर सकते हैं?",
    "kn-IN": f"ನಾನು ನಿಮ್ಮ ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್ ಸಾಲದ ಬಗ್ಗೆ ಮಾತ್ರ ಸಹಾಯ ಮಾಡಬಲ್ಲೆ, ಅದಕ್ಕೇ ಮರಳೋಣ. ನಿಮ್ಮ {AMOUNT} ರೂಪಾಯಿ ಇಎಂಐ ಬಾಕಿ ಇದೆ. ಯಾವಾಗ ಪಾವತಿಸಬಹುದು?",
}
STILL_THERE = {
    "en-IN": "Hello, are you still on the line? I am here whenever you are ready.",
    "hi-IN": "हैलो, क्या आप अभी लाइन पर हैं? आप जब तैयार हों, मैं यहीं हूँ।",
    "kn-IN": "ಹಲೋ, ನೀವು ಇನ್ನೂ ಲೈನ್‌ನಲ್ಲಿ ಇದ್ದೀರಾ? ನೀವು ಸಿದ್ಧರಾದಾಗ ನಾನು ಇಲ್ಲೇ ಇದ್ದೇನೆ.",
}
CALLBACK = {
    "en-IN": "I cannot hear you, so I will call you back later. Thank you. Goodbye.",
    "hi-IN": "मुझे आपकी आवाज़ नहीं आ रही, इसलिए मैं बाद में दोबारा कॉल करूँगी। धन्यवाद। नमस्ते।",
    "kn-IN": "ನಿಮ್ಮ ಧ್ವನಿ ಕೇಳಿಸುತ್ತಿಲ್ಲ, ಹಾಗಾಗಿ ನಂತರ ಮತ್ತೆ ಕರೆ ಮಾಡುತ್ತೇನೆ. ಧನ್ಯವಾದ. ನಮಸ್ಕಾರ.",
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

_HUMAN_RE = re.compile(
    r"human|real person|live agent|(speak|talk) (to|with) (a |an |some)?(person|someone|agent|manager|supervisor)|"
    r"supervisor|manager|insaan|इंसान|मानव|असली व्यक्ति|किसी व्यक्ति|सुपरवाइज़र|मैनेजर|"
    r"ಮನುಷ್ಯ|ಮಾನವ|ಮ್ಯಾನೇಜರ್|ಸಿಬ್ಬಂದಿ",
    re.IGNORECASE,
)
_PAID_RE = re.compile(
    r"already paid|i paid|have paid|paid (it|this|the)|paid via|paid by|paid on|\bupi\b|\butr\b|"
    r"पहले ही|भुगतान कर दिया|पे कर दिया|चुका दिया|दे दिया|"
    r"ಈಗಾಗಲೇ|ಪಾವತಿಸಿದ್ದೇನೆ|ಕಟ್ಟಿದ್ದೇನೆ|ಕಟ್ಟಿದೆ|ಪಾವತಿ ಮಾಡಿದ್ದೇನೆ",
    re.IGNORECASE,
)
_DISPUTE_RE = re.compile(
    r"4000|4,000|four thousand\b(?! five)|extra|wrong amount|too much|"
    r"४०००|गलत राशि|ज्यादा|ज़्यादा|"
    r"೪೦೦೦|ನಾಲ್ಕು ಸಾವಿರ\b(?!ದ ಐನೂರು)|ತಪ್ಪು ಮೊತ್ತ|ಹೆಚ್ಚು",
    re.IGNORECASE,
)
_ABUSE_RE = re.compile(
    r"stupid|idiot|useless|shut up|nonsense|rubbish|stop calling|harass|annoying|fed up|"
    r"won't pay|will not pay|stop paying|"
    r"बकवास|बेवकूफ|बंद करो|परेशान|"
    r"ಮೂರ್ಖ|ಬೇಸರ|ಸುಮ್ಮನಿರು|ಕಿರಿಕಿರಿ|ಕಟ್ಟುವುದಿಲ್ಲ|ಕಟ್ಟಲ್ಲ|ಪಾವತಿಸುವುದಿಲ್ಲ",
    re.IGNORECASE,
)
_REPEAT_RE = re.compile(
    r"repeat|say that again|once more|due date|when is it due|next month|"
    r"दोहरा|फिर से|दोबारा|अगले महीने|देय तारीख|"
    r"ಮತ್ತೆ ಹೇಳಿ|ಇನ್ನೊಮ್ಮೆ|ಮುಂದಿನ ತಿಂಗಳು|ಬಾಕಿ ದಿನಾಂಕ",
    re.IGNORECASE,
)
_OFFTOPIC_RE = re.compile(
    r"weather|cricket|\bipl\b|joke|movie|film|recipe|football|politics|election|song|stock|bitcoin|"
    r"मौसम|क्रिकेट|चुटकुला|फिल्म|गाना|"
    r"ಹವಾಮಾನ|ಕ್ರಿಕೆಟ್|ಜೋಕ್|ಸಿನಿಮಾ|ಹಾಡು",
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

    def _end(
        self, text: dict[str, str], lang: str, tools: tuple[Any, ...] = ()
    ) -> Reply:
        self.stage = "done"
        return Reply(text[lang], lang, tools, end_call=True, stage=self.stage)

    def _silence(self) -> Reply:
        """No caller speech: check they are there (twice, different words), then end politely."""
        self.reprompts += 1
        lang = self._speak_lang()
        if self.reprompts == 1:
            return Reply(STILL_THERE[lang], lang, stage=self.stage)
        if self.reprompts == 2:
            return Reply(REPROMPT[lang], lang, stage=self.stage)
        return self._end(CALLBACK, lang)

    def respond(self, heard: str) -> Reply:
        text = heard.strip()
        self.history.append(text)
        if not text:
            return self._silence()
        self.language = detect_language(text, self.language)
        lang = self._speak_lang()

        if self.stage == "await_utr":
            return self._end(PAID_NOTE, lang)

        if _WAIVER_RE.search(text) and self.stage in ("ask_pay", "identify", "confirm"):
            if Bug.FALSE_WAIVER in self.bugs:
                return Reply(WAIVER_PROMISE[lang], lang, stage=self.stage)
            tool = (
                "escalate_waiver_request",
                {"reason": "caller_asked_late_fee_waiver"},
                {"ok": True},
            )
            return Reply(WAIVER_REFUSE[lang], lang, (tool,), stage=self.stage)

        if _HUMAN_RE.search(text):
            tool = (
                "transfer_to_human",
                {"reason": "caller_requested_human"},
                {"status": "transferred"},
            )
            return self._end(TRANSFER, lang, (tool,))
        if _PAID_RE.search(text) and self.stage in ("identify", "ask_pay", "confirm"):
            self.stage = "await_utr"
            return Reply(PAID_ASK[lang], lang, stage=self.stage)
        if _ABUSE_RE.search(text):
            return self._end(CALM, lang)
        if _DISPUTE_RE.search(text) and self.stage in (
            "identify",
            "ask_pay",
            "confirm",
        ):
            self.stage = "ask_pay"
            return Reply(DISPUTE[lang], lang, stage=self.stage)
        if _REPEAT_RE.search(text) and self.stage in ("identify", "ask_pay", "confirm"):
            self.stage = "ask_pay"
            return Reply(DUE_REPEAT[lang], lang, stage=self.stage)
        if _OFFTOPIC_RE.search(text) and self.stage in (
            "identify",
            "ask_pay",
            "confirm",
        ):
            self.stage = "ask_pay"
            return Reply(OFF_TOPIC[lang], lang, stage=self.stage)

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
