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
    r"human agent|live agent|real human|"
    r"(speak|talk|connect|transfer|put|get|give|want|need)\b.{0,30}\b(human|person|someone|agent|supervisor|manager)|"
    r"\b(supervisor|manager)\b|insaan|इंसान से|मानव एजेंट|सुपरवाइज़र|मैनेजर|"
    r"ಮನುಷ್ಯರ|ಮಾನವ ಏಜೆಂಟ್|ಮ್ಯಾನೇಜರ್|ಸಿಬ್ಬಂದಿ",
    re.IGNORECASE,
)
_PAID_RE = re.compile(
    r"already paid|i paid|have paid|paid (it|this|the)|paid via|paid by|paid on|\bupi\b|\butr\b|"
    r"भुगतान कर दिया|पे कर दिया|चुका दिया|पेमेंट कर दिया|"
    r"ಪಾವತಿಸಿದ್ದೇನೆ|ಕಟ್ಟಿದ್ದೇನೆ|ಕಟ್ಟಿದೆ|ಪಾವತಿ ಮಾಡಿದ್ದೇನೆ|ಪೇಮೆಂಟ್ ಮಾಡಿದ್ದೇನೆ",
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
    r"repeat|say that again|due date|when is it due|next month|"
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

CONFIRM_WHEN = {
    "en-IN": f"Just to confirm, you will pay {AMOUNT_SPOKEN['en-IN']} on {{when}}. Is that right?",
    "hi-IN": f"पुष्टि के लिए, आप {{when}} को {AMOUNT_SPOKEN['hi-IN']} का भुगतान करेंगे। क्या यह सही है?",
    "kn-IN": f"ದೃಢೀಕರಿಸಲು, ನೀವು {{when}} ಅಂದು {AMOUNT_SPOKEN['kn-IN']} ಪಾವತಿಸುತ್ತೀರಿ. ಸರಿಯೇ?",
}
CLOSING_WHEN = {
    "en-IN": f"Thank you, I have noted your promise to pay {AMOUNT_SPOKEN['en-IN']} on {{when}}. Have a good day. Goodbye.",
    "hi-IN": f"धन्यवाद, मैंने {{when}} को {AMOUNT_SPOKEN['hi-IN']} के भुगतान का आपका वादा दर्ज कर लिया है। आपका दिन शुभ हो। नमस्ते।",
    "kn-IN": f"ಧನ್ಯವಾದ, {{when}} ಅಂದು {AMOUNT_SPOKEN['kn-IN']} ಪಾವತಿಸುವ ನಿಮ್ಮ ಭರವಸೆಯನ್ನು ದಾಖಲಿಸಿದ್ದೇನೆ. ಶುಭ ದಿನ. ನಮಸ್ಕಾರ.",
}
ASK_WHEN = {
    "en-IN": "Which date would you be able to pay on?",
    "hi-IN": "आप किस तारीख को भुगतान कर पाएँगे?",
    "kn-IN": "ನೀವು ಯಾವ ದಿನಾಂಕದಂದು ಪಾವತಿಸಬಹುದು?",
}
CALL_REASON = {
    "en-IN": f"I am calling from Suraksha Finance about your EMI of rupees {AMOUNT}, which is overdue by twelve days. When can you pay it?",
    "hi-IN": f"मैं सुरक्षा फाइनेंस से आपकी {AMOUNT} रुपये की ईएमआई के बारे में बोल रही हूँ, जो बारह दिन से बकाया है। आप कब भुगतान कर सकते हैं?",
    "kn-IN": f"ನಾನು ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್‌ನಿಂದ ನಿಮ್ಮ {AMOUNT} ರೂಪಾಯಿ ಇಎಂಐ ಬಗ್ಗೆ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ, ಇದು ಹನ್ನೆರಡು ದಿನದಿಂದ ಬಾಕಿ ಇದೆ. ಯಾವಾಗ ಪಾವತಿಸಬಹುದು?",
}
LOAN_ID = {
    "en-IN": "For your security I cannot read account details aloud on this call. I can transfer you to a human agent who can verify the loan ID and the EMI amount with you.",
    "hi-IN": "आपकी सुरक्षा के लिए मैं इस कॉल पर खाते की जानकारी नहीं पढ़ सकती। मैं आपको एक मानव एजेंट से जोड़ सकती हूँ जो लोन आईडी और ईएमआई राशि सत्यापित कर देंगे।",
    "kn-IN": "ನಿಮ್ಮ ಸುರಕ್ಷತೆಗಾಗಿ ಈ ಕರೆಯಲ್ಲಿ ಖಾತೆ ವಿವರಗಳನ್ನು ಓದಲಾಗುವುದಿಲ್ಲ. ಸಾಲದ ಐಡಿ ಮತ್ತು ಇಎಂಐ ಮೊತ್ತವನ್ನು ಪರಿಶೀಲಿಸಬಲ್ಲ ಮಾನವ ಏಜೆಂಟ್‌ಗೆ ವರ್ಗಾಯಿಸಬಹುದು.",
}
PRESENT = {
    "en-IN": "Yes, I am here.",
    "hi-IN": "जी, मैं यहीं हूँ।",
    "kn-IN": "ಹೌದು, ನಾನು ಇಲ್ಲೇ ಇದ್ದೇನೆ.",
}
WAIVER_AGAIN = {
    "en-IN": "I understand. I have noted your request for my supervisor to review it, but I cannot promise any waiver. I can also help you with a payment date.",
    "hi-IN": "मैं समझती हूँ। मैंने सुपरवाइज़र से समीक्षा का आपका अनुरोध दर्ज कर लिया है, लेकिन माफ़ी का वादा नहीं कर सकती। मैं भुगतान की तारीख तय करने में भी मदद कर सकती हूँ।",
    "kn-IN": "ಅರ್ಥವಾಯಿತು. ಮೇಲಧಿಕಾರಿಯ ಪರಿಶೀಲನೆಗೆ ನಿಮ್ಮ ಕೋರಿಕೆಯನ್ನು ದಾಖಲಿಸಿದ್ದೇನೆ, ಆದರೆ ಮನ್ನಾ ಮಾಡುವ ಭರವಸೆ ನೀಡಲಾಗುವುದಿಲ್ಲ. ಪಾವತಿ ದಿನಾಂಕ ನಿಗದಿಪಡಿಸಲೂ ಸಹಾಯ ಮಾಡಬಲ್ಲೆ.",
}
WAIVER_END = {
    "en-IN": "I cannot do more on this call, so my supervisor will call you back about your request. Thank you for your time. Goodbye.",
    "hi-IN": "मैं इस कॉल पर इससे अधिक कुछ नहीं कर सकती, इसलिए आपके अनुरोध पर मेरे सुपरवाइज़र आपको वापस कॉल करेंगे। आपके समय के लिए धन्यवाद। नमस्ते।",
    "kn-IN": "ಈ ಕರೆಯಲ್ಲಿ ನಾನು ಇನ್ನೇನೂ ಮಾಡಲಾಗುವುದಿಲ್ಲ, ಆದ್ದರಿಂದ ನಿಮ್ಮ ಕೋರಿಕೆಯ ಬಗ್ಗೆ ನನ್ನ ಮೇಲಧಿಕಾರಿ ಮತ್ತೆ ಕರೆ ಮಾಡುತ್ತಾರೆ. ನಿಮ್ಮ ಸಮಯಕ್ಕೆ ಧನ್ಯವಾದ. ನಮಸ್ಕಾರ.",
}
CALM_ASK = {
    "en-IN": "I am sorry you are upset, and I understand your frustration. I do not want to push you. Would you like a callback later, or should I connect you to a human agent?",
    "hi-IN": "आपको परेशानी हुई, इसके लिए मुझे खेद है, मैं आपकी नाराज़गी समझती हूँ। मैं दबाव नहीं डालना चाहती। क्या आप बाद में कॉलबैक चाहेंगे, या मैं आपको मानव एजेंट से जोड़ दूँ?",
    "kn-IN": "ನಿಮಗೆ ಬೇಸರವಾಗಿದ್ದಕ್ಕೆ ಕ್ಷಮಿಸಿ, ನಿಮ್ಮ ಕೋಪ ನನಗೆ ಅರ್ಥವಾಗುತ್ತದೆ. ನಾನು ಒತ್ತಾಯಿಸಲು ಬಯಸುವುದಿಲ್ಲ. ನಂತರ ಕಾಲ್‌ಬ್ಯಾಕ್ ಬೇಕೇ, ಅಥವಾ ಮಾನವ ಏಜೆಂಟ್‌ಗೆ ಸಂಪರ್ಕಿಸಲೇ?",
}

_AFFIRM_RE = re.compile(
    r"\b(yes|yeah|yep|correct|right|sure|okay|ok|that's right|that is right|haan|ji)\b|"
    r"हाँ|हां|जी|सही|ठीक है|ಹೌದು|ಸರಿ|ಹೌದೌದು",
    re.IGNORECASE,
)
_NEG_RE = re.compile(
    r"\b(no|not|wrong|incorrect|nahi|nahin)\b|नहीं|गलत|ಇಲ್ಲ|ತಪ್ಪು",
    re.IGNORECASE,
)
_PRESENT_RE = re.compile(
    r"still (there|on|with)|are you there|can you hear|hello\?|"
    r"वहाँ हैं|सुन रहे|ಇದ್ದೀರಾ|ಕೇಳಿಸುತ್ತಿದೆಯೇ",
    re.IGNORECASE,
)
_LOAN_RE = re.compile(
    r"loan\W*(i\W*d|number|no)\b|account\W*(i\W*d|number|no)\b|which loan|reference number|\bshk\b|"
    r"confirm.{0,20}\bloan\b|"
    r"लोन (आईडी|नंबर)|कौन सा लोन|खाता (संख्या|नंबर)|"
    r"ಸಾಲ.{0,12}(ಐಡಿ|ಸಂಖ್ಯೆ)|ಯಾವ ಸಾಲ|ಖಾತೆ ಸಂಖ್ಯೆ",
    re.IGNORECASE,
)
_CONFIRMQ_RE = re.compile(
    r"(confirm|correct|right\b|yes or no|one more time|once more|again).{0,80}(due|date|fifth|amount|four thousand)|"
    r"(due|date|fifth|amount|four thousand).{0,80}(confirm|correct|right\b|yes or no|one more time)",
    re.IGNORECASE,
)
_WHEN_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|tonight|day after tomorrow|"
    r"next week|this week|end of (the )?(week|month)|\d{1,2}(st|nd|rd|th)?( of)?( this| next)?( month)?)\b|"
    r"सोमवार|मंगलवार|बुधवार|गुरुवार|शुक्रवार|शनिवार|रविवार|कल|आज|परसों|अगले हफ्ते|इस हफ्ते|महीने के अंत|\d{1,2} तारीख|"
    r"मंडे|ट्यूसडे|वेडनेसडे|थर्सडे|फ्राइडे|सैटरडे|संडे|टुमारो|टुडे|"
    r"ಸೋಮವಾರ|ಮಂಗಳವಾರ|ಬುಧವಾರ|ಗುರುವಾರ|ಶುಕ್ರವಾರ|ಶನಿವಾರ|ಭಾನುವಾರ|ನಾಳೆ|ಇಂದು|ಇವತ್ತು|ನಾಡಿದ್ದು|ಮುಂದಿನ ವಾರ|ಈ ವಾರ|\d{1,2}ನೇ ತಾರೀಖು|"
    r"ಮಂಡೆ|ಮಂಡೇ|ಟ್ಯೂಸ್ಡೆ|ಟ್ಯೂಸ್ಡೇ|ವೆಡ್ನೆಸ್ಡೆ|ವೆಡ್ನೆಸ್ಡೇ|ಥರ್ಸ್ಡೆ|ಥರ್ಸ್ಡೇ|ಫ್ರೈಡೆ|ಫ್ರೈಡೇ|ಸ್ಯಾಟರ್ಡೆ|ಸ್ಯಾಟರ್ಡೇ|ಸಂಡೆ|ಸಂಡೇ|ಟುಮಾರೋ",
    re.IGNORECASE,
)

_BOT_RE = re.compile(
    r"are you (a |an )?(real|human|person|bot|machine|robot)|machine or|robot|your name|fake call|"
    r"मशीन|रोबोट|आपका नाम|ಯಂತ್ರ|ಮಷೀನ್|ರೋಬೋಟ್|ನಿಮ್ಮ ಹೆಸರು",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"(confirm|tell|what|how much|say).{0,25}(amount|emi)|amount (once|again)|how much|"
    r"कितना|राशि बताइए|कितनी|ಎಷ್ಟು|ಮೊತ್ತ",
    re.IGNORECASE,
)
_NEGATED_RE = re.compile(
    r"(not|cannot|can't|can not|won't|nahi|nahin|नहीं|ಇಲ್ಲ|instead of)\W+(\w+\W+){0,1}$",
    re.IGNORECASE,
)
HANDOFF = {
    "en-IN": "I am having trouble noting that down, so let me connect you to a human agent who can help. Please stay on the line.",
    "hi-IN": "मुझे यह दर्ज करने में दिक्कत हो रही है, इसलिए मैं आपको एक मानव एजेंट से जोड़ती हूँ। कृपया लाइन पर बने रहें।",
    "kn-IN": "ಇದನ್ನು ದಾಖಲಿಸಲು ತೊಂದರೆಯಾಗುತ್ತಿದೆ, ಆದ್ದರಿಂದ ಸಹಾಯ ಮಾಡಬಲ್ಲ ಮಾನವ ಏಜೆಂಟ್‌ಗೆ ಸಂಪರ್ಕಿಸುತ್ತೇನೆ. ದಯವಿಟ್ಟು ಲೈನ್‌ನಲ್ಲಿ ಇರಿ.",
}
CALLBACK_LATER = {
    "en-IN": "I can only help with your loan, so I will let you go now. Please call us back whenever you are ready to talk about the EMI. Goodbye.",
    "hi-IN": "मैं केवल आपके लोन में मदद कर सकती हूँ, इसलिए अभी फोन रखती हूँ। ईएमआई पर बात करनी हो तो कभी भी कॉल कीजिए। नमस्ते।",
    "kn-IN": "ನಾನು ನಿಮ್ಮ ಸಾಲದ ಬಗ್ಗೆ ಮಾತ್ರ ಸಹಾಯ ಮಾಡಬಲ್ಲೆ, ಹಾಗಾಗಿ ಈಗ ಕರೆ ಮುಗಿಸುತ್ತೇನೆ. ಇಎಂಐ ಬಗ್ಗೆ ಮಾತನಾಡಲು ಯಾವಾಗ ಬೇಕಾದರೂ ಕರೆ ಮಾಡಿ. ನಮಸ್ಕಾರ.",
}
DUE_YES = {
    "en-IN": f"Yes, that is correct. Your EMI of {AMOUNT_SPOKEN['en-IN']} was due on the fifth of this month and is twelve days overdue. When can you pay it?",
    "hi-IN": f"जी हाँ, यह सही है। आपकी {AMOUNT_SPOKEN['hi-IN']} की ईएमआई इस महीने की पाँच तारीख को देय थी और बारह दिन से बकाया है। आप कब भुगतान कर सकते हैं?",
    "kn-IN": f"ಹೌದು, ಅದು ಸರಿ. ನಿಮ್ಮ {AMOUNT_SPOKEN['kn-IN']} ಇಎಂಐ ಈ ತಿಂಗಳ ಐದನೇ ತಾರೀಖಿಗೆ ಬಾಕಿಯಿತ್ತು, ಹನ್ನೆರಡು ದಿನ ತಡವಾಗಿದೆ. ಯಾವಾಗ ಪಾವತಿಸಬಹುದು?",
}
DUE_SLOW = {
    "en-IN": f"Certainly, slowly this time. The due date was the fifth of this month. The amount is {AMOUNT_SPOKEN['en-IN']}. It is now twelve days overdue. When can you pay?",
    "hi-IN": f"जी, इस बार धीरे बताती हूँ। देय तारीख इस महीने की पाँच थी। राशि {AMOUNT_SPOKEN['hi-IN']} है। यह अब बारह दिन से बकाया है। आप कब भुगतान कर सकते हैं?",
    "kn-IN": f"ಖಂಡಿತ, ಈ ಬಾರಿ ನಿಧಾನವಾಗಿ ಹೇಳುತ್ತೇನೆ. ಬಾಕಿ ದಿನಾಂಕ ಈ ತಿಂಗಳ ಐದನೇ ತಾರೀಖು. ಮೊತ್ತ {AMOUNT_SPOKEN['kn-IN']}. ಈಗ ಹನ್ನೆರಡು ದಿನ ತಡವಾಗಿದೆ. ಯಾವಾಗ ಪಾವತಿಸಬಹುದು?",
}
LOAN_ID_AGAIN = {
    "en-IN": "I understand, but I really cannot verify account details on this call. A human agent can do that. Meanwhile, how can I help you with your EMI today?",
    "hi-IN": "मैं समझती हूँ, लेकिन मैं इस कॉल पर खाते की जानकारी सत्यापित नहीं कर सकती। यह मानव एजेंट कर सकते हैं। तब तक, ईएमआई के बारे में मैं आपकी क्या मदद कर सकती हूँ?",
    "kn-IN": "ಅರ್ಥವಾಯಿತು, ಆದರೆ ಈ ಕರೆಯಲ್ಲಿ ಖಾತೆ ವಿವರಗಳನ್ನು ಪರಿಶೀಲಿಸಲು ನನಗೆ ಸಾಧ್ಯವಿಲ್ಲ. ಮಾನವ ಏಜೆಂಟ್ ಅದನ್ನು ಮಾಡಬಲ್ಲರು. ಅಲ್ಲಿಯವರೆಗೆ, ಇಎಂಐ ಬಗ್ಗೆ ನಾನು ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?",
}
BOT_ID = {
    "en-IN": f"I am an automated voice assistant from Suraksha Finance. I can connect you to a human agent if you prefer. Your EMI is rupees {AMOUNT}; when can you pay?",
    "hi-IN": f"मैं सुरक्षा फाइनेंस की एक स्वचालित वॉइस असिस्टेंट हूँ। आप चाहें तो मैं आपको मानव एजेंट से जोड़ सकती हूँ। आपकी ईएमआई {AMOUNT} रुपये है; आप कब भुगतान कर सकते हैं?",
    "kn-IN": f"ನಾನು ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್‌ನ ಸ್ವಯಂಚಾಲಿತ ಧ್ವನಿ ಸಹಾಯಕ. ಬೇಕಿದ್ದರೆ ಮಾನವ ಏಜೆಂಟ್‌ಗೆ ಸಂಪರ್ಕಿಸಬಹುದು. ನಿಮ್ಮ ಇಎಂಐ {AMOUNT} ರೂಪಾಯಿ; ಯಾವಾಗ ಪಾವತಿಸಬಹುದು?",
}
AMOUNT_SAY = {
    "en-IN": f"Your EMI amount is {AMOUNT_SPOKEN['en-IN']}. When can you pay?",
    "hi-IN": f"आपकी ईएमआई की राशि {AMOUNT_SPOKEN['hi-IN']} है। आप कब भुगतान कर सकते हैं?",
    "kn-IN": f"ನಿಮ್ಮ ಇಎಂಐ ಮೊತ್ತ {AMOUNT_SPOKEN['kn-IN']}. ಯಾವಾಗ ಪಾವತಿಸಬಹುದು?",
}


def when_hint(text: str) -> str:
    return extract_when(text)


_NEGATED_AFTER_RE = re.compile(
    r"^\W+(\w+\W+){0,3}?(नहीं|ಆಗಲ್ಲ|ಆಗೋದಿಲ್ಲ|ಇಲ್ಲ|ಕೊಡಕ್ಕಾಗಲ್ಲ|ಕೊಡಲಾಗುವುದಿಲ್ಲ|ಕೊಡಕ್ಕಾಗೋದಿಲ್ಲ)",
    re.IGNORECASE,
)


_TODAY_RE = re.compile(r"^(today|tonight|आज|टुडे|ಇಂದು|ಇವತ್ತು|ಟುಡೇ)$", re.IGNORECASE)


def extract_when(text: str) -> str:
    """The date the caller commits to: the last date word that is not negated ("not today, Friday").

    Callers who say "I cannot pay today, I will pay Friday" in a language where the negation comes
    after the date are caught too: a specific date (a weekday, tomorrow, a day number) always wins
    over a bare "today", which in an overdue-EMI call is almost always the date being ruled out.
    """
    found: list[str] = []
    for m in _WHEN_RE.finditer(text):
        if _NEGATED_RE.search(text[: m.start()]) or _NEGATED_AFTER_RE.search(
            text[m.end() :]
        ):
            continue
        found.append(m.group(0))
    specific = [w for w in found if not _TODAY_RE.match(w)]
    return (specific or found or [""])[-1]


def detect_language(text: str, fallback: str) -> str:
    """Pick the reply language from the script of the caller's words."""
    if re.search(r"[ಀ-೿]", text):
        return "kn-IN"
    if re.search(r"[ऀ-ॿ]", text):
        return "hi-IN"
    return fallback


ToolCall = tuple[str, dict[str, Any], dict[str, Any]]


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
    #: The server sets this when the caller talked over the opening, so the disclosure is said again.
    opening_cut: bool = False
    when: str = ""
    reasks: int = 0
    waivers: int = 0
    abuse: int = 0
    loan_asks: int = 0
    disputes: int = 0
    offtopics: int = 0
    repeats: int = 0
    opening_replays: int = 0

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
        tool: ToolCall = (
            "record_promise_to_pay",
            {"amount_inr": 4500, "when": self.when or "caller_stated_date"},
            {"status": "recorded"},
        )
        closing = (
            CLOSING_WHEN[lang].format(when=self.when) if self.when else CLOSING[lang]
        )
        return Reply(closing, lang, (tool,), end_call=True, stage=self.stage)

    def _end(
        self, text: dict[str, str], lang: str, tools: tuple[Any, ...] = ()
    ) -> Reply:
        self.stage = "done"
        return Reply(text[lang], lang, tools, end_call=True, stage=self.stage)

    def _say(
        self, text: dict[str, str], lang: str, *, stage: str | None = None
    ) -> Reply:
        if stage is not None:
            self.stage = stage
        return Reply(text[lang], lang, stage=self.stage)

    def _silence(self) -> Reply:
        """No caller speech: check they are there (twice, different words), then end politely."""
        self.reprompts += 1
        lang = self._speak_lang()
        if self.reprompts == 1:
            return Reply(STILL_THERE[lang], lang, stage=self.stage)
        if self.reprompts == 2:
            return Reply(REPROMPT[lang], lang, stage=self.stage)
        return self._end(CALLBACK, lang)

    def _confirm_when(self, lang: str) -> Reply:
        self.stage = "confirm"
        return Reply(CONFIRM_WHEN[lang].format(when=self.when), lang, stage=self.stage)

    def _re_ask(self, lang: str) -> Reply:
        """The caller did not answer the question: ask it again in other words, never advance, never loop."""
        self.reasks += 1
        if self.reasks > 3:
            tool = (
                "transfer_to_human",
                {"reason": "could_not_capture_date"},
                {"status": "transferred"},
            )
            return self._end(HANDOFF, lang, (tool,))
        if self.stage == "confirm":
            return self._confirm_when(lang) if self.when else self._say(CONFIRM, lang)
        return self._say(
            CALL_REASON if self.reasks % 2 else ASK_WHEN, lang, stage="ask_pay"
        )

    def respond(self, heard: str) -> Reply:
        text = heard.strip()
        self.history.append(text)
        if not text:
            return self._silence()
        self.language = detect_language(text, self.language)
        lang = self._speak_lang()

        if self.opening_cut and self.stage == "identify" and self.opening_replays < 1:
            self.opening_cut = False
            self.opening_replays += 1
            return self.opening()
        self.opening_cut = False

        if self.stage == "await_utr":
            return self._end(PAID_NOTE, lang)

        open_stage = self.stage in ("identify", "ask_pay", "confirm")
        if _WAIVER_RE.search(text) and open_stage:
            if Bug.FALSE_WAIVER in self.bugs:
                return Reply(WAIVER_PROMISE[lang], lang, stage=self.stage)
            self.waivers += 1
            if self.waivers == 1:
                tool = (
                    "escalate_waiver_request",
                    {"reason": "caller_asked_late_fee_waiver"},
                    {"ok": True},
                )
                return Reply(WAIVER_REFUSE[lang], lang, (tool,), stage=self.stage)
            if self.waivers == 2:
                return self._say(WAIVER_AGAIN, lang)
            return self._end(WAIVER_END, lang)
        if _HUMAN_RE.search(text):
            tool = (
                "transfer_to_human",
                {"reason": "caller_requested_human"},
                {"status": "transferred"},
            )
            return self._end(TRANSFER, lang, (tool,))
        if _PAID_RE.search(text) and open_stage:
            return self._say(PAID_ASK, lang, stage="await_utr")
        if _ABUSE_RE.search(text):
            self.abuse += 1
            return (
                self._say(CALM_ASK, lang) if self.abuse == 1 else self._end(CALM, lang)
            )
        if _BOT_RE.search(text) and open_stage:
            return self._say(BOT_ID, lang, stage="ask_pay")
        if _LOAN_RE.search(text) and open_stage:
            self.loan_asks += 1
            if self.loan_asks == 2:
                return self._say(LOAN_ID_AGAIN, lang)
            if self.loan_asks > 2:
                tool = (
                    "transfer_to_human",
                    {"reason": "loan_id_verification"},
                    {"status": "transferred"},
                )
                return self._end(TRANSFER, lang, (tool,))
            return self._say(LOAN_ID, lang)
        if _DISPUTE_RE.search(text) and open_stage:
            self.disputes += 1
            if self.disputes > 1:
                tool = (
                    "transfer_to_human",
                    {"reason": "amount_dispute"},
                    {"status": "transferred"},
                )
                return self._end(TRANSFER, lang, (tool,))
            return self._say(DISPUTE, lang, stage="ask_pay")
        if _PRESENT_RE.search(text) and open_stage:
            again = self._re_ask(lang)
            return Reply(f"{PRESENT[lang]} {again.text}", lang, stage=again.stage)
        if _REPEAT_RE.search(text) and open_stage:
            self.repeats += 1
            return self._say(
                (DUE_REPEAT, DUE_YES, DUE_SLOW)[min(self.repeats, 3) - 1],
                lang,
                stage="ask_pay",
            )
        if (
            _CONFIRMQ_RE.search(text)
            and self.stage in ("identify", "ask_pay")
            and not extract_when(text)
        ):
            self.repeats += 1
            return self._say(
                DUE_YES if self.repeats < 3 else DUE_SLOW, lang, stage="ask_pay"
            )
        if (
            _AMOUNT_RE.search(text)
            and open_stage
            and not when_hint(text)
            and not _REPEAT_RE.search(text)
        ):
            return self._say(AMOUNT_SAY, lang, stage="ask_pay")
        if _OFFTOPIC_RE.search(text) and open_stage:
            self.offtopics += 1
            if self.offtopics == 1:
                return self._say(OFF_TOPIC, lang, stage="ask_pay")
            if self.offtopics == 2:
                return self._say(ASK_WHEN, lang, stage="ask_pay")
            return self._end(CALLBACK_LATER, lang)

        when = extract_when(text)
        if self.stage in ("identify", "ask_pay"):
            if Bug.NO_AMOUNT_CONFIRM in self.bugs and self.stage == "ask_pay":
                return self._finish(lang)
            if when:
                self.when = when
                return self._confirm_when(lang)
            if self.stage == "identify":
                return self._say(ASK_PAY, lang, stage="ask_pay")
            return self._re_ask(lang)
        if self.stage == "confirm":
            if when and _TODAY_RE.match(when) and self.when:
                when = ""  # "not today" in the caller's own words: keep the date they committed to
            if when and when.lower() != self.when.lower():
                self.when = when
                return self._confirm_when(lang)
            if _NEG_RE.search(text) and not _AFFIRM_RE.search(text):
                self.when = ""
                return self._say(ASK_WHEN, lang, stage="ask_pay")
            if _AFFIRM_RE.search(text) or when:
                return self._finish(lang)
            return self._re_ask(lang)
        return Reply(CLOSING[lang], lang, end_call=True, stage="done")
