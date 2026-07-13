# crol-list integration: drop-in for the readable-or-else ratchet gate

This is the exact drop-in for crol-list to adopt `readable-or-else` as its
readability CI gate, per the `nycsg7` preset, in `ratchet` mode. It supersedes
the `test/standards/reading_level.py` stub sketched in crol-list's own
backlog card (`w6-11-standards-as-code.md`) with the real component.

## Why ratchet, not a hard gate

Every one of crol-list's 6 shipped HTML pages currently misses FK grade 7,
by 0.8 grades (`stats.html`, closest) to 7.8 grades (`data.html`, furthest) —
see a July 2026 measured baseline of the crol-list pages, from the research
this component was scoped from, for the full numbers. A hard
`--mode gate --max-grade 7` as originally sketched in the backlog card would
fail 100% of pages immediately with no path to green. Ratchet mode commits
today's scores as a ceiling and fails only on regression, with grade 7
tracked as the long-term target in the preset itself.

## 1. Install

```bash
pip install readable-or-else   # once published; vendor the wheel pre-1.0 if not yet on PyPI
```

## 2. Commit the initial baseline (run once)

```bash
readable-or-else baseline \
  about.html api.html changelog.html data.html index.html stats.html \
  --preset nycsg7 \
  -o reading-level-baseline.json
```

Commit `reading-level-baseline.json` to the repo. Expected initial values
(from the measured baseline in the design report — re-run the command above
against current content rather than trusting these numbers, they'll have
drifted):

| Page | FK grade at baseline time |
|---|---|
| about.html | 10.78 |
| api.html | 10.76 |
| changelog.html | 11.25 |
| data.html | 13.38 |
| index.html (static chrome only — see note below) | 14.81 |
| stats.html | 7.82 |

**Note on `index.html`:** it's an SPA whose search-results/detail content is
rendered client-side from data, so the static-markup extract above is
nav/hero/footer chrome only — a floor on what a user actually reads, not the
full experience. `readable-or-else`'s `--extract dom-rendered` mode is a
documented stub in v1 (see the main README's Limits section); until that
lands, extend crol-list's existing Playwright-based DOM walk (the same
pattern `test/functional/13_stray_english.py` already uses for the
stray-English guard) to emit rendered text, and feed that to `readable-or-else`
as a `.txt` input instead of `index.html` directly.

## 3. CI job

```yaml
name: readable-or-else
on: pull_request
jobs:
  reading-level:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install readable-or-else
      - name: Reading-level ratchet gate
        run: |
          readable-or-else check \
            about.html api.html changelog.html data.html index.html stats.html \
            --preset nycsg7 \
            --mode ratchet \
            --baseline reading-level-baseline.json \
            --format gh-annotations
```

Wire this as its own job (mirroring the existing `unit` / `i18n-guard` job
split in `.github/workflows/ci.yml`) rather than folding it into `unit` —
`readable-or-else`'s dependencies (`textstat`, `beautifulsoup4`) are the first
pip installs that job would need; keeping it isolated matches how
`i18n-guard` already isolates its own Playwright dependency.

## 4. Tightening the baseline as pages improve

Whenever a page's score improves, re-run the baseline command for just that
page to lock the gain in — `readable-or-else baseline` only ever lowers a
recorded grade, so it can't be used to accidentally relax the gate:

```bash
readable-or-else baseline data.html --preset nycsg7 -o reading-level-baseline.json
```

Per the design report's own prioritization (§5): spend simplification effort
on `data.html` and `index.html`'s static chrome first (furthest over
target), not on `i18n.js` UI strings — those are already near grade 7
(6.55–6.71 across the full en dictionary) and are not the source of the gap.

## 5. Recommended: run `fix`/`--suggest` locally, let CI only measure

The cheapest and most honest way to close the remaining 37 (104 - 67, see §7
below) over-target passages is to **never call an LLM from crol-list's CI at
all**. Per the main README's "Backends" section:

1. Locally, point readable-or-else at a flat-plan CLI (the `command` backend
   — `READABLE_OR_ELSE_LLM_BACKEND=command`, `READABLE_OR_ELSE_LLM_CMD="claude
   -p --model sonnet"` or similar) and run `fix` — free at the margin, and
   every rewrite gets eyeballed before it lands.
2. Commit the rewritten HTML alongside a re-run of step 4's baseline command
   for the pages that improved.
3. The CI job in §3 above never changes: `check --mode ratchet` re-measures
   the committed pages deterministically against the committed baseline.
   That re-measurement **is** the proof the local `fix` run actually hit
   grade 7 — CI doesn't need to trust the local step, because it recomputes
   the grade itself from what got committed.

Grade-level rewriting on crol-list's prose (city-services copy, not legal
judgment calls) is mechanical enough that a flat-plan CLI or a local model is
usually sufficient — reserve a metered frontier model for a passage that
keeps failing meaning-preservation on the cheaper tiers. See the README's
"Choosing a backend: a cost ladder" for the full ordering.

## 6. Optional: rewrite suggestions inside CI

Calling an LLM from CI directly is the **exception** under the workflow
above, not the norm — only reach for it to surface suggestions on a PR
nobody's rewritten locally yet. It also runs into a real constraint: hosted
CI can't authenticate as your personal Claude Pro/Max or ChatGPT session, so
the flat-plan `command` backend generally isn't usable here (unless the CLI
supports its own CI-scoped, non-interactive credentials) — fall back to the
`http` backend against a cheap metered model instead, gated behind a label so
it's not on the default per-PR run:

```yaml
      - name: Suggest simplifications
        if: contains(github.event.pull_request.labels.*.name, 'suggest-rewrite')
        env:
          READABLE_OR_ELSE_LLM_BASE: ${{ secrets.READABLE_OR_ELSE_LLM_BASE }}
          READABLE_OR_ELSE_LLM_KEY: ${{ secrets.READABLE_OR_ELSE_LLM_KEY }}
          READABLE_OR_ELSE_LLM_MODEL: ${{ secrets.READABLE_OR_ELSE_LLM_MODEL }}
          READABLE_OR_ELSE_MAX_CALLS: "25"
        run: |
          readable-or-else check data.html index.html \
            --preset nycsg7 --mode warn --suggest --format json \
            > readable-or-else-suggestions.json
```

`READABLE_OR_ELSE_MAX_CALLS` caps how many rewrite calls this job can make in
one run (default 50 if unset) — a denial-of-wallet guard against a
misconfigured or unexpectedly large batch running up a bill against a
metered endpoint; keep it at or below the number of passages you actually
expect to suggest for.

Post `readable-or-else-suggestions.json`'s `rewrite` entries as PR review
comments in a follow-up step (any PR-comment action that can read JSON and
call the GitHub API works — this repo doesn't ship one, to stay
CI-provider-agnostic). Never wire this to auto-commit the rewrite; a human
must accept the diff.

## 7. Mixed-content rewriting closes most of the earlier eligibility gap

The first production run of `fix`/`--suggest` against crol-list (PR #17)
found that most of its over-target prose was structurally ineligible: `fix`
v1 only ever considered a *pure* leaf element (no nested tags at all) a
rewrite candidate, and real civic-page paragraphs routinely carry at least
one inline `<a>`, `<b>`, or `<em>` — a citation, a "see also," a payment
link.

readable-or-else 0.2.0 adds mixed-content rewriting (see the main README's
"Mixed-content rewriting: honest limits" section): a leaf element with
supported inline tags is now itself an eligible passage, rewritten around
placeholder tokens that stand in for its inline children and reassembled
using the *original* tag objects, so link `href`s and other attributes never
change. Re-measuring all 104 currently-over-target passages across
crol-list's six pages (`about.html`, `api.html`, `data.html`,
`changelog.html`, `stats.html`, `index.html`) against this version:

| | count |
|---|---|
| Over-target passages, total | 104 |
| Eligible before (pure leaf only) | 42 |
| Newly eligible now (mixed-content) | 25 |
| `inline_dominant` (denied without an LLM call — inline text is most of the sentence) | 1 |
| Still skipped (`<code>` spans, nested inline-in-inline, `data-i18n` `<span>` chrome) | 36 |

So this re-run reaches **67 of 104** over-target passages (up from 42),
mostly by picking up paragraphs with a single inline link. The remaining 36
are concentrated in `api.html`/`changelog.html`'s `<code>`-heavy technical
prose (an honest limit, not a bug — see the README) and `index.html`'s
`data-i18n`-wrapped `<span>` chrome (nested `<span>`-in-`<span>`, also out of
scope for v1's one-level inline model). Re-run `fix --preset nycsg7` after
upgrading to pick these up; nothing else in this drop-in changes.

## What's explicitly out of scope here

Per the design report's build/wrap/skip verdict (§3): link-text linting and
i18n missing-key linting are a **different rule family** from reading-level
gating, and are NOT part of this integration. Link-text checks belong as a
Vale custom rule; i18n missing-key checks are already solved by crol-list's
own `i18n_keys.py`. Don't bundle them into this readable-or-else adoption.
