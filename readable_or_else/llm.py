"""LLM-backed rewrite: the shared primitive behind both `--suggest` and `fix`.

Produces a candidate rewrite of a failing passage at the target grade,
re-measures the candidate with the same wrapped textstat formulas used for
gating, and rejects it if it is still over target or fails a
meaning-preservation heuristic check. This module is backend-agnostic: it
only ever calls `client.complete(system, user) -> str` on whatever backend
`client_from_env()` (or a caller) hands it — see "Backends" below.

`rewrite_passage` below (the `--suggest` path) never writes anywhere — its
candidate is only ever emitted as a suggestion for a human to accept. Applying
a rewrite in place is a separate, opt-in mode: see fix.py and apply.py, which
build on `check_meaning_preserved` here as one of several denial rules
(denial_rules.py) that gate whether a candidate may be auto-applied.

Backends (READABLE_OR_ELSE_LLM_BACKEND):
  - "http" (default): a configurable OpenAI-compatible chat-completions
    endpoint (`LLMClient`/`LLMConfig`). Provider-agnostic by design — OpenAI
    itself, an Anthropic-compatible shim, or a local proxy — but billed per
    call by whatever's on the other end of the URL.
  - "command" (`CommandLLMClient`/`CommandLLMConfig`): shells out to a
    configured CLI command per passage instead. This is the fit for
    subscription/flat-plan tools (a "claude -p ..." or similar CLI reachable
    only through its own harness, not an API key) and local models — the
    per-call *cost* is zero, though a CLI cold-starts a process per passage so
    it's slower than a persistent HTTP connection.

Both backends duck-type the same `complete(system, user) -> str` shape, so
everything downstream (denial rules, retry-with-feedback, re-measurement) is
backend-agnostic and never branches on which one is active.

`client_from_env()` also wraps whichever backend it builds in a `BudgetedClient`
enforcing READABLE_OR_ELSE_MAX_CALLS (default 50) — a denial-of-wallet guard:
a runaway loop is a risk on a metered endpoint (surprise bill) and on a
flat-plan CLI alike (a locked-up terminal), so the cap applies identically to
both backends rather than trying to estimate cost, which is backend-specific.

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
import shlex
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .measure import measure

DEFAULT_SYSTEM_PROMPT = (
    "You are a plain-language editor. Rewrite the given passage so it reads at "
    "or below U.S. grade {target_grade} on the Flesch-Kincaid scale, in {language}. "
    "Preserve every number, proper noun, and URL exactly. Keep the same factual "
    "content and intent. Do not add commentary, headings, or quotation marks — "
    "reply with only the rewritten passage."
)

# Used by fix.py's attempt_fix_mixed (mixed_content.py) for passages that
# contain inline markup (links, bold, etc.) serialized as placeholder tokens.
MIXED_CONTENT_SYSTEM_PROMPT = (
    "You are a plain-language editor. Rewrite the given passage so it reads at "
    "or below U.S. grade {target_grade} on the Flesch-Kincaid scale, in {language}. "
    "The passage contains placeholder tokens shaped like [LINK1:some text] standing "
    "in for links or inline formatting (bold, emphasis, etc.) — treat each whole "
    "token, brackets included, as one opaque word. Rules for tokens: every token in "
    "the input must appear in your output exactly once, byte-for-byte identical "
    "including its brackets and inner text; you may move a token to a different "
    "place in the sentence, but you may never edit, translate, shorten, or drop "
    "what is inside its brackets, and never invent a new token. Preserve every "
    "number, proper noun, and URL that appears outside a token, exactly. Keep the "
    "same factual content and intent. Do not add commentary, headings, or "
    "quotation marks — reply with only the rewritten passage, tokens included."
)


class RewriteUnavailable(RuntimeError):
    """Raised when the LLM endpoint isn't configured or the call fails."""


BUDGET_EXCEEDED_PREFIX = "call budget exceeded"


class CallBudgetExceeded(RewriteUnavailable):
    """Raised by `BudgetedClient` once READABLE_OR_ELSE_MAX_CALLS is reached."""


class RewriteClient(Protocol):
    """The only shape rewrite_passage/fix.py depend on — either backend satisfies it."""

    def complete(self, system: str, user: str) -> str: ...


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str = ""

    @classmethod
    def from_env(cls) -> "LLMConfig":
        base_url = os.environ.get("READABLE_OR_ELSE_LLM_BASE")
        model = os.environ.get("READABLE_OR_ELSE_LLM_MODEL")
        api_key = os.environ.get("READABLE_OR_ELSE_LLM_KEY", "")
        if not base_url or not model:
            raise RewriteUnavailable(
                "READABLE_OR_ELSE_LLM_BASE and READABLE_OR_ELSE_LLM_MODEL must be set in the "
                "environment to use --suggest or fix (READABLE_OR_ELSE_LLM_KEY is optional, "
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


DEFAULT_COMMAND_TIMEOUT = 60.0


@dataclass
class CommandLLMConfig:
    command: str
    timeout: float = DEFAULT_COMMAND_TIMEOUT

    @classmethod
    def from_env(cls) -> "CommandLLMConfig":
        command = os.environ.get("READABLE_OR_ELSE_LLM_CMD")
        if not command:
            raise RewriteUnavailable(
                "READABLE_OR_ELSE_LLM_BACKEND=command requires READABLE_OR_ELSE_LLM_CMD, e.g. "
                "'claude -p --model sonnet', 'llm -m ollama:llama3.1', or 'ollama run llama3.1'."
            )
        timeout_raw = os.environ.get("READABLE_OR_ELSE_LLM_TIMEOUT")
        timeout = float(timeout_raw) if timeout_raw else DEFAULT_COMMAND_TIMEOUT
        return cls(command=command, timeout=timeout)


class CommandLLMClient:
    """Shells out to a configured command as the rewrite backend, one subprocess per passage.

    Built for flat-plan CLIs (subscription tools reachable only through their own
    harness, not an API key) and local models — the per-call cost is zero, unlike
    `LLMClient`, which pays per token to whatever's behind the URL. The tradeoff
    is latency: a CLI cold-starts a process per passage, so a large file runs
    slower here than against a persistent HTTP connection, and success depends on
    that CLI's own auth/session already being valid in this shell.

    Shell-safety: the passage text is never interpolated into the command string —
    it is written to the subprocess's stdin only, and `READABLE_OR_ELSE_LLM_CMD` is
    split with `shlex.split` and run without `shell=True`, so nothing in the
    passage or the model's own output can inject an extra shell command.
    """

    def __init__(self, config: CommandLLMConfig):
        self.config = config

    def complete(self, system: str, user: str) -> str:
        prompt = f"{system}\n\n{user}"
        try:
            argv = shlex.split(self.config.command)
        except ValueError as exc:
            raise RewriteUnavailable(
                f"backend_error: could not parse READABLE_OR_ELSE_LLM_CMD {self.config.command!r}: {exc}"
            ) from exc
        if not argv:
            raise RewriteUnavailable("backend_error: READABLE_OR_ELSE_LLM_CMD is empty")

        try:
            result = subprocess.run(
                argv,
                input=prompt.encode("utf-8"),
                capture_output=True,
                timeout=self.config.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RewriteUnavailable(
                f"backend_error: command timed out after {self.config.timeout:.0f}s: "
                f"{self.config.command!r}"
            ) from exc
        except OSError as exc:
            raise RewriteUnavailable(
                f"backend_error: could not run command {self.config.command!r}: {exc}"
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RewriteUnavailable(
                f"backend_error: command {self.config.command!r} exited {result.returncode}: {stderr}"
            )

        return result.stdout.decode("utf-8", errors="replace").strip()


DEFAULT_MAX_CALLS = 50


class BudgetedClient:
    """Wraps any rewrite client and enforces a hard per-invocation call ceiling.

    This is the only lever for denial-of-wallet safety: cost estimation is
    backend-specific (dollars-per-token for `LLMClient`, meaningless for a flat-plan
    `CommandLLMClient`), so instead of trying to price a run, this caps how many
    calls it may make at all. Once the ceiling is hit, every further call raises
    immediately — no subprocess spawned, no request sent — so remaining passages
    degrade cleanly to the same "denied" reporting path as any other backend error.
    """

    def __init__(self, client: RewriteClient, max_calls: int = DEFAULT_MAX_CALLS):
        self.client = client
        self.max_calls = max_calls
        self.calls_made = 0

    def complete(self, system: str, user: str) -> str:
        if self.calls_made >= self.max_calls:
            raise CallBudgetExceeded(
                f"{BUDGET_EXCEEDED_PREFIX}: READABLE_OR_ELSE_MAX_CALLS={self.max_calls} reached "
                "for this invocation — raise it or split the run to process the rest"
            )
        self.calls_made += 1
        return self.client.complete(system, user)


def client_from_env(timeout: float = 30.0) -> "BudgetedClient":
    """Build the configured rewrite backend from environment variables.

    READABLE_OR_ELSE_LLM_BACKEND selects the backend ("http", the default, or
    "command" — see the module docstring). The result is always wrapped in a
    `BudgetedClient` honoring READABLE_OR_ELSE_MAX_CALLS, regardless of backend.
    """
    backend = os.environ.get("READABLE_OR_ELSE_LLM_BACKEND", "http")
    if backend == "http":
        client: RewriteClient = LLMClient(LLMConfig.from_env(), timeout=timeout)
    elif backend == "command":
        client = CommandLLMClient(CommandLLMConfig.from_env())
    else:
        raise RewriteUnavailable(
            f"unknown READABLE_OR_ELSE_LLM_BACKEND={backend!r}; expected 'http' or 'command'"
        )

    max_calls_raw = os.environ.get("READABLE_OR_ELSE_MAX_CALLS")
    max_calls = int(max_calls_raw) if max_calls_raw else DEFAULT_MAX_CALLS
    return BudgetedClient(client, max_calls)


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
    client: RewriteClient,
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
