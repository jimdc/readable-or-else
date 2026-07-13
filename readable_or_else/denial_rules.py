"""Denial rules — the gate between an LLM rewrite candidate and applying it.

This is the auto-fixer's safety net (the same role prettier's idempotency
check or eslint's fixable-rule allowlist plays): a candidate rewrite is only
ever applied in place if it clears every rule below. A denied candidate is
never written to disk — it degrades to a suggestion in the report, tagged
with exactly which rule denied it, and the passage keeps failing the gate as
it did before fix mode existed.

Each rule is a small, independent, independently-testable function of
`(original, candidate, **context)`. `run_denial_rules` runs them in a fixed
order and stops at the first denial, so every outcome names exactly one
responsible rule — never "rejected" with no reason.

Rules (in evaluation order):
  1. grade_target       — re-measured candidate grade must meet the preset target.
  2. meaning_preserved   — numbers, URLs, and named entities in the original must
                           still appear in the candidate (see llm.py).
  3. length_ratio        — candidate length must stay within a configurable
                           ratio of the original (default 0.4x-2.5x): catches
                           drastic truncation ("Yes.") or padding.
  4. markup_integrity    — candidate must not contain raw '<'/'>' characters,
                           which would corrupt the surrounding HTML when
                           spliced back into a text node.
  5. extra (configurable) — caller-supplied callables for house-specific
                           denials (banned phrases, tone rules, etc).

A sixth concern from the design brief, "link anchors preserved," is enforced
structurally rather than as a post-rewrite text check: apply.py never
considers a text node for rewrite if it sits inside (or wraps) a nested
inline tag such as `<a>`, so anchor text is never a rewrite candidate in the
first place — see apply.py's leaf-element scope note.
"""

from dataclasses import dataclass, field
from typing import Callable

from .llm import check_meaning_preserved
from .measure import measure

DEFAULT_MIN_LENGTH_RATIO = 0.4
DEFAULT_MAX_LENGTH_RATIO = 2.5


@dataclass
class DenialOutcome:
    denied: bool
    rule: str = ""
    detail: str = ""

    @classmethod
    def ok(cls) -> "DenialOutcome":
        return cls(denied=False)

    @classmethod
    def deny(cls, rule: str, detail: str) -> "DenialOutcome":
        return cls(denied=True, rule=rule, detail=detail)


@dataclass
class DenialConfig:
    min_length_ratio: float = DEFAULT_MIN_LENGTH_RATIO
    max_length_ratio: float = DEFAULT_MAX_LENGTH_RATIO
    extra_denials: list[Callable[[str, str], DenialOutcome]] = field(default_factory=list)


def rule_grade_target(original: str, candidate: str, *, target_grade: float, language: str, **_) -> DenialOutcome:
    after = measure(candidate, language=language)
    if after.grade is not None and after.grade > target_grade:
        return DenialOutcome.deny(
            "grade_target",
            f"candidate grade {after.grade:.2f} exceeds target {target_grade}",
        )
    return DenialOutcome.ok()


def rule_meaning_preserved(original: str, candidate: str, **_) -> DenialOutcome:
    check = check_meaning_preserved(original, candidate)
    if not check.passed:
        missing = "; ".join(f"{kind}: {sorted(values)}" for kind, values in check.missing.items())
        return DenialOutcome.deny("meaning_preserved", f"missing after rewrite — {missing}")
    return DenialOutcome.ok()


def rule_length_ratio(
    original: str,
    candidate: str,
    *,
    min_length_ratio: float = DEFAULT_MIN_LENGTH_RATIO,
    max_length_ratio: float = DEFAULT_MAX_LENGTH_RATIO,
    **_,
) -> DenialOutcome:
    if not original.strip():
        return DenialOutcome.ok()
    ratio = len(candidate) / len(original)
    if ratio < min_length_ratio or ratio > max_length_ratio:
        return DenialOutcome.deny(
            "length_ratio",
            f"length ratio {ratio:.2f} outside allowed [{min_length_ratio}, {max_length_ratio}]",
        )
    return DenialOutcome.ok()


def rule_markup_integrity(original: str, candidate: str, **_) -> DenialOutcome:
    if "<" in candidate or ">" in candidate:
        return DenialOutcome.deny(
            "markup_integrity",
            "candidate contains a raw '<' or '>' — would corrupt markup if spliced into a text node",
        )
    return DenialOutcome.ok()


DEFAULT_RULES: list[Callable[..., DenialOutcome]] = [
    rule_grade_target,
    rule_meaning_preserved,
    rule_length_ratio,
    rule_markup_integrity,
]


def run_denial_rules(
    original: str,
    candidate: str,
    *,
    target_grade: float,
    language: str,
    config: DenialConfig | None = None,
) -> DenialOutcome:
    config = config or DenialConfig()
    context = dict(
        target_grade=target_grade,
        language=language,
        min_length_ratio=config.min_length_ratio,
        max_length_ratio=config.max_length_ratio,
    )
    for rule in DEFAULT_RULES:
        outcome = rule(original, candidate, **context)
        if outcome.denied:
            return outcome
    for extra in config.extra_denials:
        outcome = extra(original, candidate)
        if outcome.denied:
            return outcome
    return DenialOutcome.ok()
