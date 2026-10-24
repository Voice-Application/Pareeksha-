#!/usr/bin/env python3
"""Build docs/design/mock-call-detail.html (single self-contained file).

Run: python3 -I proof/DES-01/build_mock.py
Inputs : proof/DES-01/mock-template.html, docs/design/tokens.css, Google Fonts (Geist, Geist Mono,
         Noto Sans Kannada; fetched once into $FONT_CACHE or /tmp, embedded as base64 woff2).
Output : docs/design/mock-call-detail.html
All numbers on the screen are synthetic sample data. They are internally consistent (the
overall score, points, p50/p95 and talk-time percentages are computed here from the sample
turns, not typed in).
"""
import base64
import html
import math
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "proof/DES-01/mock-template.html"
TOKENS = ROOT / "docs/design/tokens.css"
OUT = ROOT / "docs/design/mock-call-detail.html"
CACHE = Path(os.environ.get("FONT_CACHE", "/tmp/pareeksha-des01-fonts"))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Geist:wght@100..900&family=Geist+Mono:wght@100..900"
             "&family=Noto+Sans+Kannada:wght@100..900&display=swap")
WANT = [("Geist", "latin"), ("Geist Mono", "latin"), ("Noto Sans Kannada", "kannada")]

D = 108.0  # call duration, seconds


def fonts_css() -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    cssf = CACHE / "fonts.css"
    if not cssf.exists():
        cssf.write_text(urllib.request.urlopen(urllib.request.Request(FONTS_URL, headers={"User-Agent": UA})).read().decode())
    css = cssf.read_text()
    blocks = re.findall(r"/\* ([\w-]+) \*/\s*@font-face \{(.*?)\}", css, re.S)
    out = []
    for fam, sub in WANT:
        for s, b in blocks:
            if s == sub and f"font-family: '{fam}'" in b:
                url = re.search(r"url\((.*?)\)", b).group(1)
                rng = re.search(r"unicode-range: (.*?);", b).group(1)
                f = CACHE / (fam.replace(" ", "") + "-" + sub + ".woff2")
                if not f.exists():
                    f.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA})).read())
                b64 = base64.b64encode(f.read_bytes()).decode()
                out.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:100 900;font-display:swap;"
                           f"src:url(data:font/woff2;base64,{b64}) format('woff2');unicode-range:{rng}}}")
                break
        else:
            raise SystemExit(f"font block not found: {fam} {sub}")
    return "\n".join(out)


# ---------------------------------------------------------------- sample call data
# (idx, speaker, start_s, end_s, response_latency_s or None)
TURNS = [
    (0, "agent", 1.0, 9.0, None),
    (1, "caller", 11.0, 17.9, None),
    (2, "agent", 19.0, 28.0, 1.1),
    (3, "caller", 31.0, 41.0, None),
    (4, "agent", 42.4, 55.0, 1.4),
    (5, "caller", 52.0, 57.0, None),
    (6, "agent", 59.6, 74.0, 2.6),
    (7, "caller", 77.0, 85.0, None),
    (8, "agent", 86.0, 95.0, 1.0),
    (9, "caller", 97.0, 101.0, None),
    (10, "agent", 101.8, 106.0, 0.8),
]
KN = {
    1: ("ಹೌದು, speaking. EMI bagge alva? ನಾನು already pay maadiddini, but ಮೆಸೇಜ್ ಬಂದಿಲ್ಲ.",
        "Yes, speaking. Is this about the EMI? I already paid, but no message has come."),
    3: ("ಕಳೆದ ತಿಂಗಳು ಹದಿನೈದನೇ ತಾರೀಖು, ನಾಲ್ಕು ಸಾವಿರ kattiddini.",
        "Last month on the 15th, I paid four thousand."),
    5: ("ಇಲ್ಲ ಇಲ್ಲ, four thousand! ನಲವತ್ತು alla!", "No, no, four thousand! Not forty!"),
    7: ("ಸರಿ, ಮೆಸೇಜ್ please send maadi.", "Okay, please send the message."),
    9: ("ಇಲ್ಲ. ಧನ್ಯವಾದಗಳು.", "No. Thank you."),
}
EN = {
    0: "Namaskara. I am the EMI reminder assistant from Sample Finance. This call is recorded for quality. May I speak with the account holder?",
    2: "Thank you. Our records show an EMI due on 5 November. When did you pay, and how much?",
    4: "Understood. You paid ₹ 40,000 on the 15th. Let me confirm that amount: forty thousand rupees. Is that correct?",
    6: "Thank you for confirming. I have recorded your payment of ₹ 40,000 and will update the account.",
    8: "A confirmation message will be sent within one day. Is there anything else I can help with?",
    10: "Thank you. Have a good day.",
}
DIMS = [  # key, label, weight, score 0..4, reason, evidence turns
    ("task_completion", "Task completion", 25, 1, "Dispute was logged, but for the wrong amount. The caller's goal was met for the wrong value.", [4, 6]),
    ("policy_compliance", "Policy compliance", 20, 3, None, []),
    ("factual_accuracy", "Factual accuracy", 15, 0, "Confirmed and recorded ₹ 40,000 although the caller said four thousand twice. Critical.", [3, 4, 6]),
    ("language_handling", "Language handling", 15, 2, "Replied only in English to a Kannada-English caller and did not ask to repeat the amount.", [4]),
    ("conversation_flow", "Conversation flow", 10, 3, None, []),
    ("empathy_tone", "Empathy and tone", 10, 3, None, []),
    ("escalation", "Escalation", 5, 4, None, []),
]
CHECKS = [  # key, state p/f/w, detail, result word, must_pass
    ("recording_disclosure", "p", "Said in turn 0 at 00:01", "Pass", False),
    ("forbidden_absent", "p", "No forbidden phrases in 6 agent turns", "Pass", False),
    ("no_loops", "p", "No repeated agent turn", "Pass", False),
    ("amount_confirmed", "f", "Agent confirmed 40000, expected 4000", "Fail", True),
    ("response_latency_p95", "f", "2.6 s, target under 2.0 s", "Fail", False),
    ("barge_in_honoured", "f", "0 of 1 honoured, target at least 90%", "Fail", False),
]


def mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 60:02d}:{s % 60:02d}"


def pct(t: float) -> str:
    return f"{t / D * 100:.3f}".rstrip("0").rstrip(".")


def rng(seed):
    s = seed & 0xFFFFFFFF
    def nxt():
        nonlocal s
        s = (s + 0x6D2B79F5) & 0xFFFFFFFF
        t = s
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return nxt


def wave_path(speaker: str, seed: int) -> str:
    r = rng(seed)
    spans = [(a, b) for (_, sp, a, b, _) in TURNS if sp == speaker]
    parts = []
    for i in range(0, 1080):
        t = i / 10.0
        inside = any(a <= t <= b for a, b in spans)
        if inside:
            syl = abs(math.sin(t * 5.3 + seed)) * 0.55 + abs(math.sin(t * 11.7 + seed * 0.3)) * 0.45
            amp = 3.0 + 14.5 * syl * (0.55 + 0.45 * r())
        else:
            amp = 0.5 + 0.6 * r()
        parts.append(f"M{i + 0.5} {20 - amp:.1f}V{20 + amp:.1f}")
    return "".join(parts)


def ruler() -> str:
    return "".join(f'<b style="left:{pct(t)}%">{mmss(t)}</b>' for t in range(0, 109, 10))


LAT_MAX = 3.0
LAT_SCALE = 70.0  # % of lane height used for LAT_MAX


def latbars() -> str:
    out = []
    for (i, sp, a, b, lat) in TURNS:
        if lat is None:
            continue
        cls = "over" if lat > 2.0 else ("mid" if lat > 1.0 else "")
        out.append(f'<span class="latbar {cls}" style="left:{pct(a)}%;height:{lat / LAT_MAX * LAT_SCALE:.1f}%" title="Turn {i}: {lat:.1f} s"><b>{lat:.1f}</b></span>')
    return "\n".join(out)


I = lambda name, cls="i sm": f'<svg class="{cls}" aria-hidden="true"><use href="#i-{name}"/></svg>'


def turns_html() -> str:
    rows = []
    for (i, sp, a, b, lat) in TURNS:
        ev = i in (4, 5, 6)
        cls = f"turn {sp}" + (" ev" if ev else "") + (" playing" if i == 4 else "")
        who = "Agent" if sp == "agent" else "Caller"
        if sp == "caller" and i in KN:
            txt, tr = KN[i]
            body = f'<p class="say" lang="kn">{html.escape(txt)}</p><div class="tr">{html.escape(tr)}</div>'
        else:
            body = f'<p class="say" lang="en">{html.escape(EN[i])}</p>'
        extra = ""
        chips = []
        if i == 3:
            extra += '<div class="glass"><b>Agent STT heard</b>last month fifteenth, <span class="bad">forty thousand</span> paid</div>'
            chips.append('<span class="chip mono fail">' + I("x") + "asr_misrecognition</span>")
        if i == 4:
            chips.append('<span class="chip mono fail">' + I("x") + "wrong_fact</span>")
            chips.append('<span class="chip mono">evidence for factual_accuracy</span>')
        if i == 5:
            extra += '<div class="barge">' + I("tri") + "Caller interrupted at 00:52. Agent kept speaking for 3.0 s.</div>"
            chips.append('<span class="chip mono warn">' + I("tri") + "interruption_handling</span>")
        if i == 6:
            extra += ('<div class="glass"><b>Tool call</b>record_payment_claim(amount=<span class="bad">40000</span>, date="15th") at 01:02</div>')
            chips.append('<span class="chip mono fail">' + I("x") + "tool_arguments</span>")
        if lat is not None:
            c = "fail" if lat > 2.0 else ("warn" if lat > 1.0 else "")
            ic = I("x") if lat > 2.0 else (I("tri") if lat > 1.0 else "")
            chips.append(f'<span class="chip mono {c}">{ic}{lat:.1f} s to respond</span>')
        foot = f'<div class="foot">{"".join(chips)}</div>' if chips else ""
        rows.append(
            f'<div class="{cls}" id="t{i}" data-t="{a}" role="button" tabindex="0" aria-label="Turn {i}, {who}, {mmss(a)}">'
            f'<div class="ts">{mmss(a)}<br>#{i}</div><div class="who">{who}</div>'
            f'<div class="body">{body}{extra}{foot}</div></div>'
        )
    return "\n".join(rows)


def dims_html():
    out = []
    total = 0.0
    for key, label, w, s, why, refs in DIMS:
        pts = w * s / 4
        total += pts
        step = s + 1
        pips = "".join(f'<i class="{"on" if n < s else ""}"></i>' for n in range(4))
        reason = f'<p class="why">{html.escape(why)}</p>' if why else ""
        rf = ""
        if refs:
            rf = '<div class="refs">' + "".join(f'<a class="ref" data-seek="{n}" href="#t{n}">#{n}</a>' for n in refs) + "</div>"
        crit = ' <span class="badge critical" style="height:18px">critical</span>' if (s == 0 and key == "factual_accuracy") else ""
        out.append(
            f'<div class="dim"><div class="dim-top"><span class="name">{label}</span><span class="w">{w}%</span>{crit}'
            f'<span class="pts">{pts:g} / {w}</span><span class="sc s{step}" title="Score {s} of 4">{s}/4</span></div>'
            f'<div class="pips s{step}" aria-hidden="true">{pips}</div>{reason}{rf}</div>'
        )
    return "\n".join(out), total


def checks_html():
    out = []
    for key, st, detail, word, must in CHECKS:
        ic = {"p": "check", "f": "x", "w": "tri"}[st]
        mp = ' <span class="chip" style="height:18px;font-size:var(--text-2xs)">must pass</span>' if must else ""
        out.append(f'<div class="row {st}">{I(ic, "i")}<div><span class="k">{key}</span>{mp}<span class="d">{html.escape(detail)}</span></div><span class="res">{word}</span></div>')
    return "\n".join(out)


def stats_html():
    lats = sorted(l for (_, _, _, _, l) in TURNS if l is not None)
    def nearest_rank(p):
        return lats[max(0, math.ceil(p / 100 * len(lats)) - 1)]
    p50, p95 = nearest_rank(50), nearest_rank(95)
    agent = sum(b - a for (_, sp, a, b, _) in TURNS if sp == "agent")
    caller = sum(b - a for (_, sp, a, b, _) in TURNS if sp == "caller")
    # overlap counted once for silence
    covered = 0.0
    spans = sorted((a, b) for (_, _, a, b, _) in TURNS)
    cur_a, cur_b = spans[0]
    for a, b in spans[1:]:
        if a <= cur_b:
            cur_b = max(cur_b, b)
        else:
            covered += cur_b - cur_a
            cur_a, cur_b = a, b
    covered += cur_b - cur_a
    sil = max(0.0, D - covered)
    ap, cp = round(agent / D * 100), round(caller / D * 100)
    sp_ = 100 - ap - cp
    def stat(cls, ic, v, label, target):
        return f'<div class="stat {cls}"><div class="eyebrow">{label}</div><div class="v">{ic}{v}</div><div class="t">{target}</div></div>'
    return '<div class="stats">' + "".join([
        stat("w", I("tri"), f"{p50:.1f} s", "Response p50", "target under 1.0 s"),
        stat("f", I("x"), f"{p95:.1f} s", "Response p95", "target under 2.0 s"),
        stat("p", I("check"), "0.9 s", "First greeting", "target under 1.5 s"),
        stat("f", I("x"), "0 of 1", "Barge-in honoured", "target at least 90%"),
        stat("", "", f"{ap} / {cp} / {sp_}%", "Talk time", "agent / caller / silence"),
        stat("", "", "11", "Turns", "6 agent, 5 caller"),
    ]) + "</div>", (p50, p95)


def main():
    tpl = TEMPLATE.read_text()
    tokens = TOKENS.read_text()
    dims, total = dims_html()
    stats, (p50, p95) = stats_html()
    assert abs(total - 48.75) < 1e-9, total          # template header hard-codes 48.75; fail loudly if data drifts
    assert (p50, p95) == (1.1, 2.6), (p50, p95)
    rep = {
        "/*__FONTS__*/": fonts_css(),
        "/*__TOKENS__*/": tokens,
        "/*__RULER__*/": ruler(),
        "/*__WAVE_AGENT__*/": wave_path("agent", 7),
        "/*__WAVE_CALLER__*/": wave_path("caller", 13),
        "/*__BARGE_X__*/": pct(52.0),
        "/*__TOOL_X__*/": pct(62.0),
        "/*__LIMIT_Y__*/": f"{2.0 / LAT_MAX * LAT_SCALE:.1f}",
        "/*__LATBARS__*/": latbars(),
        "/*__EV_X0__*/": pct(42.4),
        "/*__EV_W__*/": f"{(74.0 - 42.4) / D * 100:.3f}",
        "/*__PH_X__*/": pct(50.0),
        "/*__TURNS__*/": turns_html(),
        "/*__DIMS__*/": dims,
        "/*__CHECKS__*/": checks_html(),
        "/*__STATS__*/": stats,
    }
    for k, v in rep.items():
        assert k in tpl, k
        tpl = tpl.replace(k, v)
    tpl = tpl.replace('<span id="now">00:52</span>', '<span id="now">00:50</span>')
    OUT.write_text(tpl)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB); overall={total}, p50={p50}, p95={p95}")


if __name__ == "__main__":
    main()
