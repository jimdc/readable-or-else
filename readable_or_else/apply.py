"""HTML-aware apply-in-place: fix mode's markup layer.

Walks the parsed document and considers each *leaf text element* — a tag
whose entire content is text, with no nested tags at all (a plain `<p>`, a
plain `<li>`, a heading, and so on) — as one rewrite passage. An element that
contains any nested tag (a `<a>`, `<span>`, `<strong>`, an inline image,
anything) is never considered: v1 has no safe way to re-splice a partial
rewrite around inline markup without risking exactly the "never break
markup" guarantee this module exists to provide, so those passages are left
untouched and counted as skipped rather than guessed at. This is also how
link-anchor text ends up preserved: a paragraph containing a link is never a
rewrite candidate in the first place, so the anchor is never at risk.

Accepted candidates are spliced in by replacing the leaf element's contents
with a single new text node — the element's tag, attributes, and position in
the tree are never touched, so everything outside the rewritten text is
byte-identical before and after.
"""

from bs4 import BeautifulSoup, NavigableString

from .denial_rules import DenialConfig
from .fix import PassageFixResult, attempt_fix
from .measure import measure

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

        if el.name in LEAF_TAGS and el.find_all(True) and el.get_text().strip():
            m = measure(el.get_text(), language=language)
            if m.grade is not None and m.grade > target_grade:
                skipped += 1
            continue

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

    return str(soup), results, skipped
