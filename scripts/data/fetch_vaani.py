"""Select a dialect evaluation set from Vaani (ARTPARK-IISc/Vaani, CC-BY-4.0) without full shards.

Each Vaani shard is a ~0.3-0.6 GB parquet file on the Hugging Face Hub. This script opens shards
through ``HfFileSystem`` (HTTP range requests), reads only the small metadata/transcript columns to
choose clips, and then reads the ``audio`` column of just the row groups that hold chosen clips.

Selection rules (see data/dialect/vaani/SOURCES.md for the run that produced the committed set):
  * ``isTranscriptionAvailable == "Yes"`` and the row's ``language`` is the group's language;
  * 5-20 s long;
  * the transcript has no ``[unintelligible]``, ``[inaudible]`` or ``<UNKNOWN_SEGMENT>`` (the
    reference would be incomplete, so WER would blame the engine for words nobody wrote down);
  * at least 4 words after the transcription tags are stripped (``clean_transcript``);
  * kn-en-mix only: the transcript marks at least 2 English words (Vaani writes an English word in
    native script followed by its Latin spelling in braces, ``ಗ್ರೀನ್ {green}``), and those make up at
    least 10 % of the words;
  * speakers are taken round-robin (at most ``--max-per-speaker`` clips each) so every group has as
    many distinct speakers as the scanned shards offer.

Requires HF_TOKEN with access to the gated dataset, the backend dependencies (numpy, scipy,
soundfile) and ``pip install pyarrow huggingface_hub``. Usage (from the repository root):

    python3 scripts/data/fetch_vaani.py --out data/dialect/vaani
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

if TYPE_CHECKING:  # pyarrow / huggingface_hub are needed only to fetch, not to import this module
    from huggingface_hub import HfFileSystem

REPO = "datasets/ARTPARK-IISc/Vaani"
REVISION = (
    "9e6ed4f94f7060e633cbc500480623ae7521522c"  # dataset commit the committed set was taken from
)
TARGET_RATE = 16_000
META_COLUMNS = [
    "audio.path",
    "language",
    "duration",
    "speakerID",
    "gender",
    "state",
    "district",
    "pincode",
    "stay(years)",
    "isTranscriptionAvailable",
    "transcript",
    "UtteranceSequenceID",
]


@dataclass(frozen=True)
class Group:
    label: str
    language: str  # manifest language code
    vaani_language: str  # value of Vaani's ``language`` column
    folders: tuple[str, ...]  # audio/<State>/<District>
    code_mix: bool = False
    description: str = ""


GROUPS = (
    Group(
        "kn-mysuru",
        "kn-IN",
        "Kannada",
        ("audio/Karnataka/Mysore", "audio/Karnataka/Chamarajanagar"),
        description="Old Mysore Kannada (Mysore, Chamarajanagar)",
    ),
    Group(
        "kn-north",
        "kn-IN",
        "Kannada",
        ("audio/Karnataka/Dharwad", "audio/Karnataka/Belgaum"),
        description="North Karnataka Kannada (Dharwad, Belgaum)",
    ),
    Group(
        "kn-coastal",
        "kn-IN",
        "Kannada",
        ("audio/Karnataka/DakshinaKannada",),
        description="Coastal Kannada (Dakshina Kannada)",
    ),
    Group(
        "hi-standard",
        "hi-IN",
        "Hindi",
        ("audio/UttarPradesh/Lucknow", "audio/Delhi/NewDelhi"),
        description="Hindi-belt Hindi (Lucknow, New Delhi)",
    ),
    Group(
        "kn-en-mix",
        "kn-IN",
        "Kannada",
        ("audio/Karnataka/Bangalore",),
        code_mix=True,
        description="Bengaluru Kannada-English code-mix (Bangalore)",
    ),
)

# Vaani transcription convention (paper arXiv:2603.28714, Appendix A "Vaani Audio Transcription
# Guidelines", plus tags observed in the data; recorded in data/dialect/vaani/SOURCES.md).
EXCLUDE_TAGS = re.compile(r"\[\s*(unintelligible|inaudible)\s*\]|<\s*UNKNOWN_SEGMENT\s*>", re.I)
BRACES = re.compile(r"\{([^{}]*)\}")  # misspelling correction / Latin spelling of an English word
SQUARE = re.compile(r"\[[^\[\]]*\]")  # non-speech events: [noise], [breathing], [laugh], ...
ANGLE = re.compile(r"</?\s*[A-Za-z_]+\s*>")  # span markers <noise>...</noise>, <PAUSE>
INCOMPLETE = re.compile(r"(?:--+|[–—])")  # incomplete-utterance markers
DANDA = re.compile(r"[।॥|]")
LATIN_WORD = re.compile(r"^[A-Za-z][A-Za-z' .-]*$")
# IISc_VaaniProject_<vendor>_<State>_<District>_<speaker>_...; ``speakerID`` is "SID_<speaker>".
SPEAKER_IN_NAME = re.compile(r"^IISc_VaaniProject_([A-Z])_[A-Za-z]+_[A-Za-z]+_([A-Za-z0-9]+)_")


def rel(path: str) -> str:
    """Hub path (possibly ``Vaani@<revision>/...``) -> path inside the dataset repo."""
    return "audio/" + path.split("/audio/", 1)[1]


def clean_transcript(text: str) -> str:
    """Strip Vaani tags, keep the words that were spoken (native script, as transcribed)."""
    text = unicodedata.normalize("NFC", text)
    # word{gloss}suffix was one spoken word (ಪ್ಲೇಗ್ರೌಂಡ್{playground}ನಲ್ಲಿ): rejoin it
    text = re.sub(r"(?<=\S)\{[^{}]*\}(?=[^\s\[\]<>{}.,?।|])", "", text)
    text = BRACES.sub(" ", text)
    text = SQUARE.sub(" ", text)
    text = ANGLE.sub(" ", text)
    text = INCOMPLETE.sub(" ", text)
    text = DANDA.sub(" ", text)
    return " ".join(text.split())


def english_glosses(text: str) -> list[str]:
    """Latin-script brace contents: the English words the speaker used."""
    return [g.strip() for g in BRACES.findall(text) if g.strip() and LATIN_WORD.match(g.strip())]


def gloss_heads(text: str) -> list[str]:
    """Native-script word written right before each Latin brace gloss (the spoken loanword)."""
    heads = []
    for m in BRACES.finditer(text):
        if not LATIN_WORD.match(m.group(1).strip() or "-"):
            continue
        before = SQUARE.sub(" ", ANGLE.sub(" ", text[: m.start()])).split()
        if before:
            word = INCOMPLETE.sub("", DANDA.sub("", before[-1])).strip(".,?")
            if word and word not in heads:
                heads.append(word)
    return heads


def speaker_of(row: dict) -> str | None:
    """Vaani pseudonymous speaker id: ``speakerID`` when filled, else the id in the file name."""
    m = SPEAKER_IN_NAME.match(row["audio.path"] or "")
    from_name = f"SID_{m.group(2)}" if m else None
    sid = row.get("speakerID")
    if sid and from_name and sid != from_name:
        raise ValueError(f"speakerID {sid} disagrees with file name {row['audio.path']}")
    return sid or from_name


@dataclass
class Candidate:
    group: Group
    shard: str
    row_group: int
    index_in_group: int
    row_index: int
    meta: dict
    speaker: str
    reference: str
    terms: list[str] = field(default_factory=list)


def eligible(group: Group, row: dict) -> str | None:
    """Return the cleaned reference if the row qualifies for ``group``."""
    if row["isTranscriptionAvailable"] != "Yes" or row["language"] != group.vaani_language:
        return None
    if not (5.0 <= float(row["duration"] or 0) <= 20.0):
        return None
    raw = row["transcript"] or ""
    if EXCLUDE_TAGS.search(raw):
        return None
    if re.search(r"[0-9]", raw):  # guideline: numbers are written as words; digits mean a bad row
        return None
    ref = clean_transcript(raw)
    words = ref.split()
    if len(words) < 4:
        return None
    if group.code_mix:
        glosses = english_glosses(raw)
        if len(glosses) < 2 or len(glosses) / len(words) < 0.10:
            return None
    return ref


def scan_shard(fs: HfFileSystem, group: Group, path: str, log: Any) -> list[Candidate]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(fs.open(path, block_size=1 << 20, revision=REVISION))
    table = pf.read(columns=META_COLUMNS)
    rows = table.to_pylist()
    # flatten audio.path (pyarrow returns {'audio': {'path': ...}})
    for r in rows:
        r["audio.path"] = (r.pop("audio") or {}).get("path")
    bounds = []
    start = 0
    for i in range(pf.metadata.num_row_groups):
        n = pf.metadata.row_group(i).num_rows
        bounds.append((start, start + n))
        start += n
    out = []
    transcribed = 0
    for idx, r in enumerate(rows):
        transcribed += r["isTranscriptionAvailable"] == "Yes"
        ref = eligible(group, r)
        if ref is None:
            continue
        speaker = speaker_of(r)
        if speaker is None:
            continue
        rg = next(i for i, (a, b) in enumerate(bounds) if a <= idx < b)
        # domain terms (kn-en-mix): the spoken English loanwords that stand as whole words in the
        # reference, so entity accuracy can score them
        terms = (
            [t for t in gloss_heads(r["transcript"]) if t in ref.split()][:5]
            if group.code_mix
            else []
        )
        out.append(Candidate(group, path, rg, idx - bounds[rg][0], idx, r, speaker, ref, terms))
    log(
        f"  {rel(path)}: {len(rows)} rows, {transcribed} transcribed, "
        f"{len(out)} eligible, {len({c.speaker for c in out})} speakers"
    )
    return out


def consistent_speakers(cands: list[Candidate], log) -> list[Candidate]:
    """One Vaani speaker id per person, as far as the metadata can tell.

    Ids whose rows disagree on gender are dropped. Different ids with identical
    (district, gender, pincode, stay) may be one person registered twice, so only the id with the
    most eligible clips is kept from each such cluster (counting a person twice would make the
    speaker-grouped bootstrap CI too narrow).
    """
    genders: dict[str, set] = defaultdict(set)
    for c in cands:
        genders[c.speaker].add(c.meta["gender"])
    bad = {s for s, g in genders.items() if len(g) > 1}
    if bad:
        log(f"  dropped speaker ids with conflicting gender: {sorted(bad)}")
    clusters: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for c in cands:
        if c.speaker not in bad:
            m = c.meta
            clusters[(m["district"], m["gender"], m["pincode"], m["stay(years)"])][c.speaker] += 1
    keep = {max(ids, key=lambda s: (ids[s], s)) for ids in clusters.values()}
    merged = sum(len(ids) - 1 for ids in clusters.values())
    if merged:
        log(f"  {merged} speaker ids set aside: same district/gender/pincode/stay as a kept id")
    return [c for c in cands if c.speaker in keep]


def choose(cands: list[Candidate], per_group: int, max_per_speaker: int) -> list[Candidate]:
    """Round-robin over speakers so the set has as many distinct speakers as possible."""
    by_speaker: dict[str, list[Candidate]] = defaultdict(list)
    for c in cands:
        by_speaker[c.speaker].append(c)
    order = sorted(by_speaker, key=lambda s: (-len(by_speaker[s]), s))
    picked: list[Candidate] = []
    for rnd in range(max_per_speaker):
        for s in order:
            if len(picked) >= per_group:
                return picked
            if rnd < len(by_speaker[s]):
                picked.append(by_speaker[s][rnd])
    return picked


def to_wav16k(data: bytes) -> tuple[bytes, float]:
    samples, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    mono = samples.mean(axis=1)
    if rate != TARGET_RATE:
        g = np.gcd(int(rate), TARGET_RATE)
        mono = resample_poly(mono, TARGET_RATE // g, int(rate) // g)
    mono = np.clip(mono, -1.0, 1.0)
    buf = io.BytesIO()
    sf.write(buf, (mono * 32767).astype(np.int16), TARGET_RATE, subtype="PCM_16", format="WAV")
    return buf.getvalue(), len(mono) / TARGET_RATE


def fetch_audio(fs: HfFileSystem, picked: list[Candidate], dest: Path, log: Any) -> list[dict]:
    import pyarrow.parquet as pq

    rows = []
    by_rg: dict[tuple[str, int], list[Candidate]] = defaultdict(list)
    for c in picked:
        by_rg[(c.shard, c.row_group)].append(c)
    for (shard, rg), group_cands in sorted(by_rg.items()):
        pf = pq.ParquetFile(fs.open(shard, block_size=1 << 20, revision=REVISION))
        audio = pf.read_row_group(rg, columns=["audio"]).column("audio").to_pylist()
        log(f"  read audio row group {rg} of {rel(shard)} ({len(group_cands)} clips)")
        for c in group_cands:
            item = audio[c.index_in_group]
            if item["path"] != c.meta["audio.path"]:
                raise RuntimeError(f"row mismatch: {item['path']} != {c.meta['audio.path']}")
            wav, seconds = to_wav16k(item["bytes"])
            name = Path(c.meta["audio.path"]).stem + ".wav"
            (dest / name).write_bytes(wav)
            rows.append(
                {
                    "file": f"{c.group.label}/{name}",
                    "reference_text": c.reference,
                    "language": c.group.language,
                    "dialect_label": c.group.label,
                    "speaker_id": f"vaani-{c.speaker}",
                    "consent": "true",
                    "domain_terms": "|".join(c.terms),
                    "_source": {
                        "vaani_file": c.meta["audio.path"],
                        "shard": rel(shard),
                        "row_index": c.row_index,
                        "district": c.meta["district"],
                        "state": c.meta["state"],
                        "gender": c.meta["gender"],
                        "duration_s": round(seconds, 3),
                        "raw_transcript": c.meta["transcript"],
                    },
                }
            )
    return rows


def run_group(fs: HfFileSystem, group: Group, args, log) -> list[dict]:
    log(f"[{group.label}] {group.description}")
    shard_lists = {
        f: sorted(fs.ls(f"{REPO}/{f}", detail=False, revision=REVISION)) for f in group.folders
    }
    pool: list[Candidate] = []
    cands: list[Candidate] = []
    for i in range(args.max_shards):
        for folder in group.folders:
            if i < len(shard_lists[folder]):
                pool += scan_shard(fs, group, shard_lists[folder][i], log)
        cands = consistent_speakers(pool, log)
        speakers = {c.speaker for c in cands}
        enough_clips = len(choose(cands, args.per_group, args.max_per_speaker)) >= args.per_group
        if enough_clips and len(speakers) >= args.min_speakers:
            break
    picked = choose(cands, args.per_group, args.max_per_speaker)
    log(
        f"  picked {len(picked)} clips from {len({c.speaker for c in picked})} speakers "
        f"(pool {len(cands)} eligible clips, {len({c.speaker for c in cands})} speakers)"
    )
    dest = args.out / group.label
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*.wav"):
        old.unlink()
    return fetch_audio(fs, picked, dest, log)


# Author list of the Vaani citation (dataset card, "Citation"), joined into the BibTeX entry.
_AUTHORS = [
    "Sujith Pulikodan",
    "Abhayjeet Singh",
    "Agneedh Basu",
    "Nihar Desai",
    "Pavan Kumar J",
    "Pranav D Bhat",
    "Raghu Dharmaraju",
    "Ritika Gupta",
    "Sathvik Udupa",
    "Saurabh Kumar",
    "Sumit Sharma",
    "Vaibhav Vishwakarma",
    "Visruth Sanka",
    "Dinesh Tewari",
    "Harsh Dhand",
    "Amrita Kamat",
    "Sukhwinder Singh",
    "Shikhar Vashishth",
    "Partha Talukdar",
    "Raj Acharya",
    "Prasanta Kumar Ghosh",
]
CITATION = f"""@misc{{pulikodan2026vaanicapturinglanguagelandscape,
      title={{VAANI: Capturing the language landscape for an inclusive digital India}},
      author={{{" and ".join(_AUTHORS)}}},
      year={{2026}},
      eprint={{2603.28714}},
      archivePrefix={{arXiv}},
      primaryClass={{eess.AS}},
      url={{https://arxiv.org/abs/2603.28714}},
}}"""

SOURCES_HEAD = """# Sources: Vaani dialect evaluation set

Generated by `scripts/data/fetch_vaani.py`; do not edit by hand.

## Dataset and licence

- Dataset: **Vaani** by IISc Bangalore and ARTPARK, Hugging Face `ARTPARK-IISc/Vaani` (gated),
  dataset commit `{revision}`.
- Licence: **CC-BY-4.0** (https://creativecommons.org/licenses/by/4.0/). The clips are excerpts
  of Vaani recordings, resampled to 16 kHz mono 16-bit WAV, with the transcripts' tags stripped
  (below); nothing else is changed. Attribution: "Vaani dataset, IISc Bangalore and ARTPARK,
  CC-BY-4.0".
- Consent: per the Vaani paper (arXiv:2603.28714, section 5) every participant signed a consent
  form enabling open-source distribution; `consent=true` in `manifest.csv` records that
  dataset-level consent, not a consent we collected.
- Speaker ids are Vaani's pseudonymous ids (`speakerID`, or the id in the Vaani file name when
  `speakerID` is empty; both agree wherever both exist), prefixed `vaani-`.

Citation:

```
{citation}
```

## Groups

| group | lang | Vaani folders scanned | clips | speakers | districts of the clips | audio s |
|---|---|---|---|---|---|---|
{group_rows}

The dialect label is the **district where the speaker lives** (Vaani `district`; Vaani also lists
each speaker's `stay(years)` there), not a linguist's judgement of the accent. kn-en-mix is
Bangalore Kannada whose transcript marks at least 2 English words, making up at least 10 % of
the words.
hi-standard: Lucknow is scanned first, but its first shard holds 1 transcribed row (not
eligible), so the Hindi clips came from New Delhi (see the fetch log).

## Selection rules

`isTranscriptionAvailable == Yes`; Vaani `language` is the group language (Kannada / Hindi);
5-20 s; no `[unintelligible]`, `[inaudible]` or `<UNKNOWN_SEGMENT>` in the transcript; no digits;
at least 4 words after cleaning. Speakers are taken round-robin (max 4 clips each). Speaker ids
with conflicting gender are dropped, and of several ids with identical (district, gender,
pincode, stay) only one is kept, so one person is not counted twice in the speaker-grouped
bootstrap. Shards are read in order from shard 0 until a group has enough clips.

## Transcription convention and how tags were stripped

Source: Vaani Audio Transcription Guidelines (arXiv:2603.28714, Appendix A), plus tags seen in
the data that the appendix does not list (`<noise>...</noise>`, `<talking>`, `<pause>`,
Latin-script braces after English words).

| Vaani notation | meaning | in `reference_text` |
|---|---|---|
| `[unintelligible]` `[inaudible]` `<UNKNOWN_SEGMENT>` | not understood or heard | excluded |
| `[noise]` `[breathing]` `[laugh]` `[static]` ... | non-speech events | removed |
| `<noise> ... </noise>` `<talking>` `<pause>` | span / pause markers | markers removed |
| `word {{gloss}}` | spoken word + correct or Latin spelling | brace removed, word kept |
| `word{{gloss}}suffix` | one spoken word with a gloss inside | rejoined: `wordsuffix` |
| trailing `--` or a dash | incomplete utterance | removed |
| purna viram (danda or a vertical bar) | sentence end | replaced by a space |

Brace example: `ಗ್ರೀನ್ {{green}}` keeps `ಗ್ರೀನ್`; `रंग बरंगे{{बिरंगे}}` keeps `बरंगे`, the word as
spoken. So references are verbatim native script with **English loanwords in native script**
(`ಕಲರ್`, `कलर`), as Vaani's transcribers wrote them. Commas and full stops stay (the pipeline's
normaliser strips punctuation). `domain_terms` (kn-en-mix only) are the native-script forms of
the English words the transcript marks, when they stand as whole words in the reference.

## Clips (Vaani row ids)

The Vaani file name is the Vaani row id; shard and row index locate it in the dataset commit
above. `sources.json` also has the raw transcript, gender and duration of every clip.

| file | speaker_id | district | shard | row |
|---|---|---|---|---|
{clip_rows}

## Fetch log

```
{fetch_log}
```
"""

REVIEW_HEAD = """# Spot-check: Vaani dialect clips

Five clips per group (every fourth clip in file order, so every district shows up) for the owner
to listen to and compare with the reference text: does the accent fit the group, does the text
match the audio? Full list: `manifest.csv`; raw Vaani transcripts: `sources.json`.
"""


def write_docs(out: Path, rows: list[dict], fetch_log: str) -> None:
    """SOURCES.md (attribution, convention, per-clip Vaani ids) and REVIEW.md (spot-check table)."""
    by_group: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_group[r["dialect_label"]].append(r)
    group_rows = []
    for g in GROUPS:
        rs = by_group.get(g.label, [])
        counts: dict[str, int] = defaultdict(int)
        for r in rs:
            counts[r["_source"]["district"]] += 1
        folders = ", ".join(f.removeprefix("audio/") for f in g.folders)
        districts = ", ".join(f"{d} {n}" for d, n in sorted(counts.items()))
        speakers = len({r["speaker_id"] for r in rs})
        seconds = sum(r["_source"]["duration_s"] for r in rs)
        group_rows.append(
            f"| {g.label} | {g.language} | {folders} | {len(rs)} | {speakers} | {districts} "
            f"| {seconds:.0f} |"
        )
    clip_rows = [
        f"| {r['file']} | {r['speaker_id']} | {r['_source']['district']} "
        f"| {r['_source']['shard'].removeprefix('audio/')} | {r['_source']['row_index']} |"
        for r in rows
    ]
    (out / "SOURCES.md").write_text(
        SOURCES_HEAD.format(
            revision=REVISION,
            citation=CITATION,
            group_rows="\n".join(group_rows),
            clip_rows="\n".join(clip_rows),
            fetch_log=fetch_log.rstrip(),
        ),
        encoding="utf-8",
    )
    review = [REVIEW_HEAD]
    for g in GROUPS:
        review += [
            f"## {g.label}: {g.description}",
            "",
            "| file | speaker | s | reference text |",
            "|---|---|---|---|",
        ]
        review += [
            f"| data/dialect/vaani/{r['file']} | {r['speaker_id']} "
            f"| {r['_source']['duration_s']:.1f} | {r['reference_text']} |"
            for r in by_group.get(g.label, [])[::4][:5]
        ]
        review += ["", "OK? [ ] accent  [ ] transcript", ""]
    (out / "REVIEW.md").write_text("\n".join(review), encoding="utf-8")


def load_rows(out: Path) -> list[dict]:
    with (out / "manifest.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    sources = {s["file"]: s for s in json.loads((out / "sources.json").read_text(encoding="utf-8"))}
    for r in rows:
        r["_source"] = sources[r["file"]]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=Path("data/dialect/vaani"))
    ap.add_argument("--per-group", type=int, default=22)
    ap.add_argument("--max-per-speaker", type=int, default=4)
    ap.add_argument("--min-speakers", type=int, default=5)
    ap.add_argument("--max-shards", type=int, default=6, help="per district folder")
    ap.add_argument("--groups", nargs="*", default=[g.label for g in GROUPS])
    ap.add_argument(
        "--docs-only",
        action="store_true",
        help="rewrite SOURCES.md / REVIEW.md from manifest.csv + sources.json (no network)",
    )
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.docs_only:
        write_docs(
            args.out, load_rows(args.out), (args.out / "fetch_log.txt").read_text(encoding="utf-8")
        )
        return
    log_path = args.out / "fetch_log.txt"
    log_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg, flush=True)
        log_lines.append(msg)

    from huggingface_hub import HfFileSystem

    fs = HfFileSystem()  # reads HF_TOKEN from the environment
    rows: list[dict] = []
    for group in GROUPS:
        if group.label in args.groups:
            rows += run_group(fs, group, args, log)
    rows.sort(key=lambda r: r["file"])
    cols = [
        "file",
        "reference_text",
        "language",
        "dialect_label",
        "speaker_id",
        "consent",
        "domain_terms",
    ]
    with (args.out / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (args.out / "sources.json").write_text(
        json.dumps(
            [{"file": r["file"], "speaker_id": r["speaker_id"], **r["_source"]} for r in rows],
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    write_docs(args.out, rows, log_path.read_text(encoding="utf-8"))
    print(f"wrote {len(rows)} clips -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
