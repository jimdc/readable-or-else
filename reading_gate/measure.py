"""Readability measurement.

This module is a thin wrapper over textstat (https://github.com/textstat/textstat,
MIT). Readability formulas (Flesch-Kincaid, SMOG, Gunning Fog, Coleman-Liau, ARI,
Fernandez-Huerta, Szigriszt-Pazos) are peer-reviewed, validated math with subtle
language-specific constants (syllable-counting rules differ by language) — they
are wrapped here, never reimplemented.

English (en) has a validated grade-level formula (Flesch-Kincaid) that this
component gates on. Spanish (es) formulas in textstat (Fernandez-Huerta,
Szigriszt-Pazos) are EASE scores on the INFLESZ scale (higher = easier), not
US-grade-level numbers, and are not comparable to an English grade threshold —
v1 treats es as measure-only: it reports the ease scores but does not gate on
them. Extending gating to es (or other languages) needs a defined threshold on
that language's own scale, not a reuse of the en grade cutoff.
"""

from dataclasses import dataclass, field

import textstat

SUPPORTED_LANGUAGES = ("en", "es")
GATEABLE_LANGUAGES = ("en",)


@dataclass
class Measurement:
    language: str
    word_count: int
    sentence_count: int
    grade: float | None
    grade_formula: str
    details: dict = field(default_factory=dict)


def measure(text: str, language: str = "en") -> Measurement:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"unsupported language {language!r}; reading-gate v1 supports: "
            f"{', '.join(SUPPORTED_LANGUAGES)}"
        )

    textstat.set_lang(language)
    words = textstat.lexicon_count(text, removepunct=True)
    sentences = textstat.sentence_count(text)

    if language == "en":
        grade = textstat.flesch_kincaid_grade(text)
        details = {
            "flesch_kincaid_grade": grade,
            "flesch_reading_ease": textstat.flesch_reading_ease(text),
            "smog_index": textstat.smog_index(text),
            "gunning_fog": textstat.gunning_fog(text),
            "coleman_liau_index": textstat.coleman_liau_index(text),
            "automated_readability_index": textstat.automated_readability_index(text),
        }
        return Measurement(
            language=language,
            word_count=words,
            sentence_count=sentences,
            grade=grade,
            grade_formula="flesch_kincaid_grade",
            details=details,
        )

    # es: measure-only — no grade-level gating formula in v1, see module docstring.
    details = {
        "fernandez_huerta": textstat.fernandez_huerta(text),
        "szigriszt_pazos": textstat.szigriszt_pazos(text),
    }
    return Measurement(
        language=language,
        word_count=words,
        sentence_count=sentences,
        grade=None,
        grade_formula="measure_only",
        details=details,
    )
