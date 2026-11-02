"""DIALECT-02: Vaani clip selection (scripts/data/fetch_vaani.py), offline parts only."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pareeksha.dialect.manifest import clip_duration_ms, validate_row

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "data" / "fetch_vaani.py"
_spec = importlib.util.spec_from_file_location("fetch_vaani", SCRIPT)
assert _spec and _spec.loader
fv = importlib.util.module_from_spec(_spec)
sys.modules["fetch_vaani"] = fv
_spec.loader.exec_module(fv)

KN = next(g for g in fv.GROUPS if g.label == "kn-mysuru")
MIX = next(g for g in fv.GROUPS if g.label == "kn-en-mix")
HI = next(g for g in fv.GROUPS if g.label == "hi-standard")


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        # real Vaani transcripts (Mysore / Bangalore / New Delhi shard 0)
        (
            "<noise>ಇದೊಂದು ದೇವಸ್ಥಾನವಾಗಿದ್ದು ಸುಂದರವಾಗಿ ಕಾಣುತ್ತಿದೆ.</noise>",
            "ಇದೊಂದು ದೇವಸ್ಥಾನವಾಗಿದ್ದು ಸುಂದರವಾಗಿ ಕಾಣುತ್ತಿದೆ.",
        ),
        ("ನಮ ಅಜ್ಜಿಗೆ ಸುಸ್ತ್ [noise] ಆಗತೈತೆ [breathing] ನಾವೆಲ್ಲ", "ನಮ ಅಜ್ಜಿಗೆ ಸುಸ್ತ್ ಆಗತೈತೆ ನಾವೆಲ್ಲ"),
        ("ಅಲ್ಲಿ ಗ್ರೀನ್ {green} ಕಲರ್ ಸಹ ಕಾಣಿಸ್ತಾ ಇದೆ ।ಎದಿನೆಂಟು", "ಅಲ್ಲಿ ಗ್ರೀನ್ ಕಲರ್ ಸಹ ಕಾಣಿಸ್ತಾ ಇದೆ ಎದಿನೆಂಟು"),
        ("ಒಂದು ಸ್ಕೂಲ್{school} ಪ್ಲೇಗ್ರೌಂಡ್{playground}ನಲ್ಲಿ ಎಲ್ಲಾ", "ಒಂದು ಸ್ಕೂಲ್ ಪ್ಲೇಗ್ರೌಂಡ್ನಲ್ಲಿ ಎಲ್ಲಾ"),
        ("ಇಲ್ಲಿ ಒಂದು <pause> ಬೋರ್ಡ್{board} ಅಲ್ಲಿ", "ಇಲ್ಲಿ ಒಂದು ಬೋರ್ಡ್ ಅಲ್ಲಿ"),
        ("रंग बरंगे{बिरंगे} कपड़े पहने", "रंग बरंगे कपड़े पहने"),
        ("ಮನೆಯವರು ಹಾಕ--", "ಮನೆಯವರು ಹಾಕ"),
        ("ಕ್ರೀಮ್ {cream} ಕಲರ್ {color} ಪ್ಯಾಂಟ್ {pant}--", "ಕ್ರೀಮ್ ಕಲರ್ ಪ್ಯಾಂಟ್"),
    ],
)
def test_clean_transcript_strips_vaani_tags(raw: str, clean: str) -> None:
    assert fv.clean_transcript(raw) == clean


def test_english_glosses_and_spoken_loanwords() -> None:
    raw = "ಇದು ಮಸೀದಿ <pause>ಮಸೀದಿ ಲೈಟಿಂಗ್ಸ್ {lightings} ಎಲ್ಲ ಗ್ರೀನ್ {green} ಕಲರ್ {colour} ಇದೆ."
    assert fv.english_glosses(raw) == ["lightings", "green", "colour"]
    assert fv.gloss_heads(raw) == ["ಲೈಟಿಂಗ್ಸ್", "ಗ್ರೀನ್", "ಕಲರ್"]
    # a native-script brace is a spelling correction, not an English word
    assert fv.english_glosses("रंग बरंगे{बिरंगे} कपड़े") == []


def _row(**kw: object) -> dict[str, object]:
    base = {
        "isTranscriptionAvailable": "Yes",
        "language": "Kannada",
        "duration": 8.0,
        "transcript": "ಇದು ಒಂದು ದೊಡ್ಡ ಮರ ಇದೆ",
        "audio.path": "IISc_VaaniProject_S_Karnataka_Mysore_114258_11815471_GENERIC_0573_0_9.wav",
        "speakerID": None,
    }
    return {**base, **kw}


def test_eligibility_rules() -> None:
    assert fv.eligible(KN, _row()) == "ಇದು ಒಂದು ದೊಡ್ಡ ಮರ ಇದೆ"
    assert fv.eligible(KN, _row(isTranscriptionAvailable="No")) is None
    assert fv.eligible(KN, _row(language="Hindi")) is None
    assert fv.eligible(HI, _row()) is None
    assert fv.eligible(KN, _row(duration=4.9)) is None
    assert fv.eligible(KN, _row(duration=20.1)) is None
    assert fv.eligible(KN, _row(transcript="ಇದು [unintelligible] ದೊಡ್ಡ ಮರ ಇದೆ")) is None
    assert fv.eligible(KN, _row(transcript="ಇದು [inaudible] ದೊಡ್ಡ ಮರ ಇದೆ")) is None
    assert fv.eligible(KN, _row(transcript="<UNKNOWN_SEGMENT> ಇದು ದೊಡ್ಡ ಮರ ಇದೆ")) is None
    assert fv.eligible(KN, _row(transcript="ಇದು 2 ದೊಡ್ಡ ಮರ ಇದೆ")) is None
    assert fv.eligible(KN, _row(transcript="<noise> ಮರ ಇದೆ </noise>")) is None  # < 4 words


def test_code_mix_needs_two_english_words_and_ten_percent() -> None:
    one = "ಇದು ಒಂದು ಕಾರ್ {car} ತುಂಬಾ ದೊಡ್ಡದಾಗಿ ಕಾಣುತ್ತಿದೆ"
    two = "ಇದು ಒಂದು ಕಾರ್ {car} ಗ್ರೀನ್ {green} ಕಲರ್ ಇದೆ"
    assert fv.eligible(MIX, _row(transcript=one)) is None
    assert fv.eligible(MIX, _row(transcript=two)) == "ಇದು ಒಂದು ಕಾರ್ ಗ್ರೀನ್ ಕಲರ್ ಇದೆ"
    sparse = "ಕಾರ್ {car} ಗ್ರೀನ್ {green} " + " ".join(["ಮರ"] * 19)  # 2 of 21 words < 10 %
    assert fv.eligible(MIX, _row(transcript=sparse)) is None


def test_speaker_id_from_column_or_file_name() -> None:
    assert fv.speaker_of(_row()) == "SID_114258"
    assert fv.speaker_of(_row(speakerID="SID_114258")) == "SID_114258"
    k = "IISc_VaaniProject_K_Karnataka_Bangalore_Bangalore844425030134186_050_X_01744_0_9.wav"
    assert fv.speaker_of(_row(**{"audio.path": k})) == "SID_Bangalore844425030134186"
    with pytest.raises(ValueError, match="disagrees"):
        fv.speaker_of(_row(speakerID="SID_999"))


def _cand(speaker: str, gender: str = "Female", pincode: int = 1, n: int = 0) -> object:
    meta = {"district": "Mysore", "gender": gender, "pincode": pincode, "stay(years)": "NA(20)"}
    return fv.Candidate(KN, "shard", 0, n, n, meta, speaker, "ref")


def test_speaker_dedup_and_round_robin() -> None:
    a = [_cand("A", pincode=1, n=i) for i in range(5)]
    b = [_cand("B", pincode=1, n=10 + i) for i in range(2)]  # same demographics as A: set aside
    c = [_cand("C", pincode=2, n=20), _cand("C", gender="Male", pincode=2, n=21)]  # gender clash
    d = [_cand("D", pincode=3, n=30 + i) for i in range(3)]
    kept = fv.consistent_speakers(a + b + c + d, lambda _msg: None)
    assert {x.speaker for x in kept} == {"A", "D"}
    picked = fv.choose(kept, per_group=5, max_per_speaker=2)
    assert [x.speaker for x in picked] == ["A", "D", "A", "D"]  # capped at 2 per speaker


def test_to_wav16k_output_is_accepted_by_the_manifest_importer() -> None:
    rate = 48_000
    t = np.arange(int(rate * 6.0)) / rate
    stereo = np.stack([0.3 * np.sin(2 * np.pi * 220 * t)] * 2, axis=1).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, stereo, rate, format="WAV", subtype="FLOAT")
    wav, seconds = fv.to_wav16k(buf.getvalue())
    info = sf.info(io.BytesIO(wav))
    assert (info.samplerate, info.channels, info.subtype) == (16_000, 1, "PCM_16")
    assert seconds == pytest.approx(6.0, abs=0.01)
    assert clip_duration_ms(wav) == pytest.approx(6000, abs=10)


def test_committed_manifest_rows_are_valid() -> None:
    """The committed Vaani manifest passes the importer's row validation (consent, language)."""
    import csv

    manifest = SCRIPT.parents[2] / "data" / "dialect" / "vaani" / "manifest.csv"
    with manifest.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 100
    for row in rows:
        parsed = validate_row(row)
        assert not isinstance(parsed, str), parsed
        assert (manifest.parent / row["file"]).is_file()
