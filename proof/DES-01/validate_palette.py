#!/usr/bin/env python3
"""Validate docs/design/tokens.css: WCAG contrast + colour-vision-deficiency separation.

Run: python3 -I proof/DES-01/validate_palette.py
Reads tokens.css (light = :root, dark = [data-theme="dark"]), prints a report, exits 1 on failure.

CVD simulation: Machado, Oliveira & Fernandes (2009), severity 1.0, applied in linear sRGB.
Distance: CIE76 deltaE in Lab (D65). Neighbouring score steps must stay >= MIN_DE_CVD under
protanopia, deuteranopia and tritanopia, OR differ in lightness by >= MIN_DL (greyscale-safe).
"""
import re
import sys
from pathlib import Path

import numpy as np

TOKENS = Path(__file__).resolve().parents[2] / "docs" / "design" / "tokens.css"
MIN_DE_CVD = 14.0
MIN_DL = 9.0

MACHADO = {
    "protan": np.array([[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]),
    "deutan": np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]),
    "tritan": np.array([[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]),
}


def parse_blocks(css: str):
    light = re.search(r":root\s*\{(.*?)\n\}", css, re.S).group(1)
    dark = re.search(r'\[data-theme="dark"\]\s*\{(.*?)\n\}', css, re.S).group(1)
    def vars_of(b):
        return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", b)}
    lv = vars_of(light)
    dv = dict(lv)
    dv.update(vars_of(dark))
    return lv, dv


def hex_rgb(h):
    h = h.strip().lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)]) / 255.0


def lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def delin(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def lum(h):
    r, g, b = lin(hex_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def to_lab(rgb_lin):
    M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = M @ rgb_lin
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def lab_of(h, mode=None):
    c = lin(hex_rgb(h))
    if mode:
        c = np.clip(MACHADO[mode] @ c, 0, 1)
    return to_lab(c)


def de(a, b, mode=None):
    return float(np.linalg.norm(lab_of(a, mode) - lab_of(b, mode)))


def main():
    css = TOKENS.read_text()
    fails = []
    for theme, v in zip(("light", "dark"), parse_blocks(css)):
        print(f"\n===== {theme.upper()} =====")
        # 1. text contrast
        text_pairs = [
            ("--fg", "--bg-canvas", 7.0), ("--fg", "--bg-surface", 7.0),
            ("--fg-muted", "--bg-surface", 4.5), ("--fg-muted", "--bg-canvas", 4.5),
            ("--fg-subtle", "--bg-surface", 4.5), ("--fg-subtle", "--bg-canvas", 4.5),
            ("--accent-fg", "--bg-surface", 4.5), ("--accent-fg", "--bg-canvas", 4.5),
            ("--accent-on", "--accent", 4.5),
            ("--pass-fg", "--pass-tint", 4.5), ("--warn-fg", "--warn-tint", 4.5),
            ("--fail-fg", "--fail-tint", 4.5), ("--critical-on", "--critical", 4.5),
            ("--pass-fg", "--bg-surface", 4.5), ("--warn-fg", "--bg-surface", 4.5),
            ("--fail-fg", "--bg-surface", 4.5),
        ]
        for i in range(1, 6):
            text_pairs.append((f"--score-{i}-on", f"--score-{i}", 4.5))
        for fg, bg, need in text_pairs:
            c = contrast(v[fg], v[bg])
            ok = c >= need
            print(f"  {'ok  ' if ok else 'FAIL'} {fg:16s} on {bg:16s} {c:5.2f}:1 (need {need})")
            if not ok:
                fails.append((theme, fg, bg, c))
        # 2. non-text: borders vs surface, score steps vs surface
        for k in ("--border-strong",):
            c = contrast(v[k], v["--bg-surface"])
            ok = c >= 3.0
            print(f"  {'ok  ' if ok else 'FAIL'} {k} vs surface {c:.2f}:1 (WCAG 1.4.11 need 3.0)")
            if not ok:
                fails.append((theme, k, "surface", c))
        for i in range(1, 6):
            c = contrast(v[f"--score-{i}"], v["--bg-surface"])
            ok = c >= 1.5
            print(f"  {'ok  ' if ok else 'FAIL'} --score-{i} vs surface {c:.2f}:1 (non-text >= 1.5 advisory, labels carry meaning)")
        # 3. CVD separation of neighbouring score steps
        steps = [v[f"--score-{i}"] for i in range(1, 6)]
        for i in range(4):
            a, b = steps[i], steps[i + 1]
            dl = abs(lab_of(a)[0] - lab_of(b)[0])
            row = [f"{m}={de(a, b, m):5.1f}" for m in MACHADO]
            ok = all(de(a, b, m) >= MIN_DE_CVD for m in MACHADO) or dl >= MIN_DL
            print(f"  {'ok  ' if ok else 'FAIL'} score-{i + 1}->{i + 2}: normal={de(a, b):5.1f} " + " ".join(row) + f" dL={dl:4.1f}")
            if not ok:
                fails.append((theme, f"score {i + 1}->{i + 2}", "cvd", dl))
        # 4. verdict triple (pass/warn/fail solid) separation under CVD
        trip = [v["--pass"], v["--warn"], v["--fail"]]
        names = ["pass", "warn", "fail"]
        for i in range(3):
            for j in range(i + 1, 3):
                a, b = trip[i], trip[j]
                dl = abs(lab_of(a)[0] - lab_of(b)[0])
                ok = all(de(a, b, m) >= MIN_DE_CVD for m in MACHADO) or dl >= MIN_DL
                row = " ".join(f"{m}={de(a, b, m):5.1f}" for m in MACHADO)
                print(f"  {'ok  ' if ok else 'FAIL'} verdict {names[i]} vs {names[j]}: {row} dL={dl:4.1f}")
                if not ok:
                    fails.append((theme, f"verdict {names[i]}/{names[j]}", "cvd", dl))
    print("\nRESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    for f in fails:
        print("  ", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
