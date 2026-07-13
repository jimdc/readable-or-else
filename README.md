# reading-gate

A CI gate for readability, plus an LLM-backed rewrite mode that proposes a
simplified version of any passage that misses its target grade.

Most readability gates stop at "fail the build." reading-gate also answers
the next question a failing build raises: *okay, so what should this say
instead?* `--suggest` calls a configurable LLM to draft a plain-language
rewrite, re-measures it with the same formula used for gating, and only
surfaces it if the rewrite actually hits the target grade and preserves the
original's numbers, links, and named entities. It never edits your files —
suggestions are always a human-reviewed proposal, never an auto-apply.

## Why grade 7

The flagship preset, `nycsg7`, is the [NYC Web Content Style
Guide](https://designsystem.nyc.gov/standards/nyc-web-content-style-guide.html)'s
"Reading level" standard, verbatim:

> "Always make your content as simple as you can without losing meaning. Try
> to simplify your content to a seventh grade reading level or lower. We use
> the Flesch–Kincaid grade level formula."

reading-gate ships that standard as data (see `reading_gate/presets.py`), not
a hardcoded assumption — every preset carries its source citation inline so
the tool stays honest about which public standard it's enforcing, and how
faithfully.

## What this is not

- **Not a readability-formula reimplementation.** Measurement is a thin
  wrapper over [`textstat`](https://github.com/textstat/textstat) (MIT) —
  Flesch-Kincaid, Flesch Reading Ease, SMOG, Gunning Fog, Coleman-Liau, ARI
  for English; Fernández-Huerta and Szigriszt-Pazos for Spanish. These are
  peer-reviewed, language-tuned formulas; reading-gate doesn't second-guess
  the math, only the policy around it (gate/warn/ratchet, presets, the
  rewrite loop).
- **Not civic-specific.** The NYC standard is the flagship preset because it's
  where this tool started, not a constraint — `govuk9` and `wcag-aaa` ship
  alongside it, and `--preset custom --max-grade N` covers everything else.
- **Not a mass HTML-boilerplate remover.** Extraction is a thin
  script/style/template strip suited to ordinary site markup (see
  `reading_gate/extract.py`), not a news-article content extractor like
  Mozilla's Readability.js. `--extract dom-rendered` (for SPA-rendered
  content) is a documented stub in v1 — see Limits below.

## Quickstart

```bash
pip install -e .   # or: pip install reading-gate, once published

# Gate a page against the NYC grade-7 standard
reading-gate check about.html --preset nycsg7

# Same thing, machine-readable, for scripting
reading-gate check about.html --preset nycsg7 --format json

# GitHub Actions inline annotations
reading-gate check about.html --preset nycsg7 --format gh-annotations
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
reading-gate baseline about.html data.html --preset nycsg7 -o reading-level-baseline.json

# From then on, only fail on regressions
reading-gate check about.html data.html --preset nycsg7 --mode ratchet \
  --baseline reading-level-baseline.json
```

`reading-gate baseline` only ever *lowers* a file's recorded grade — it can't
be used to quietly relax an existing entry. Re-run it whenever a page's score
improves to lock the gain in.

### GitHub Actions recipe

```yaml
name: reading-gate
on: pull_request
jobs:
  reading-level:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install reading-gate
      - run: |
          reading-gate check about.html data.html changelog.html \
            --preset nycsg7 --mode ratchet \
            --baseline reading-level-baseline.json \
            --format gh-annotations
```

`--format gh-annotations` emits `::error`/`::warning` workflow commands so
failures and warnings show up as inline PR annotations without any extra
plumbing.

## The rewrite mode (`--suggest`)

```bash
export READING_GATE_LLM_BASE="https://api.openai.com/v1"   # any OpenAI-compatible endpoint
export READING_GATE_LLM_KEY="sk-..."                        # omit for endpoints that don't need auth
export READING_GATE_LLM_MODEL="gpt-4o-mini"

reading-gate check about.html --preset nycsg7 --suggest --format json
```

`READING_GATE_LLM_BASE` is deliberately provider-agnostic — point it at
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
3. A rewrite is **never auto-applied.** It's emitted as a suggestion —
   PR-comment-ready markdown, or folded into `--format json`/`gh-annotations`
   output — for a human to read and accept or discard.
4. **English only in v1.**

**What it does not guarantee** (read before trusting it):

- Meaning preservation is a heuristic, not a semantic-equivalence proof. It
  catches a rewrite that drops a number, a link, or a proper noun. It will
  **not** catch a rewrite that keeps every number and name but subtly
  changes what the sentence claims. Always read the diff.
- It costs an LLM call per over-target passage. It's opt-in for a reason —
  gating itself (`check` without `--suggest`) is pure arithmetic and free.
- `--extract dom-rendered` (SPA-rendered content) is not implemented in v1 —
  see Limits.

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

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest      # or: python3 -m unittest discover
```

Tests are fully offline — the LLM rewrite path is tested against an injected
fake client (`tests/fakes.py`); no test makes a live network call.

## crol-list: the reference consumer

reading-gate was scoped against crol-list's own pages as its first real
corpus. See
[`data/reading-gate-b1/crol-integration.md`](data/reading-gate-b1/crol-integration.md)
for the exact drop-in: ratchet mode across its six pages, the `nycsg7`
preset, and a ready-to-paste CI job.

## License

MIT.
