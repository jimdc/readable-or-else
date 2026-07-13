"""LLM-backed rewrite mode — the product.

Calls a configurable OpenAI-compatible chat-completions endpoint to produce a
candidate rewrite of a failing passage at the target grade, re-measures the
candidate with the same wrapped textstat formulas used for gating, and rejects
it if it is still over target or fails a meaning-preservation heuristic check.
A rewrite is NEVER auto-applied — it is only ever emitted as a suggestion for
a human to accept.

Provider-agnostic by design (env-configured base URL/key/model) so this works
against OpenAI itself, Anthropic-via-OpenAI-compat shims, or a local proxy —
this is a public component, not tied to one vendor.

Honest limits (read before trusting --suggest output):
  - English only in v1.
  - Meaning-preservation is a heuristic, not a semantic equivalence proof: it
    checks that numbers, URLs, and capitalized multi-word phrases (a proxy for
    named entities) surviving in the original also appear in the candidate. It
    cannot catch a rewrite that preserves those tokens but subtly changes
    meaning elsewhere. Always read the diff before accepting.
  - Grade re-measurement uses the same formula as the original gate, so a
    rewrite that passes has actually been re-scored, not just trusted.
"""

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .measure import measure

DEFAULT_SYSTEM_PROMPT = (
    "You are a plain-language editor. Rewrite the given passage so it reads at "
    "or below U.S. grade {target_grade} on the Flesch-Kincaid scale, in {language}. "
    "Preserve every number, proper noun, and URL exactly. Keep the same factual "
    "content and intent. Do not add commentary, headings, or quotation marks — "
    "reply with only the rewritten passage."
)


class RewriteUnavailable(RuntimeError):
    """Raised when the LLM endpoint isn't configured or the call fails."""


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str = ""

    @classmethod
    def from_env(cls) -> "LLMConfig":
        base_url = os.environ.get("READING_GATE_LLM_BASE")
        model = os.environ.get("READING_GATE_LLM_MODEL")
        api_key = os.environ.get("READING_GATE_LLM_KEY", "")
        if not base_url or not model:
            raise RewriteUnavailable(
                "READING_GATE_LLM_BASE and READING_GATE_LLM_MODEL must be set in the "
                "environment to use --suggest/--rewrite (READING_GATE_LLM_KEY is optional, "
                "for endpoints that don't require auth)."
            )
        return cls(base_url=base_url.rstrip("/"), model=model, api_key=api_key)


class LLMClient:
    """Minimal OpenAI-compatible chat-completions client (stdlib only)."""

    def __init__(self, config: LLMConfig, timeout: float = 30.0):
        self.config = config
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        url = f"{self.config.base_url}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RewriteUnavailable(f"LLM endpoint call failed: {exc}") from exc
        try:
            return body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            raise RewriteUnavailable(
                f"unexpected LLM response shape: {body!r}"
            ) from exc


_NUMBER_RE = re.compile(r"\d[\d,.]*")
_URL_RE = re.compile(r"https?://\S+")
_URL_TRAILING_PUNCT = ".,;:!?)\"'"
_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


def _tokens(text: str) -> dict[str, set[str]]:
    urls = {url.rstrip(_URL_TRAILING_PUNCT) for url in _URL_RE.findall(text)}
    return {
        "numbers": set(_NUMBER_RE.findall(text)),
        "urls": urls,
        "entities": set(_ENTITY_RE.findall(text)),
    }


@dataclass
class MeaningCheck:
    passed: bool
    missing: dict[str, set[str]] = field(default_factory=dict)


def check_meaning_preserved(original: str, candidate: str) -> MeaningCheck:
    original_tokens = _tokens(original)
    candidate_tokens = _tokens(candidate)
    missing = {
        kind: values - candidate_tokens[kind]
        for kind, values in original_tokens.items()
        if values - candidate_tokens[kind]
    }
    return MeaningCheck(passed=not missing, missing=missing)


@dataclass
class RewriteResult:
    original_text: str
    candidate_text: str | None
    accepted: bool
    reason: str
    before_grade: float | None
    after_grade: float | None = None


def rewrite_passage(
    text: str,
    target_grade: float,
    language: str,
    client: LLMClient,
) -> RewriteResult:
    before = measure(text, language=language)

    system = DEFAULT_SYSTEM_PROMPT.format(target_grade=target_grade, language=language)
    try:
        candidate = client.complete(system, text)
    except RewriteUnavailable as exc:
        return RewriteResult(
            original_text=text,
            candidate_text=None,
            accepted=False,
            reason=str(exc),
            before_grade=before.grade,
        )

    after = measure(candidate, language=language)
    meaning = check_meaning_preserved(text, candidate)

    if after.grade is not None and after.grade > target_grade:
        return RewriteResult(
            original_text=text,
            candidate_text=candidate,
            accepted=False,
            reason=(
                f"candidate still over target: grade {after.grade:.2f} > "
                f"target {target_grade}"
            ),
            before_grade=before.grade,
            after_grade=after.grade,
        )

    if not meaning.passed:
        missing_desc = "; ".join(
            f"{kind}: {sorted(values)}" for kind, values in meaning.missing.items()
        )
        return RewriteResult(
            original_text=text,
            candidate_text=candidate,
            accepted=False,
            reason=f"meaning-preservation check failed — missing {missing_desc}",
            before_grade=before.grade,
            after_grade=after.grade,
        )

    return RewriteResult(
        original_text=text,
        candidate_text=candidate,
        accepted=True,
        reason=f"grade {after.grade:.2f} meets target {target_grade}; meaning check passed",
        before_grade=before.grade,
        after_grade=after.grade,
    )
