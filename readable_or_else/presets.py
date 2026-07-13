"""Named readability presets.

Presets are DATA, not code: each one is a threshold + a formula-per-language
mapping + a citation, so the tool is self-documenting about which public
standard it is enforcing. Measurement math itself lives in measure.py and is
never reimplemented here — see that module's docstring.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Preset:
    name: str
    max_grade: float | None
    formula: dict[str, str]
    source: str
    hard_gate: bool = True
    note: str = ""


PRESETS: dict[str, Preset] = {
    "nycsg7": Preset(
        name="nycsg7",
        max_grade=7,
        formula={"en": "flesch_kincaid_grade"},
        source=(
            'NYC Web Content Style Guide, "Reading level": '
            "https://designsystem.nyc.gov/standards/nyc-web-content-style-guide.html — "
            '"Try to simplify your content to a seventh grade reading level or lower. '
            'We use the Flesch-Kincaid grade level formula."'
        ),
    ),
    "govuk9": Preset(
        name="govuk9",
        max_grade=4,
        formula={"en": "flesch_kincaid_grade"},
        source=(
            'GOV.UK content design, "Writing for GOV.UK" — targets a reading age of 9.'
        ),
        note=(
            "GOV.UK's own standard is stated as a reading AGE of 9, not a US grade level, and "
            "textstat has no reading-age formula. This preset approximates reading age 9 as "
            "Flesch-Kincaid US grade <=4 (the common age-minus-5 heuristic). Treat govuk9 as an "
            "approximation of the GOV.UK standard, not a direct implementation of it."
        ),
    ),
    "wcag-aaa": Preset(
        name="wcag-aaa",
        max_grade=9,  # US grade ~= end of "lower secondary education" (ISCED), the SC's own wording
        formula={"en": "flesch_kincaid_grade"},
        source=(
            "WCAG 3.1.5 Reading Level (AAA): "
            "https://www.w3.org/WAI/WCAG22/Understanding/reading-level.html"
        ),
        hard_gate=False,
        note=(
            "WCAG 3.1.5 requires content above lower-secondary reading level to have a "
            "simplified supplement available, not a hard numeric gate. readable-or-else models "
            "this preset as flag-only: it never fails a build (mode is downgraded to warn "
            "behavior regardless of --mode), and the report reminds you to provide a "
            "simplified supplement for flagged passages."
        ),
    ),
}


def get_preset(name: str) -> Preset:
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(
            f"unknown preset {name!r}; available presets: {', '.join(sorted(PRESETS))}"
        ) from None


def custom_preset(max_grade: float, formula: str = "flesch_kincaid_grade") -> Preset:
    return Preset(
        name="custom",
        max_grade=max_grade,
        formula={"en": formula},
        source="user-supplied --max-grade (no named standard)",
    )
