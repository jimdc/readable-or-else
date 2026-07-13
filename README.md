# readable-or-else

**readable-or-else** is a **readability CI gate** — a **Flesch-Kincaid grade
level check in CI** that fails a pull request when a page misses its target
reading level — plus an LLM-backed mode that can **rewrite text to a 7th
grade reading level with an LLM** (or any grade you choose) so a failing
build doesn't stall on "now what." It's built for **plain language** and
**accessibility** work, including a ready-made **WCAG** 3.1.5 Reading Level
preset, and ships general-purpose: point it at any HTML or text content, not
just civic sites.

Most readability gates stop at "fail the build." readable-or-else also answers
the next question a failing build raises: *okay, so what should this say
instead?* `--suggest` calls a configurable LLM to draft a plain-language
rewrite, re-measures it with the same formula used for gating, and only
surfaces it if the rewrite actually hits the target grade and preserves the
original's numbers, links, and named entities. It never edits your files —
suggestions are always a human-reviewed proposal.

**Why the name:** the gate fails your build... or else the rewrite mode
tells you exactly what to say instead.

**The harder problem isn't passing the gate once — it's staying passed as
the text keeps changing.** A page that reads at grade 7 today drifts the
moment someone edits a paragraph, adds a section, or pastes in new copy from
a different author. Re-running a rewrite tool by hand after every edit
doesn't scale, which is exactly the problem eslint --fix and prettier --write
solved for code style: don't just report the failure, fix it, automatically,
every time, and let a human review the diff instead of authoring it from
scratch. `fix` is that convention applied to accessibility: it rewrites each
failing passage, runs the candidate through a documented set of denial rules,
and applies only the candidates that pass — see "Fix mode" below.

## Why grade 7

This tool exists because of one standard: the [NYC Web Content Style
Guide](https://designsystem.nyc.gov/standards/nyc-web-content-style-guide.html)'s
"Reading level" rule, quoted verbatim below, which became the flagship
`nycsg7` preset:

> "Always make your content as simple as you can without losing meaning. Try
> to simplify your content to a seventh grade reading level or lower. We use
> the Flesch–Kincaid grade level formula."

readable-or-else ships that standard as data (see `readable_or_else/presets.py`), not
a hardcoded assumption — every preset carries its source citation inline so
the tool stays honest about which public standard it's enforcing, and how
faithfully. The NYC guide is the tool's origin, not its scope: readable-or-else
is a general-purpose readability gate for any HTML or text content — see
"Not civic-specific" below.

## What this is not

- **Not a readability-formula reimplementation.** Measurement is a thin
  wrapper over [`textstat`](https://github.com/textstat/textstat) (MIT) —
  Flesch-Kincaid, Flesch Reading Ease, SMOG, Gunning Fog, Coleman-Liau, ARI
  for English; Fernández-Huerta and Szigriszt-Pazos for Spanish. These are
  peer-reviewed, language-tuned formulas; readable-or-else doesn't second-guess
  the math, only the policy around it (gate/warn/ratchet, presets, the
  rewrite loop).
- **Not civic-specific.** The NYC standard is the flagship preset because it's
  where this tool started, not a constraint — `govuk9` and `wcag-aaa` ship
  alongside it, and `--preset custom --max-grade N` covers everything else.
- **Not a mass HTML-boilerplate remover.** Extraction is a thin
  script/style/template strip suited to ordinary site markup (see
  `readable_or_else/extract.py`), not a news-article content extractor like
  Mozilla's Readability.js. `--extract dom-rendered` (for SPA-rendered
  content) is a documented stub in v1 — see Limits below.

## Quickstart

```bash
pip install -e .   # or: pip install readable-or-else, once published

# Gate a page against the NYC grade-7 standard
readable-or-else check about.html --preset nycsg7
# or the shorter alias:
ror check about.html --preset nycsg7

# Same thing, machine-readable, for scripting
readable-or-else check about.html --preset nycsg7 --format json

# GitHub Actions inline annotations
readable-or-else check about.html --preset nycsg7 --format gh-annotations
```

Exit code is `1` if any input fails its gate, `0` otherwise. `warn` mode and
flag-only presets (see `wcag-aaa` below) never fail the process — they only
report.

### Modes

| Mode | Behavior |
|---|---|
| `gate` (default) | Fails on any file over the preset's `max_grade`. |
| `warn` | Reports over-target files but always exits 0. |
| `ratchet` | Fails only on **regression** against a committed baseline file — lets an already-over-target project adopt the gate without failing every PR on day one, and only requires new/never-baselined files to meet the target directly. |

### Presets

| Preset | Standard | Max grade | Notes |
|---|---|---|---|
| `nycsg7` | [NYC Web Content Style Guide](https://designsystem.nyc.gov/standards/nyc-web-content-style-guide.html) | FK grade 7 | The flagship preset. |
| `govuk9` | GOV.UK content design ("reading age 9") | FK grade 4 (approx.) | GOV.UK's standard is a *reading age*, not a US grade level, and `textstat` has no reading-age formula — this preset approximates reading age 9 as FK grade ≤4 (the common age-minus-5 heuristic). Treat it as an approximation. |
| `wcag-aaa` | [WCAG 3.1.5 Reading Level (AAA)](https://www.w3.org/WAI/WCAG22/Understanding/reading-level.html) | FK grade 9 (flag-only) | WCAG 3.1.5 asks for a simplified *supplement* above lower-secondary level, not a hard gate — this preset never fails a build regardless of `--mode`; it only warns. |
| `custom` | — | `--max-grade N` (required) | Any threshold, no named standard. |

### Ratchet mode: the committed baseline

```bash
# Record today's scores as the baseline (run once, commit the file)
readable-or-else baseline about.html data.html --preset nycsg7 -o reading-level-baseline.json

# From then on, only fail on regressions
readable-or-else check about.html data.html --preset nycsg7 --mode ratchet \
  --baseline reading-level-baseline.json
```

`readable-or-else baseline` only ever *lowers* a file's recorded grade — it can't
be used to quietly relax an existing entry. Re-run it whenever a page's score
improves to lock the gain in.

### GitHub Actions recipe

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
      - run: |
          readable-or-else check about.html data.html changelog.html \
            --preset nycsg7 --mode ratchet \
            --baseline reading-level-baseline.json \
            --format gh-annotations
```

`--format gh-annotations` emits `::error`/`::warning` workflow commands so
failures and warnings show up as inline PR annotations without any extra
plumbing.

## The rewrite mode (`--suggest`)

```bash
export READABLE_OR_ELSE_LLM_BASE="https://api.openai.com/v1"   # any OpenAI-compatible endpoint
export READABLE_OR_ELSE_LLM_KEY="sk-..."                        # omit for endpoints that don't need auth
export READABLE_OR_ELSE_LLM_MODEL="gpt-4o-mini"

readable-or-else check about.html --preset nycsg7 --suggest --format json
```

`READABLE_OR_ELSE_LLM_BASE` is deliberately provider-agnostic — point it at
OpenAI, an Anthropic-compatible shim, or a local proxy. This is a public
component; it shouldn't assume one vendor.

**What `--suggest` guarantees:**

1. Every candidate rewrite is **re-measured** with the same formula used for
   gating — a suggestion is only ever surfaced if it actually hits the
   target grade, not just because the model was asked nicely.
2. Every candidate is checked for **meaning preservation** before it's
   surfaced: numbers, URLs, and multi-word capitalized phrases (a proxy for
   named entities) present in the original must also appear in the
   candidate, or the rewrite is rejected.
3. `--suggest` itself **never writes to your files.** It's emitted as a
   suggestion — PR-comment-ready markdown, or folded into `--format
   json`/`gh-annotations` output — for a human to read and accept or discard.
   (`fix`, below, is the separate, opt-in mode that does apply candidates.)
4. **English only in v1.**

See it run for real, not mocked: [`examples/crol-list-rewrites.html`](examples/crol-list-rewrites.html)
is a live before/after showcase against crol-list's own hardest prose.

**What it does not guarantee** (read before trusting it):

- Meaning preservation is a heuristic, not a semantic-equivalence proof. It
  catches a rewrite that drops a number, a link, or a proper noun. It will
  **not** catch a rewrite that keeps every number and name but subtly
  changes what the sentence claims. Always read the diff.
- It costs an LLM call per over-target passage. It's opt-in for a reason —
  gating itself (`check` without `--suggest`) is pure arithmetic and free.
- `--extract dom-rendered` (SPA-rendered content) is not implemented in v1 —
  see Limits.

## Fix mode (`fix`): auto-apply, gated by denial rules

```bash
export READABLE_OR_ELSE_LLM_BASE="https://api.openai.com/v1"
export READABLE_OR_ELSE_LLM_KEY="sk-..."
export READABLE_OR_ELSE_LLM_MODEL="gpt-4o-mini"

readable-or-else fix about.html data.html --preset nycsg7
```

For each file, `fix` finds every *leaf block element* (a `<p>`, `<li>`,
heading, table cell, etc.) that measures over the preset's target grade,
asks the configured LLM for a rewrite, runs the candidate through the denial
rules below, and — only if it clears all of them — replaces that element's
content in place. Exit code is `1` if any passage was left over-target
(denied, or structurally ineligible), `0` otherwise, mirroring `check`'s
gate semantics so `fix` slots into the same CI step.

Two passage shapes are handled. A *pure leaf* (no nested tags at all) is
rewritten as plain text. A *mixed-content* leaf — text plus supported inline
tags like `<a>`, `<b>`, `<em>` — is rewritten too: each inline element
becomes an opaque placeholder token (`[LINK1:the payment portal]`) the LLM
must keep exactly once, anywhere in the sentence, without touching what's
inside the brackets; a passing candidate is reassembled using the *original*
tag objects, so an anchor's `href` and every other attribute survive
untouched. This is what lets `fix` reach the common civic-page paragraph
that has a citation or "see also" link in the middle of otherwise-plain
prose — see "Mixed-content rewriting" below.

**Why this is opt-in, not the default:** a denial rule you haven't yet
watched fire on your own prose is a rule you're trusting blind. `check`
(gate the build) and `--suggest` (propose a rewrite for a human to read)
stay the default path; `fix` is for consumers who've already seen `--suggest`
output on their content and are comfortable letting the same checks decide
automatically. New consumers should see suggestions before trusting the
denial rules with their prose.

### The denial rules

A candidate is applied only if it clears every rule below, checked in this
order — the first one it fails is the one reported:

| Rule | What it checks | Why |
|---|---|---|
| `grade_target` | Candidate is re-measured; must be at or under the preset's `max_grade`. | The whole point — a rewrite that doesn't actually simplify the text isn't a fix. |
| `meaning_preserved` | Numbers, URLs, and multi-word capitalized phrases (a proxy for named entities) present in the original must still appear in the candidate. | Catches a rewrite that quietly drops a fee amount, a deadline, or an agency name while "simplifying." |
| `length_ratio` | Candidate length must stay within a configurable ratio of the original's (`--min-length-ratio`/`--max-length-ratio`, default 0.4x-2.5x). | Catches drastic truncation ("Yes.") or padding that technically passes the grade check but isn't a faithful rewrite. |
| `markup_integrity` | Candidate must not contain a raw `<` or `>`. | An LLM hallucinating HTML into its output would otherwise get spliced into a text node verbatim. |
| *(extra, configurable)* | Any caller-supplied `DenialConfig(extra_denials=[...])` callables — house style rules, banned phrases, whatever your content needs. | v1 exposes this at the library level only; the CLI doesn't yet load custom rules from a config file. |

For a mixed-content passage, a sixth rule runs first, on the raw
placeholder-bearing text rather than dehydrated prose:

| Rule | What it checks | Why |
|---|---|---|
| `placeholder_preserved` | Every `[LABEL#:text]` token in the original must appear in the candidate exactly once, byte-for-byte — order may change, content may not. | Subsumes link-anchor preservation for this path: a candidate that drops, duplicates, or edits a token never reaches the five prose rules above, let alone the DOM. |

**Link anchors are preserved two ways depending on shape.** A *pure* leaf
(no nested tags) is never a rewrite candidate to begin with, so its text is
never at risk. A *mixed-content* leaf's anchors are preserved structurally
by reassembly: a placeholder token can only resolve to its original `<a>`
Tag object once `placeholder_preserved` has already confirmed that token —
label, index, and inner text — is unchanged from extraction, and reassembly
always re-uses that same object (never rebuilds one from the candidate's
text), so its `href` and every other attribute are untouched by construction.

**Retry-with-feedback.** A denial names a specific rule and reason — exactly
what a second LLM attempt needs. On denial, `fix` makes one bounded retry
(`--max-retries`, default `1`) that folds the failed rule and reason into the
prompt, then stops. This is cost-conscious by design: at most one extra LLM
call per failing passage, not a loop until something sticks.

**A denied candidate degrades to exactly the `--suggest` outcome** — nothing
is lost. The file keeps failing `check` as it did before, and the report
names which rule denied it, so a human reviewing the PR sees the same
information `--suggest` would have shown.

### Mixed-content rewriting: honest limits

Not every element with inline markup is eligible. `serialize_mixed_content`
(`readable_or_else/mixed_content.py`) declines, and the passage falls back to
"skip it, count it, never call the LLM" — the same as a fully unsupported
element:

- **Nested inline-in-inline** (`<a><b>text</b></a>`, or a `<b>` that itself
  wraps an `<a>`) — only one level of inline nesting is modeled.
- **`<code>` and similar** — a code span is content to preserve exactly, not
  prose to restructure around; asking an LLM to write around one invites it
  to "helpfully" reword what's inside despite instructions not to.
- **An inline element whose inner text contains `[` or `]`** — would break
  placeholder-token parsing on the round trip.
- **`inline_dominant`** — a passage where the inline elements ARE most of the
  sentence (`--inline-dominant-ratio`, default `0.5`) is denied without ever
  calling the LLM: restructuring prose around a placeholder that's most of
  the text isn't a rewrite, it's a coin flip.

### The maintenance loop in CI

The intended shape: `fix` runs first and commits its accepted rewrites to
the PR branch (or opens a small auto-fix PR of its own), then `check` gates
whatever is left — same two-step split as `eslint --fix && eslint`.

```yaml
name: readable-or-else
on: pull_request
jobs:
  reading-level:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install readable-or-else
      - name: Auto-fix over-target passages
        env:
          READABLE_OR_ELSE_LLM_BASE: ${{ secrets.LLM_BASE }}
          READABLE_OR_ELSE_LLM_KEY: ${{ secrets.LLM_KEY }}
          READABLE_OR_ELSE_LLM_MODEL: gpt-4o-mini
        run: |
          readable-or-else fix about.html data.html changelog.html --preset nycsg7 || true
      - name: Commit any applied rewrites back to the PR branch
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "readable-or-else: auto-apply accessibility rewrites"
      - name: Gate whatever is still over target
        run: |
          readable-or-else check about.html data.html changelog.html \
            --preset nycsg7 --mode ratchet \
            --baseline reading-level-baseline.json \
            --format gh-annotations
```

`fix`'s own exit code is deliberately ignored (`|| true`) in this recipe —
its job is to apply what it safely can, not to gate; `check` afterward is
still the gate. Swap the commit-back step for
`peter-evans/create-pull-request` if you'd rather land auto-fixes as their
own reviewable PR instead of amending the triggering one.

## Limits (v1)

- **English is authoritative.** Spanish is measured (Fernández-Huerta,
  Szigriszt-Pazos — the INFLESZ ease scale) but not gated: those formulas
  produce an ease score, not a US grade level, so there's no direct
  equivalent of `--max-grade` to compare against yet. Other languages aren't
  supported at all.
- **`--extract dom-rendered` is a documented stub.** SPA content rendered
  client-side from data at runtime isn't walked by this version — static
  markup extraction is a floor, not a ceiling, on what such a page's user
  actually reads. Pre-extract rendered text yourself (e.g. with a headless
  browser) and pass it as a `.txt` file if you need to gate a client-rendered
  page today.
- **Rewrite suggestions are heuristically checked, not semantically
  verified.** See above.
- **`fix` reaches leaf elements with a bounded set of inline tags** (`<a>`,
  `<b>`/`<strong>`, `<em>`/`<i>`, `<span>`, and a few others — see
  `mixed_content.INLINE_TAGS`), not markup in general. Nested inline-in-inline,
  `<code>`, and a few other shapes are still skipped rather than partially
  rewritten — see "Mixed-content rewriting: honest limits" above for the
  full list. A whole-file `.txt` input is treated as a single passage, same
  as `check`.
- **`fix`'s extra denial rules are library-only in v1.** `DenialConfig(extra_denials=[...])`
  works when calling `readable_or_else` as a library; the CLI doesn't yet
  load custom denial callables from a config file.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest      # or: python3 -m unittest discover
```

Tests are fully offline — the LLM rewrite path is tested against an injected
fake client (`tests/fakes.py`); no test makes a live network call.

## crol-list: the reference consumer

readable-or-else was scoped against crol-list's own pages as its first real
corpus. See
[`docs/consumers/crol-list.md`](docs/consumers/crol-list.md)
for the exact drop-in: ratchet mode across its six pages, the `nycsg7`
preset, and a ready-to-paste CI job.

## License

MIT.

<!--
Suggested GitHub repo description (<=120 chars):
Readability CI gate: Flesch-Kincaid grade-level checks + LLM plain-language rewrites, for accessibility & WCAG.

Suggested GitHub topics:
readability, accessibility, wcag, plain-language, flesch-kincaid, ci-cd, llm, github-actions
-->
