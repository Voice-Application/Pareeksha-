"""Pure chunking strategies. Every chunk satisfies doc[start:end] == text."""

import re
from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise

from pareeksha.schemas.rag import ChunkingConfig

_HEADING = re.compile(r"^#{1,6}[ \t]+", re.MULTILINE)
_PARA = re.compile(r"\n[ \t]*\n\s*")
_SENT = re.compile(r"(?<=[.!?।॥])\s+")
_WS = re.compile(r"\s+")
_LEVELS = (_PARA, _SENT, _WS)
_TOKEN_SPLIT = re.compile(r"[\s\.,;:!?\"'()\[\]{}<>/\\|\-–—।॥]+")


@dataclass(frozen=True)
class Chunk:
    text: str
    start: int
    end: int
    parent_start: int
    parent_end: int


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(text.lower()) if t]


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def _cuts(text: str, s: int, e: int, rx: re.Pattern[str]) -> list[int]:
    out = []
    for m in rx.finditer(text, s, e):
        pos = m.start() if rx is _HEADING else m.end()
        if s < pos < e:
            out.append(pos)
    return out


def _spans(text: str, s: int, e: int, cuts: list[int]) -> list[tuple[int, int]]:
    bounds = [s, *cuts, e]
    spans = []
    for a, b in pairwise(bounds):
        a, b = _trim(text, a, b)
        if a < b:
            spans.append((a, b))
    return spans


def _parent_bounds(text: str) -> list[int]:
    cuts = _cuts(text, 0, len(text), _HEADING)
    if not cuts:
        cuts = _cuts(text, 0, len(text), _PARA)
    return [0, *cuts, len(text)]


def _make(text: str, bounds: list[int], s: int, e: int) -> Chunk | None:
    s, e = _trim(text, s, e)
    if s >= e:
        return None
    i = bisect_right(bounds, s) - 1
    j = bisect_right(bounds, e - 1) - 1
    return Chunk(text[s:e], s, e, bounds[i], bounds[j + 1])


def _fixed(text: str, cfg: ChunkingConfig, bounds: list[int]) -> list[Chunk]:
    n, size = len(text), cfg.size
    slack = max(1, size // 10)
    out: list[Chunk] = []
    pos = 0
    while pos < n:
        end = min(pos + size, n)
        if end < n:
            for i in range(end, max(pos, end - slack) - 1, -1):
                if text[i].isspace() or text[i - 1].isspace():
                    end = i
                    break
        if c := _make(text, bounds, pos, end):
            out.append(c)
        if end >= n:
            break
        nxt = end - cfg.overlap
        pos = nxt if nxt > pos else end
    return out


def _split(text: str, s: int, e: int, level: int, size: int) -> list[tuple[int, int]]:
    s, e = _trim(text, s, e)
    if s >= e:
        return []
    if e - s <= size:
        return [(s, e)]
    if level == len(_LEVELS):  # unbroken run: hard split
        return [(i, min(i + size, e)) for i in range(s, e, size)]
    out: list[tuple[int, int]] = []
    for a, b in _spans(text, s, e, _cuts(text, s, e, _LEVELS[level])):
        out += _split(text, a, b, level + 1, size)
    return out


def _recursive(text: str, cfg: ChunkingConfig, bounds: list[int]) -> list[Chunk]:
    size, overlap = cfg.size, cfg.overlap
    sections = _spans(text, 0, len(text), _cuts(text, 0, len(text), _HEADING))
    out: list[Chunk] = []
    for ss, se in sections:
        cur_s = cur_e = last_ps = -1
        for ps, pe in _split(text, ss, se, 0, size):
            if cur_s < 0:
                cur_s, cur_e, last_ps = ps, pe, ps
            elif pe - cur_s <= size:
                cur_e, last_ps = pe, ps
            else:
                if c := _make(text, bounds, cur_s, cur_e):
                    out.append(c)
                cs = ps
                if overlap:
                    cs = max(last_ps, cur_e - overlap, pe - size)
                    if cs < ps and not text[cs - 1].isspace():
                        # snap forward to a word start; no space before ps means no carry
                        m = _WS.search(text, cs, ps)
                        cs = m.end() if m else ps
                cur_s, cur_e, last_ps = cs, pe, ps
        if cur_s >= 0 and (c := _make(text, bounds, cur_s, cur_e)):
            out.append(c)
    return out


def _sentence_window(text: str, cfg: ChunkingConfig) -> list[Chunk]:
    n = len(text)
    cuts = sorted(set(_cuts(text, 0, n, _PARA) + _cuts(text, 0, n, _SENT)))
    sents = _spans(text, 0, n, cuts)
    out = []
    for i, (s, e) in enumerate(sents):
        ps = sents[max(0, i - cfg.window)][0]
        pe = sents[min(len(sents) - 1, i + cfg.window)][1]
        out.append(Chunk(text[s:e], s, e, ps, pe))
    return out


def chunk_document(text: str, cfg: ChunkingConfig) -> list[Chunk]:
    if cfg.strategy == "sentence_window":
        return _sentence_window(text, cfg)
    bounds = _parent_bounds(text)
    if cfg.strategy == "fixed":
        return _fixed(text, cfg, bounds)
    return _recursive(text, cfg, bounds)
