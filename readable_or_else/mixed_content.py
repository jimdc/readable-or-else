"""Mixed-content rewriting: extends fix mode past the leaf-text-only limit.

apply.py's leaf-element rule treats any block element containing a nested tag
as untouched, because its plain leaf-splice strategy (replace all text with
one new text node) has no way to keep an inline tag's position and attributes
intact through a full-passage rewrite. In real civic pages this is the common
case, not the exception: most long over-target paragraphs contain at least
one `<a>` (a citation, a "see also", a payment link) — see the crol-list
fixture in tests/test_mixed_content.py, a real over-target paragraph that
apply.py's old leaf-only rule would have skipped outright.

This module closes that gap for a bounded, common family of markup: a leaf
block element (p/li/td/...) whose direct children are text plus a handful of
INLINE_TAGS, each itself a pure leaf (no further nested tags). It:

  1. Serializes that mix to a rewritable placeholder string — each inline
     element becomes an opaque token carrying a label, an index (for
     uniqueness when a passage has more than one of the same tag), and its
     exact inner text: `[LINK1:the payment portal]`. The LLM sees only this
     string and is told to keep every token exactly once — moving a token is
     fine, editing or dropping what's inside its brackets is not.
  2. Validates the LLM's output by exact placeholder-token match
     (`rule_placeholder_preserved` in denial_rules.py) — this is what
     replaces apply.py's "never touch it" link-anchor guarantee for this
     path: a candidate that drops, duplicates, or edits a token is denied
     before its prose is even measured.
  3. Reassembles a passing candidate back into the DOM by re-using the
     *original* Tag objects (never rebuilt from scratch, so their attributes
     are untouched) at their new positions, interleaved with new
     NavigableString text nodes built from the candidate's surrounding
     prose. Markup integrity is enforced structurally by this reuse, not by
     a post-hoc text diff: a placeholder token can only resolve to its
     original node once `rule_placeholder_preserved` has already confirmed
     that token — label, index, and inner text — is byte-identical to the
     one recorded at extraction time.

Honest limits (deliberately NOT handled here — `serialize_mixed_content`
returns `None` and the caller falls back to the old "skip it, count it,
never call the LLM" behavior):
  - Nested inline-in-inline (e.g. `<a><b>text</b></a>`, or a `<b>` that
    itself wraps an `<a>`) — only one level of inline nesting is modeled.
  - Tags outside INLINE_TAGS — notably `<code>` and friends: a code span is
    content to preserve, not prose to restructure around, and asking an LLM
    to write around one invites it to "helpfully" reword what's inside
    despite instructions not to.
  - An inline element whose inner text contains `[` or `]` — would break
    placeholder-token parsing on the round trip.
  - `inline_dominant` (checked in fix.py, not here): a passage where the
    inline elements ARE most of the sentence is denied without ever calling
    the LLM — "restructure the prose around a placeholder that's most of
    the text" isn't a rewrite, it's a coin flip.
"""

import re
from dataclasses import dataclass, field

from bs4 import NavigableString, Tag

INLINE_TAGS = (
    "a", "b", "strong", "em", "i", "span", "mark", "small",
    "abbr", "cite", "sub", "sup", "u", "s", "q",
)

_LABEL_OVERRIDES = {"a": "LINK", "b": "BOLD", "strong": "BOLD", "em": "EM", "i": "EM"}

# Matches one placeholder token, e.g. "[LINK1:the payment portal]".
PLACEHOLDER_RE = re.compile(r"\[([A-Z]+\d+):(.*?)\]")
# Matches the same, but captures the whole bracketed token for exact-match comparison.
PLACEHOLDER_TOKEN_RE = re.compile(r"\[[A-Z]+\d+:.*?\]")


def _label(tag_name: str) -> str:
    return _LABEL_OVERRIDES.get(tag_name, tag_name.upper())


@dataclass
class MixedContentPassage:
    """A leaf block element's content, serialized for LLM rewriting."""

    placeholder_text: str
    dehydrated_text: str
    nodes: dict = field(default_factory=dict)  # token (e.g. "LINK1") -> original Tag
    inline_text_len: int = 0
    total_text_len: int = 0

    @property
    def inline_ratio(self) -> float:
        if self.total_text_len == 0:
            return 0.0
        return self.inline_text_len / self.total_text_len


def serialize_mixed_content(el) -> MixedContentPassage | None:
    """Builds a placeholder-bearing rewrite passage from `el`'s direct content.

    Returns None if `el` contains anything outside the supported shape: a
    non-inline tag, nested inline-in-inline, or bracket-bearing inline text.
    Also returns None if `el` has no inline-tag children at all — that's a
    plain leaf, apply.py's existing path already handles it.
    """
    if not isinstance(el, Tag):
        return None

    parts = []
    nodes = {}
    counters = {}
    inline_text_len = 0

    for child in el.contents:
        if isinstance(child, NavigableString):
            parts.append(str(child))
            continue
        if not isinstance(child, Tag):
            return None  # comments, processing instructions, etc.
        if child.name not in INLINE_TAGS:
            return None
        if child.find_all(True):
            return None  # nested inline-in-inline
        inner = child.get_text()
        if "[" in inner or "]" in inner:
            return None

        label = _label(child.name)
        counters[label] = counters.get(label, 0) + 1
        token = f"{label}{counters[label]}"
        parts.append(f"[{token}:{inner}]")
        nodes[token] = child
        inline_text_len += len(inner)

    if not nodes:
        return None  # no inline children -- not a mixed-content passage

    return MixedContentPassage(
        placeholder_text="".join(parts),
        dehydrated_text=el.get_text(),
        nodes=nodes,
        inline_text_len=inline_text_len,
        total_text_len=len(el.get_text()),
    )


def dehydrate(placeholder_text: str, nodes: dict) -> str | None:
    """Replaces every placeholder token with its original node's inner text.

    Returns None if a token doesn't resolve to a known node — a defensive
    check; callers should already have run `rule_placeholder_preserved`
    first, which guarantees every token in a passing candidate is one that
    was recorded at extraction time.
    """
    missing = False

    def _sub(m):
        nonlocal missing
        node = nodes.get(m.group(1))
        if node is None:
            missing = True
            return ""
        return node.get_text()

    result = PLACEHOLDER_RE.sub(_sub, placeholder_text)
    return None if missing else result


def reassemble(el, candidate_placeholder_text: str, nodes: dict) -> bool:
    """Splices a passing candidate into `el`, in place.

    Replaces el's entire content with a new stream of NavigableStrings (the
    candidate's prose) and the ORIGINAL inline Tag objects (re-used, not
    rebuilt, so their attributes are untouched) at their new positions.
    Returns False and leaves `el` untouched if any token in the candidate
    doesn't resolve to a known node — this should never happen once
    `rule_placeholder_preserved` has passed; it's checked again here as the
    last line of defense before mutating the DOM.
    """
    segments = []
    last_end = 0
    for m in PLACEHOLDER_RE.finditer(candidate_placeholder_text):
        node = nodes.get(m.group(1))
        if node is None:
            return False
        if m.start() > last_end:
            segments.append(candidate_placeholder_text[last_end:m.start()])
        segments.append(node)
        last_end = m.end()
    if last_end < len(candidate_placeholder_text):
        segments.append(candidate_placeholder_text[last_end:])

    for segment in segments:
        if isinstance(segment, Tag):
            segment.extract()

    el.clear()
    for segment in segments:
        if isinstance(segment, Tag):
            el.append(segment)
        elif segment:
            el.append(NavigableString(segment))
    return True
