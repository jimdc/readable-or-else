"""HTML-aware apply-in-place: fix mode's markup layer.

Walks the parsed document and considers each *leaf block element* — a tag
whose direct children are text and, at most, a bounded set of inline tags
(a plain `<p>`, a plain `<li>`, a heading, and so on) — as one rewrite
passage. Two shapes are handled:

  - A pure leaf (no nested tags at all): the whole element's text is one
    passage, rewritten and spliced back as a single new text node — the
    element's tag, attributes, and position in the tree are never touched.
  - A *mixed-content* leaf (text plus supported inline tags like `<a>`,
    `<b>`, `<em>` — see mixed_content.py's INLINE_TAGS): the passage is
    serialized to placeholder-bearing text, rewritten, and reassembled by
    re-using the original inline Tag objects at their new positions, so
    their attributes (an `<a href>`, in particular) are untouched too.

An element outside both shapes — nested inline-in-inline, a `<code>` span,
or anything else mixed_content.py's `serialize_mixed_content` declines — is
left untouched and counted as skipped rather than guessed at. See
mixed_content.py's module docstring for the exact list of honest limits.
"""

from bs4 import BeautifulSoup, NavigableString

from .denial_rules import DenialConfig
from .fix import PassageFixResult, attempt_fix, attempt_fix_mixed
from .measure import measure
from .mixed_content import reassemble, serialize_mixed_content

LEAF_TAGS = (
    "p", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "figcaption", "dt", "dd", "caption", "summary",
)
SKIP_TAGS = ("script", "style", "template", "noscript")


def _is_leaf_text_element(el) -> bool:
    if el.name not in LEAF_TAGS:
        return False
    if el.find_all(True):
        return False
    return bool(el.get_text().strip())


def _replace_text_content(el, new_text: str) -> None:
    el.clear()
    el.append(NavigableString(new_text))


def fix_html(
    html: str,
    target_grade: float,
    language: str,
    client,
    denial_config: DenialConfig | None = None,
    max_retries: int = 1,
) -> tuple[str, list[PassageFixResult], int]:
    """Returns (new_html, passage_results, skipped_nested_markup_count)."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    skipped = 0

    for el in soup.find_all(True):
        if el.name in SKIP_TAGS:
            continue
        if el.name not in LEAF_TAGS:
            continue

        has_nested = bool(el.find_all(True))

        if not has_nested:
            if not _is_leaf_text_element(el):
                continue
            original_text = el.get_text()
            m = measure(original_text, language=language)
            if m.grade is None or m.grade <= target_grade:
                continue

            result = attempt_fix(
                original_text, target_grade, language, client, denial_config, max_retries, tag=el.name
            )
            if result.applied:
                _replace_text_content(el, result.candidate_text)
            results.append(result)
            continue

        if not el.get_text().strip():
            continue
        m = measure(el.get_text(), language=language)
        if m.grade is None or m.grade <= target_grade:
            continue

        passage = serialize_mixed_content(el)
        if passage is None:
            skipped += 1
            continue

        result, raw_candidate = attempt_fix_mixed(
            passage, target_grade, language, client, denial_config, max_retries, tag=el.name
        )
        if result.applied and raw_candidate is not None:
            reassemble(el, raw_candidate, passage.nodes)
        results.append(result)

    return str(soup), results, skipped
