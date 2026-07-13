"""Visible-text extraction from HTML.

Thin extractor: strip non-visible tags, return whitespace-normalized text.
This targets simple site markup (nav/hero/content pages), not news-style
boilerplate removal (Mozilla Readability.js solves that harder problem and
is overkill here — see the design report this component was scoped from).
"""

from bs4 import BeautifulSoup

DROP_TAGS = ("script", "style", "template", "noscript")


def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return " ".join(text.split())


class DomRenderedNotImplemented(NotImplementedError):
    pass


def extract_dom_rendered(path_or_url: str) -> str:
    """Documented stub for v1.

    Rendered-DOM extraction (walking a live SPA's DOM post-render, e.g. via
    Playwright) is not implemented in v1. Static markup (--extract html) is
    a floor, not a ceiling, on what a client-rendered page's user actually
    reads — score it as such. Extend this function (or vendor an existing
    rendered-DOM text walk from your project's own test suite, if it has
    one) when SPA measurement is needed.
    """
    raise DomRenderedNotImplemented(
        "--extract dom-rendered is not implemented in readable-or-else v1. "
        "Use --extract html for static markup, or pre-extract rendered text "
        "yourself and pass it as a .txt input."
    )
