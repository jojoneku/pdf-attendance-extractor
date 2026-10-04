"""
Tests for the Filipino given-name sex inference module (backend/gender.py).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from gender import (  # noqa: E402
    LEXICON_PATH,
    MIN_CONFIDENCE,
    Lexicon,
    infer_sex,
    normalize_tokens,
)


def sex(*args, **kwargs):
    return infer_sex(*args, **kwargs)[0]


# ---------------------------------------------------------------------------
# Lexicon file
# ---------------------------------------------------------------------------
def test_lexicon_file_is_aggregated_and_loadable():
    data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    assert {"first", "later"} <= set(data)
    lex = Lexicon.from_json(LEXICON_PATH)
    assert lex.first["JOHN"][0] > lex.first["JOHN"][1]  # [male, female]
    # every entry is a [male, female] count pair with total >= 2
    for table in (data["first"], data["later"]):
        for name, (m, f) in table.items():
            assert name.isalpha() and m + f >= 1
    # aggregated counts only: no spaces (i.e. no full names) in any key
    assert all(" " not in k for k in list(data["first"]) + list(data["later"]))


# ---------------------------------------------------------------------------
# Common names
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["JOHN", "Mark", "CHRISTIAN", "Kent", "JHON", "JUN", "Rey", "RHEY", "Jhun"])
def test_common_male_names(name):
    s, conf, _ = infer_sex(name)
    assert s == "M" and conf >= 0.8


@pytest.mark.parametrize("name", ["MARY", "Hannah", "Jane", "Joy", "Grace", "Mae", "Ann", "Rose", "PRINCESS"])
def test_common_female_names(name):
    s, conf, _ = infer_sex(name)
    assert s == "F" and conf >= 0.8


def test_output_shape_and_empty_input():
    s, conf, reason = infer_sex("JOHN")
    assert s in ("M", "F", "") and 0.0 <= conf <= 1.0 and isinstance(reason, str)
    assert infer_sex("") == ("", 0.0, "no name")
    assert sex("   ") == ""


def test_normalisation_handles_case_punctuation_accents():
    assert normalize_tokens("  ni\u00f1a-Marie. ") == ["NINA", "MARIE"]
    assert normalize_tokens("NI\ufffdA") == ["NINA"]  # mojibake for N-tilde
    assert sex("john paul") == "M"
    assert sex("Ni\u00f1a") == "F"


# ---------------------------------------------------------------------------
# "MA." prefix (Maria)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["MA. LUISA", "MA LUISA", "Ma. Cristina", "MA.CRISTINA", "MARIA CRISTINA"])
def test_ma_prefix_is_female(name):
    s, conf, reason = infer_sex(name)
    assert s == "F" and conf >= 0.9


def test_ma_prefix_with_separate_fields_and_unseen_following_name():
    # even if the name after "MA." is unknown / looks male, Ma. is a strong F signal
    assert sex("MA.", full_given="MA. GIERAMEE CADORNA") == "F"
    assert sex("MA. ZZQORP") == "F"


# ---------------------------------------------------------------------------
# Compound names
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name, expected",
    [
        ("JOHN PAUL", "M"),
        ("JOHN MARK", "M"),
        ("MARY JOY", "F"),
        ("KYLA JADE", "F"),
        ("ROSE MAE", "F"),
        ("MARK JUSTINE", "M"),
        ("JAN MARIE", "F"),
        ("REY ANN", "F"),  # male-looking first token, clearly female second
    ],
)
def test_compound_names(name, expected):
    assert sex(name) == expected


def test_compound_name_via_full_given_equals_first_name_only():
    assert infer_sex("KYLA", full_given="KYLA JADE TALABOC")[0] == "F"
    assert infer_sex("JOHN", "SANTOS", "JOHN PAUL SANTOS")[0] == "M"


def test_middle_name_surname_does_not_flip_result():
    # the middle name is the mother's maiden surname and must not be used
    assert sex("JOHN", "MARIA") == "M"
    assert sex("MARY", "JOHN") == "F"


# ---------------------------------------------------------------------------
# Suffix (Jr./Sr./III)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sfx", ["JR.", "Jr", "SR.", "III"])
def test_suffix_gives_male_with_high_confidence_for_unknown_name(sfx):
    s, conf, reason = infer_sex("ZZQORP", suffix=sfx)
    assert s == "M" and conf >= 0.9 and "suffix" in reason


def test_suffix_inside_given_string():
    assert sex("ZZQORP", full_given="ZZQORP JR.") == "M"


def test_suffix_ii_alone_is_not_decisive():
    assert sex("ZZQORP", suffix="II") == ""


def test_clearly_female_name_beats_suffix():
    # real data contains women recorded with "JR." / "II"
    assert sex("MARIA", suffix="JR.") == "F"
    assert sex("HANNAH", suffix="II") == "F"


# ---------------------------------------------------------------------------
# Unisex names -> low confidence alone, resolved by companion tokens
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["KIM", "JADE", "ALEX"])
def test_unisex_names_never_high_confidence_alone(name):
    s, conf, _ = infer_sex(name)
    assert conf < 0.8
    if conf < MIN_CONFIDENCE:
        assert s == ""


def test_unisex_resolved_by_other_token():
    assert sex("ANGEL MAE") == "F"
    assert sex("JADE MARK") == "M"
    assert sex("KIM JOHN") == "M"
    assert sex("ARIEL") == "M"  # Ariel is male in the Philippines


# ---------------------------------------------------------------------------
# Unseen names -> morphology fallback (low confidence)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["Jessabelle", "Marilynette", "Xyloelle", "Zarolyn", "Quennice"])
def test_unseen_feminine_endings(name):
    s, conf, reason = infer_sex(name)
    assert s == "F" and "morphology" in reason
    assert conf < 0.99


@pytest.mark.parametrize("name", ["Zandrito", "Bellard", "Quinnert", "Zymmar", "Dexrex"])
def test_unseen_masculine_endings(name):
    s, conf, reason = infer_sex(name)
    assert s == "M" and "morphology" in reason


def test_gibberish_is_undetermined():
    s, conf, _ = infer_sex("ZZQORP")
    assert s == "" and conf < MIN_CONFIDENCE


# ---------------------------------------------------------------------------
# Custom lexicon + CLI
# ---------------------------------------------------------------------------
def test_custom_lexicon_overrides_default():
    lex = Lexicon({"ZZQORP": [0, 9]}, {})
    assert sex("ZZQORP", lexicon=lex) == "F"


def test_cli_prints_sex_confidence_reason():
    out = subprocess.run(
        [sys.executable, "-m", "backend.gender", "MA. LUISA", "SANTOS"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    s, conf, reason = out.split(",", 2)
    assert s == "F" and 0.9 <= float(conf) <= 1.0 and reason

    out = subprocess.run(
        [sys.executable, "-m", "backend.gender", "ROLANDO", "", "--suffix", "JR."],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out.startswith("M,")


# ---------------------------------------------------------------------------
# Calibration, later-token dominance, curated international names, -AH
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["Zarolyn", "Zandrito", "Quennice", "Blorvana", "Xyloelle"])
def test_morphology_only_confidence_is_capped(name):
    s, conf, reason = infer_sex(name)
    assert conf <= 0.75


def test_rare_lexicon_hit_is_capped():
    lex = Lexicon({"ZZQORP": [0, 2]}, {})
    s, conf, _ = infer_sex("ZZQORP", lexicon=lex)
    assert s == "F" and conf <= 0.85
    lex = Lexicon({"ZZQORP": [0, 20]}, {})
    assert infer_sex("ZZQORP", lexicon=lex)[1] > 0.85


def test_known_later_token_dominates_unseen_first_token_morphology():
    # first token "ALFA" ends in -a (morphology says F) but ROMEL is a strong M hit
    assert infer_sex("ALFA ROMEL")[0] == "M"
    lex = Lexicon({"JOHN": [50, 0]}, {"PAUL": [40, 0]})
    s, conf, _ = infer_sex("ZORBELLA PAUL", lexicon=lex)  # -ELLA / -A would say F
    assert s == "M"
    assert infer_sex("KYNE REYNARD")[0] == "M"
    assert infer_sex("RAYNNE REXXAR")[0] == "M"
    assert infer_sex("MIKHAIL ADDESON")[0] == "M"
    assert infer_sex("DUSTINE LEVI")[0] == "M"


@pytest.mark.parametrize(
    "name",
    ["JEREMIAH", "HARRY", "LARRY", "WARREN", "JULIAN NOLI", "RAJAH AMIR", "HOSHEA FREY", "JESSEE",
     "ELDREN", "NOAH", "ELIJAH", "ISAIAH", "JOSIAH", "RAJAH"],
)
def test_curated_international_male_names(name):
    s, conf, _ = infer_sex(name)
    assert s == "M" and conf >= 0.8


@pytest.mark.parametrize("name", ["ESTER", "ESTHER", "ANJIE", "SACHI ALEXIS", "SARAH", "HANNAH", "LEAH"])
def test_curated_international_female_names(name):
    assert infer_sex(name)[0] == "F"


def test_ah_ending_is_not_a_female_signal():
    # unseen -AH names must not be pushed to F by morphology
    s, conf, reason = infer_sex("Zemmiah")
    assert s != "F"
    from gender import morphology_prior

    assert morphology_prior("ZAMRAH") == (0.0, "")
    assert infer_sex("JEREMIAH")[0] == "M"
