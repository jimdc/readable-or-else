# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- **Test command**: `python3 -m pytest` (or `python3 -m unittest discover -s tests`) from repo root — both work without installing the package first, since `readable_or_else/` sits at repo root. `pip install -e ".[dev]"` for a real venv with `textstat`/`beautifulsoup4`/`pytest`.
- **No live LLM calls in tests.** The rewrite path (`readable_or_else/llm.py`) is exercised only via the fake client in `tests/fakes.py`. Never add a test that hits `READABLE_OR_ELSE_LLM_BASE` for real.
- **Measurement math is wrapped, never reimplemented.** `readable_or_else/measure.py` is a thin wrapper over `textstat`. If a formula looks wrong, the fix is almost never in this repo — check `textstat`'s issue tracker first.
- **Presets are data, not code** (`readable_or_else/presets.py`) — each one carries its citation inline. Adding a preset means adding a `Preset(...)` entry with a real source, not writing new gating logic.
- **`--extract dom-rendered` is a v1 stub** (`readable_or_else/extract.py::extract_dom_rendered`) — raises `DomRenderedNotImplemented`. SPA-rendered content needs a real DOM walk (e.g. Playwright); not built yet.
- **crol-list is the reference consumer** — see `docs/consumers/crol-list.md` for its exact ratchet-mode drop-in and baseline numbers at adoption time.
- **Design source**: this component's build/wrap scope decisions (why textstat, why ratchet mode, why English-only rewrite, why link-text/i18n linting are explicitly out of scope) come from a research report that lives outside this repo (an estate research artifact, not committed here) — if a scope question comes up ("should this also lint X"), the answer is almost always "no, that's a different rule family," and this file should be updated with the reasoning if it recurs.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
