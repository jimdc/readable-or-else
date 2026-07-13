"""Fix mode: the auto-apply telos.

readable-or-else's `check`/`--suggest` path answers "does this page meet the
standard today?" Fix mode answers the harder, ongoing question: as this
page's text keeps changing — new copy, new sections, a rewritten paragraph —
how does it keep meeting the standard without a human re-running a rewrite
tool by hand every time? The answer is the auto-fixer convention already
proven by eslint --fix and prettier --write: rewrite the failing passage,
gate the candidate through denial_rules.py, and if it passes, apply it
in place. If it doesn't, it degrades to exactly the same suggestion
--suggest already produced — nothing is lost, the file just keeps failing
the gate as before.

Retry-with-feedback: a denial tells you a specific rule and a specific
reason, which is exactly the information a second LLM attempt needs. On
denial, this module makes one bounded retry (config `max_retries`, default
1) with that rule/reason folded into the prompt. It stops there — this is
cost-conscious by design, not a loop until something sticks.
"""

from dataclasses import dataclass

from .denial_rules import DenialConfig, run_denial_rules
from .llm import DEFAULT_SYSTEM_PROMPT, LLMClient, RewriteUnavailable
from .measure import measure

RETRY_FEEDBACK = (
    "\n\nYour previous attempt was rejected by the '{rule}' rule: {detail}. "
    "Produce a new rewrite that fixes this specific problem while still meeting "
    "the grade target and preserving the original's meaning."
)


@dataclass
class PassageFixResult:
    tag: str | None
    original_text: str
    candidate_text: str | None
    applied: bool
    rule: str
    reason: str
    attempts: int
    before_grade: float | None
    after_grade: float | None = None


def attempt_fix(
    text: str,
    target_grade: float,
    language: str,
    client: LLMClient,
    denial_config: DenialConfig | None = None,
    max_retries: int = 1,
    tag: str | None = None,
) -> PassageFixResult:
    denial_config = denial_config or DenialConfig()
    before = measure(text, language=language)
    base_system = DEFAULT_SYSTEM_PROMPT.format(target_grade=target_grade, language=language)

    system = base_system
    candidate = None
    outcome = None
    attempts = 0
    max_attempts = max(1, max_retries + 1)

    for attempt_num in range(max_attempts):
        attempts = attempt_num + 1
        try:
            candidate = client.complete(system, text)
        except RewriteUnavailable as exc:
            return PassageFixResult(
                tag=tag,
                original_text=text,
                candidate_text=None,
                applied=False,
                rule="llm_unavailable",
                reason=str(exc),
                attempts=attempts,
                before_grade=before.grade,
            )

        outcome = run_denial_rules(
            text, candidate, target_grade=target_grade, language=language, config=denial_config
        )
        if not outcome.denied:
            after = measure(candidate, language=language)
            return PassageFixResult(
                tag=tag,
                original_text=text,
                candidate_text=candidate,
                applied=True,
                rule="",
                reason=(
                    f"grade {after.grade:.2f} meets target {target_grade}; "
                    "all denial rules passed"
                ),
                attempts=attempts,
                before_grade=before.grade,
                after_grade=after.grade,
            )

        if attempt_num < max_attempts - 1:
            system = base_system + RETRY_FEEDBACK.format(rule=outcome.rule, detail=outcome.detail)

    after = measure(candidate, language=language) if candidate is not None else None
    return PassageFixResult(
        tag=tag,
        original_text=text,
        candidate_text=candidate,
        applied=False,
        rule=outcome.rule,
        reason=outcome.detail,
        attempts=attempts,
        before_grade=before.grade,
        after_grade=after.grade if after else None,
    )


@dataclass
class FileFixReport:
    path: str
    changed: bool
    results: list[PassageFixResult]
    skipped_nested_markup: int = 0


def fix_text(
    text: str,
    target_grade: float,
    language: str,
    client: LLMClient,
    denial_config: DenialConfig | None = None,
    max_retries: int = 1,
) -> tuple[str, list[PassageFixResult]]:
    """Fix mode for a plain-text (non-HTML) file: the whole file is one passage."""
    m = measure(text, language=language)
    if m.grade is None or m.grade <= target_grade:
        return text, []

    result = attempt_fix(text, target_grade, language, client, denial_config, max_retries, tag=None)
    new_text = result.candidate_text if result.applied else text
    return new_text, [result]
