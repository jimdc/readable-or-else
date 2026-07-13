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

from .denial_rules import DenialConfig, rule_placeholder_preserved, run_denial_rules
from .llm import DEFAULT_SYSTEM_PROMPT, MIXED_CONTENT_SYSTEM_PROMPT, CallBudgetExceeded, RewriteClient, RewriteUnavailable
from .measure import measure
from .mixed_content import MixedContentPassage, dehydrate

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
    client: RewriteClient,
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
        except CallBudgetExceeded as exc:
            return PassageFixResult(
                tag=tag,
                original_text=text,
                candidate_text=None,
                applied=False,
                rule="budget_exceeded",
                reason=str(exc),
                attempts=attempts,
                before_grade=before.grade,
            )
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


def attempt_fix_mixed(
    passage: MixedContentPassage,
    target_grade: float,
    language: str,
    client: RewriteClient,
    denial_config: DenialConfig | None = None,
    max_retries: int = 1,
    tag: str | None = None,
) -> tuple[PassageFixResult, str | None]:
    """Fix mode for a passage that contains inline markup (mixed_content.py).

    Same retry-with-feedback shape as `attempt_fix`, but the LLM sees and
    returns placeholder-bearing text, not plain prose. Candidates are
    validated in two stages: `rule_placeholder_preserved` on the raw
    placeholder text first (a candidate that fails this can't be safely
    dehydrated or reassembled at all), then the usual grade/meaning/length/
    markup rules on the dehydrated prose.

    Returns (result, raw_candidate). `raw_candidate` is the accepted
    placeholder-bearing text — apply.py's caller needs it, not the dehydrated
    prose in `result.candidate_text`, to splice the original inline Tag
    objects back into the DOM — and is None whenever `result.applied` is
    False.
    """
    denial_config = denial_config or DenialConfig()
    before = measure(passage.dehydrated_text, language=language)

    if passage.inline_ratio >= denial_config.inline_dominant_ratio:
        return PassageFixResult(
            tag=tag,
            original_text=passage.dehydrated_text,
            candidate_text=None,
            applied=False,
            rule="inline_dominant",
            reason=(
                f"inline elements make up {passage.inline_ratio:.0%} of this passage's "
                f"text (threshold {denial_config.inline_dominant_ratio:.0%}) — rewriting "
                "prose around them was not attempted"
            ),
            attempts=0,
            before_grade=before.grade,
        ), None

    base_system = MIXED_CONTENT_SYSTEM_PROMPT.format(target_grade=target_grade, language=language)
    system = base_system
    max_attempts = max(1, max_retries + 1)

    raw_candidate = None
    dehydrated_candidate = None
    outcome = None
    attempts = 0

    for attempt_num in range(max_attempts):
        attempts = attempt_num + 1
        try:
            raw_candidate = client.complete(system, passage.placeholder_text)
        except CallBudgetExceeded as exc:
            return PassageFixResult(
                tag=tag,
                original_text=passage.dehydrated_text,
                candidate_text=None,
                applied=False,
                rule="budget_exceeded",
                reason=str(exc),
                attempts=attempts,
                before_grade=before.grade,
            ), None
        except RewriteUnavailable as exc:
            return PassageFixResult(
                tag=tag,
                original_text=passage.dehydrated_text,
                candidate_text=None,
                applied=False,
                rule="llm_unavailable",
                reason=str(exc),
                attempts=attempts,
                before_grade=before.grade,
            ), None

        outcome = rule_placeholder_preserved(passage.placeholder_text, raw_candidate)
        dehydrated_candidate = None
        if not outcome.denied:
            dehydrated_candidate = dehydrate(raw_candidate, passage.nodes)
            outcome = run_denial_rules(
                passage.dehydrated_text, dehydrated_candidate,
                target_grade=target_grade, language=language, config=denial_config,
            )

        if not outcome.denied:
            after = measure(dehydrated_candidate, language=language)
            return PassageFixResult(
                tag=tag,
                original_text=passage.dehydrated_text,
                candidate_text=dehydrated_candidate,
                applied=True,
                rule="",
                reason=(
                    f"grade {after.grade:.2f} meets target {target_grade}; "
                    "all denial rules passed"
                ),
                attempts=attempts,
                before_grade=before.grade,
                after_grade=after.grade,
            ), raw_candidate

        if attempt_num < max_attempts - 1:
            system = base_system + RETRY_FEEDBACK.format(rule=outcome.rule, detail=outcome.detail)

    after_grade = measure(dehydrated_candidate, language=language).grade if dehydrated_candidate else None
    return PassageFixResult(
        tag=tag,
        original_text=passage.dehydrated_text,
        candidate_text=dehydrated_candidate if dehydrated_candidate is not None else raw_candidate,
        applied=False,
        rule=outcome.rule,
        reason=outcome.detail,
        attempts=attempts,
        before_grade=before.grade,
        after_grade=after_grade,
    ), None


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
    client: RewriteClient,
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
