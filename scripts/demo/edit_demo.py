#!/usr/bin/env python3
"""DOC-03-REC: cut proof/DOC-03/clips/*.webm into one ~60 s 1080p30 H.264 MP4 (burned captions, call audio mixed in).
Every cut is listed in SEGMENTS (source clip, start s, end s, speed, caption) and echoed to proof/DOC-03/cuts.json."""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
C = ROOT / "proof/DOC-03/clips"; OUT = ROOT / "proof/DOC-03/demo.mp4"
AUDIO = "/tmp/ed/call_mixed.bin"; AUDIO_CLIP_T = 13.6; AUDIO_CALL_OFFSET = 42.0   # clip time at which playback began / call position
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# (clip, start, end, speed, caption)
SEGMENTS = [
    ("01_runs", 1.5, 15.0, 1.8, "A real run: planted bug, Kannada caller, 8 kHz phone line. 0 of 1 calls passed."),
    ("02_call", 8.0, 19.5, 1.0, "The judge cites turn #6: the call ended without the promise to pay. 71.25 / 100, fail."),
    ("03_promote", 5.0, 17.0, 2.0, "Promote the failing call to a regression test."),
    ("04_compare", 6.0, 22.0, 2.3, "Same scenario, clean agent: 95.0, pass (+23.8 points)."),
    ("05_dialect", 3.0, 15.0, 2.0, "Dialect report on 20 Vaani clips. n = 4 per group, so cells are hatched as low sample."),
    ("06_audit", 10.0, 18.0, 3.0, "Upload a call recording (synthetic test call, 13 s)."),
    ("06_audit", 18.0, 45.3, 9.0, "Transcribed and scored with the same rubric."),
    ("06_audit", 45.3, 51.0, 1.0, "Audit: 48.75, critical. Wrong EMI amount and missing disclosure flagged."),
    ("07_hubspot", 3.0, 17.0, 2.5, "Live HubSpot integration: note delivered (HTTP 201). Delivery log, not the HubSpot app."),
    ("08_github", 3.5, 9.5, 1.5, "GitHub CI: pareeksha-regression fails on commit a8f8444 (planted bug)."),
    ("08_github", 11.5, 17.5, 1.5, "After the fix, the same check passes (run 41102511599)."),
]
parts, cuts, t_out = [], [], 0.0
for i, (clip, a, b, sp, cap) in enumerate(SEGMENTS):
    dur = (b - a) / sp
    cap = cap.replace("'", "’").replace(":", "\\:").replace(",", "\\,")
    f = (f"[{i}:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{sp},fps=30,scale=1920:1080,"
         f"drawbox=x=0:y=ih-110:w=iw:h=110:color=black@0.72:t=fill,"
         f"drawtext=fontfile={FONT}:text='{cap}':fontcolor=white:fontsize=36:x=48:y=h-72")
    if sp > 1.05:
        f += f",drawtext=fontfile={FONT}:text='sped up {sp:g}x':fontcolor=black:fontsize=30:box=1:boxcolor=yellow@0.95:boxborderw=10:x=w-tw-48:y=40"
    parts.append(f + f"[v{i}]")
    cuts.append({"clip": f"{clip}.webm", "src_start_s": a, "src_end_s": b, "speed": sp, "out_start_s": round(t_out, 2), "out_len_s": round(dur, 2), "caption": SEGMENTS[i][4]})
    t_out += dur
# call audio: starts at the clip time of the play click inside segment 2 (index 1)
seg = cuts[1]; a_start = seg["out_start_s"] + (AUDIO_CLIP_T - seg["src_start_s"]); a_len = seg["src_end_s"] - AUDIO_CLIP_T
inputs = [x for s in SEGMENTS for x in ("-i", str(C / f"{s[0]}.webm"))] + ["-i", AUDIO]
n = len(SEGMENTS)
fc = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v];"
fc += f"[{n}:a]atrim={AUDIO_CALL_OFFSET}:{AUDIO_CALL_OFFSET + a_len},asetpts=PTS-STARTPTS,adelay={int(a_start*1000)}:all=1,apad=whole_dur={t_out:.2f},aformat=sample_rates=44100:channel_layouts=stereo[a]"
subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                "-crf", "26", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "128k", "-t", f"{t_out:.2f}", "-movflags", "+faststart", str(OUT)], check=True)
(ROOT / "proof/DOC-03/cuts.json").write_text(json.dumps({"total_s": round(t_out, 2), "call_audio": {"out_start_s": round(a_start, 2), "len_s": round(a_len, 2), "call_offset_s": AUDIO_CALL_OFFSET}, "cuts": cuts}, indent=1))
print("total", round(t_out, 1))
