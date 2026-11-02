#!/usr/bin/env python3
"""EVAL-06 step 2: export the blind labelling packet for the 30 calibration calls.

Reads proof/EVAL-06/batch.json (written by run_batch.py) and the calls through the API, then writes
labelling/EVAL-06/:

    index.html        links to the 30 calls, GUIDE.md and labels.csv
    L01.html .. L30.html   audio player (caller + agent mix) and the timestamped transcript,
                      with an English gloss of Kannada/Hindi turns (DeepSeek machine translation)
    audio/L01.mp3 ..  the mixed recording, mono MP3, metadata stripped
    labels.csv        empty template for the owner
    .key.json         label id -> call id (shuffled order)

Blindness (docs/08-evaluation-rubric.md section 10): the pages never show the judge's output,
deterministic checks, metrics, the planted bug, the agent name, the scenario title/tags or the persona
name. They do show what the caller was asked to do, the facts on file and the scenario's success
criteria (the same brief the judge gets, identical for clean and bugged agents), the caller's
language, and the agent's own tool calls (part of the agent's behaviour).

Glosses are cached in proof/EVAL-06/gloss_cache.json (keyed by call id) so a re-export does not pay
again; DeepSeek token usage is appended to proof/EVAL-06/gloss_usage.json.

    python3 scripts/calibration/export_packet.py [--seed N]
Env: DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL (default https://api.deepseek.com), PAREEKSHA_API_* as vapi.py.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verify"))
sys.path.insert(0, str(Path(__file__).parent))
import vapi  # noqa: E402
from import_labels import COLUMNS  # noqa: E402

PACKET = ROOT / "labelling" / "EVAL-06"
PROOF = ROOT / "proof" / "EVAL-06"
GLOSS_MODEL = os.environ.get("DEEPSEEK_CALLER_MODEL") or "deepseek-flash"
LANG_NAMES = {"kn-IN": "Kannada", "hi-IN": "Hindi", "en-IN": "English (India)"}
NON_LATIN = re.compile(r"[ऀ-ॿಀ-೿]")  # Devanagari, Kannada


def fmt_ms(ms: int) -> str:
    return f"{ms // 60000:d}:{ms % 60000 / 1000:04.1f}"


def download_mp3(call_id: str, dest: Path) -> None:
    req = urllib.request.Request(
        f"{vapi.api_url()}/calls/{call_id}/audio/mixed",
        headers={"Authorization": f"Bearer {vapi.setting('PAREEKSHA_API_KEY')}"},
    )
    with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
        with urllib.request.urlopen(req, timeout=120) as r:
            wav.write(r.read())
        wav.flush()
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                wav.name,
                "-map_metadata",
                "-1",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "48k",
                str(dest),
            ],
            check=True,
        )


GLOSS_PROMPT = """You translate lines from a phone call between a loan-collection voice agent and a borrower
in India into plain English, for a reviewer who does not speak the language. Translate faithfully,
including errors, hesitations and anything odd; do not fix, summarise or add anything. Numbers stay as
said (e.g. "four thousand five hundred rupees"). Lines already in English: copy them unchanged.

The lines come from speech-to-text set to the call's language, so English speech is often written out
phonetically in Kannada or Devanagari script (e.g. "ದಿಸ್ ಕಾಲ್ ಈಸ್ ಬೀಯಿಂಗ್ ರೆಕಾರ್ಡೆಡ್" is the English "this call is
being recorded"). For each line also say which language was actually spoken: "Kannada", "Hindi",
"English", or "mixed" (more than one language in the line).

Return json only, in exactly this shape:
{"glosses": [{"idx": 0, "spoken": "English", "en": "..."}, ...]} with one entry per input line, same idx
values.

Lines:
"""


def gloss(
    turns: list[dict[str, Any]], usage_log: list[dict[str, Any]], call_id: str
) -> dict[int, dict[str, str]]:
    """``{turn idx: {"en": English gloss, "spoken": language the line was spoken in}}``."""
    lines = [
        {"idx": t["idx"], "speaker": t["speaker"], "text": t["text"]}
        for t in turns
        if NON_LATIN.search(t["text"])
    ]
    if not lines:
        return {}
    body = {
        "model": GLOSS_MODEL,
        "messages": [
            {"role": "user", "content": GLOSS_PROMPT + json.dumps(lines, ensure_ascii=False)}
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    url = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip(
        "/"
    ) + "/chat/completions"
    headers = {"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"}
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=120)
            r.raise_for_status()
            data = r.json()
            out = json.loads(data["choices"][0]["message"]["content"] or "{}")
            got = {
                int(g["idx"]): {"en": str(g["en"]), "spoken": str(g.get("spoken") or "")}
                for g in out.get("glosses", [])
            }
            missing = {ln["idx"] for ln in lines} - set(got)
            if missing:
                raise ValueError(f"gloss missing idx {sorted(missing)}")
            usage_log.append(
                {
                    "call_id": call_id,
                    "model": data.get("model"),
                    "usage": data.get("usage"),
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
            return got
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"gloss failed for {call_id}: {last}")


CSS = """
:root{--fg:#1a1d21;--muted:#5b6470;--bg:#fbfbfa;--card:#fff;--line:#e3e5e8;--agent:#0f5e66;--caller:#6b3fa0;--tool:#8a5a00}
@media (prefers-color-scheme:dark){:root{--fg:#e7e9ec;--muted:#9aa3ad;--bg:#14171a;--card:#1c2024;--line:#2c3238;--agent:#5fc4cc;--caller:#c4a3f0;--tool:#e0b25c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.5 system-ui,-apple-system,"Segoe UI","Noto Sans","Noto Sans Kannada","Noto Sans Devanagari",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}a{color:inherit}
h1{font-size:1.4rem;margin:.5rem 0}h2{font-size:1.05rem;margin:1.2rem 0 .4rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0}
.muted{color:var(--muted);font-size:.9rem}audio{width:100%;position:sticky;top:0;z-index:2;background:var(--bg)}
.turn{display:grid;grid-template-columns:4.2rem 1fr;gap:4px 10px;padding:8px 0;border-top:1px solid var(--line)}
.ts{font-variant-numeric:tabular-nums;color:var(--muted);background:none;border:0;padding:0;font:inherit;cursor:pointer;text-align:left}
.ts:hover{text-decoration:underline}.who{font-weight:600}.agent .who{color:var(--agent)}.caller .who{color:var(--caller)}
.tool .who{color:var(--tool)}.gloss{color:var(--muted);font-style:italic}.gloss b{font-style:normal;font-weight:600;font-size:.8rem}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:0}dt{color:var(--muted)}dd{margin:0}
nav{display:flex;justify-content:space-between;gap:8px;margin:8px 0}ul.calls{columns:3 10rem;padding-left:1.2rem}
code{font-size:.9em}
"""


def page(title: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>'
        f"<style>{CSS}</style></head><body><main>{body}</main></body></html>\n"
    )


def call_page(
    lid: str,
    prev: str | None,
    nxt: str | None,
    call: dict[str, Any],
    scenario: dict[str, Any],
    glosses: dict[int, dict[str, str]],
) -> str:
    e = html.escape
    lang = LANG_NAMES.get(call.get("language") or "", call.get("language") or "unknown")
    fixtures = "".join(
        f"<dt>{e(str(k))}</dt><dd>{e(str(v))}</dd>"
        for k, v in (scenario.get("fixtures") or {}).items()
    )
    items: list[tuple[int, int, str]] = []
    for t in call["turns"]:
        g = glosses.get(t["idx"])
        gl = (
            f'<div class="gloss"><b>MT gloss (spoken: {e(g["spoken"] or "?")}):</b> {e(g["en"])}</div>'
            if g
            else ""
        )
        items.append(
            (
                t["start_ms"],
                0,
                f'<div class="turn {e(t["speaker"])}"><button class="ts" data-t="{t["start_ms"]}">'
                f'{fmt_ms(t["start_ms"])}</button><div><span class="who">{e(t["speaker"].capitalize())}</span> '
                f'<span class="muted">({fmt_ms(t["start_ms"])}–{fmt_ms(t["end_ms"])})</span>'
                f'<div lang="{e(call.get("language") or "")}">{e(t["text"])}</div>{gl}</div></div>',
            )
        )
    for tc in call.get("tool_calls") or []:
        args = json.dumps(tc.get("arguments") or {}, ensure_ascii=False)
        items.append(
            (
                tc["at_ms"],
                1,
                f'<div class="turn tool"><button class="ts" data-t="{tc["at_ms"]}">{fmt_ms(tc["at_ms"])}'
                f'</button><div><span class="who">Agent tool call</span> <code>{e(tc["name"])}</code> '
                f"<code>{e(args)}</code></div></div>",
            )
        )
    transcript = "".join(x for _, _, x in sorted(items, key=lambda i: (i[0], i[1])))
    back = f'<a href="{prev}.html">&larr; {prev}</a>' if prev else ""
    fwd = f'<a href="{nxt}.html">{nxt} &rarr;</a>' if nxt else ""
    nav = f'<nav><span>{back}</span><a href="index.html">All calls</a><span>{fwd}</span></nav>'
    has_gloss = bool(glosses)
    body = f"""{nav}<h1>Call {lid}</h1>
<p class="muted">Caller language: {e(lang)} · Length {fmt_ms(call.get("duration_ms") or 0)} ·
Label this call in <code>labels.csv</code>, row <b>{lid}</b>. See <a href="GUIDE.md">GUIDE.md</a> for the scores.</p>
<audio id="a" controls preload="metadata" src="audio/{lid}.mp3"></audio>
<div class="card"><h2>What the simulated caller was asked to do</h2><p>{e(scenario.get("caller_goal") or "")}</p>
<h2>Facts on file (synthetic)</h2><dl>{fixtures}</dl>
<h2>Success criteria for the agent</h2><p>{e(scenario.get("success_criteria") or "")}</p></div>
<h2>Transcript</h2>
<p class="muted">Speech-to-text of the recording (Gnani), so it can contain recognition errors: the audio is the
source of truth. Click a timestamp to play from there.{" Lines marked <b>MT gloss</b> are a <b>machine translation</b> by DeepSeek, not a human translation, and its guess of the language actually spoken (English speech is often written out in Kannada or Devanagari script by the speech-to-text); both can be wrong." if has_gloss else ""}</p>
<div class="card">{transcript or '<p class="muted">No speech was transcribed in this call.</p>'}</div>
{nav}
<script>document.querySelectorAll('.ts').forEach(b=>b.addEventListener('click',()=>{{const a=document.getElementById('a');a.currentTime=b.dataset.t/1000;a.play();}}));</script>"""
    return page(f"Call {lid}", body)


def index_page(rows: list[tuple[str, dict[str, Any]]]) -> str:
    links = "".join(
        f'<li><a href="{lid}.html">{lid}</a> <span class="muted">{LANG_NAMES.get(c.get("language") or "", "")}, '
        f"{fmt_ms(c.get('duration_ms') or 0)}</span></li>"
        for lid, c in rows
    )
    body = f"""<h1>EVAL-06 blind labelling packet</h1>
<p>30 simulated calls to a synthetic EMI-reminder voice agent, in random order. Listen to each call, then fill
one row of <a href="labels.csv"><code>labels.csv</code></a> per call. Read <a href="GUIDE.md">GUIDE.md</a> first
(one page: the 7 scores, what counts as critical, and when a call passes).</p>
<p class="muted">Nothing here shows how the automatic judge scored a call; please do not look it up in the app
until you have finished labelling. All people, loans and numbers are synthetic.</p>
<ul class="calls">{links}</ul>"""
    return page("EVAL-06 labelling", body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="shuffle seed (default: random, recorded in .key.json)",
    )
    args = ap.parse_args()
    batch = [
        r
        for r in json.loads((PROOF / "batch.json").read_text())
        if r.get("evaluation_status") == "ok"
    ]
    if len(batch) != 30:
        raise SystemExit(f"expected 30 evaluated calls in batch.json, found {len(batch)}")
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**31)
    order = list(batch)
    random.Random(seed).shuffle(order)
    scenarios = {s["title"]: s for s in vapi.items("/scenarios")}
    cache_file, usage_file = PROOF / "gloss_cache.json", PROOF / "gloss_usage.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    usage = json.loads(usage_file.read_text()) if usage_file.exists() else []
    PACKET.mkdir(parents=True, exist_ok=True)
    ids = [f"L{i:02d}" for i in range(1, 31)]
    key, pages = {}, []
    for i, (lid, row) in enumerate(zip(ids, order)):
        call = vapi.call(row["call_id"])
        if row["call_id"] not in cache:
            cache[row["call_id"]] = {
                str(k): v for k, v in gloss(call["turns"], usage, row["call_id"]).items()
            }
            cache_file.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
            usage_file.write_text(json.dumps(usage, indent=1))
        glosses = {int(k): v for k, v in cache[row["call_id"]].items()}
        download_mp3(row["call_id"], PACKET / "audio" / f"{lid}.mp3")
        prev, nxt = (ids[i - 1] if i else None), (ids[i + 1] if i + 1 < len(ids) else None)
        (PACKET / f"{lid}.html").write_text(
            call_page(lid, prev, nxt, call, scenarios[row["scenario"]], glosses)
        )
        key[lid] = {"call_id": row["call_id"]}
        pages.append((lid, call))
        print(
            f"{lid} <- {row['call_id']} turns={len(call['turns'])} glossed={len(glosses)}",
            flush=True,
        )
    (PACKET / "index.html").write_text(index_page(pages))
    (PACKET / ".key.json").write_text(
        json.dumps({"shuffle_seed": seed, "labels": key}, indent=1) + "\n"
    )
    with (PACKET / "labels.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for lid in ids:
            w.writerow([lid] + [""] * (len(COLUMNS) - 1))
    size = sum(p.stat().st_size for p in PACKET.rglob("*") if p.is_file())
    print(f"packet: {PACKET} ({size / 1e6:.1f} MB), shuffle seed {seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
