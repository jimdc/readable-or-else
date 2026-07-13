"""readable-or-else CLI."""

import argparse
import sys

from .apply import fix_html
from .baseline import load_baseline, new_baseline, save_baseline, tighten_entry
from .denial_rules import (
    DenialConfig,
    DEFAULT_INLINE_DOMINANT_RATIO,
    DEFAULT_MAX_LENGTH_RATIO,
    DEFAULT_MIN_LENGTH_RATIO,
)
from .extract import extract_visible_text, DomRenderedNotImplemented, extract_dom_rendered
from .fix import FileFixReport, fix_text
from .gate import evaluate_file, overall_passed
from .llm import LLMClient, LLMConfig, RewriteUnavailable, rewrite_passage
from .measure import measure
from .presets import custom_preset, get_preset
from .report import format_fix_report, format_results, rewrite_suggestion_markdown

HTML_EXTENSIONS = (".html", ".htm")


def read_source_text(path: str, extract_mode: str) -> str:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    if not path.endswith(HTML_EXTENSIONS):
        return raw
    if extract_mode == "dom-rendered":
        return extract_dom_rendered(path)
    return extract_visible_text(raw)


def resolve_preset(args):
    if args.preset == "custom":
        if args.max_grade is None:
            raise SystemExit("--preset custom requires --max-grade")
        return custom_preset(args.max_grade)
    preset = get_preset(args.preset)
    if args.max_grade is not None:
        preset = type(preset)(**{**preset.__dict__, "max_grade": args.max_grade})
    return preset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="readable-or-else")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="measure and gate files against a preset")
    check.add_argument("files", nargs="+")
    check.add_argument("--preset", default="nycsg7", choices=["nycsg7", "govuk9", "wcag-aaa", "custom"])
    check.add_argument("--max-grade", type=float, default=None)
    check.add_argument("--mode", default="gate", choices=["gate", "warn", "ratchet"])
    check.add_argument("--lang", default="en")
    check.add_argument("--extract", default="html", choices=["html", "dom-rendered"])
    check.add_argument("--baseline", default=None, help="baseline JSON file (required for ratchet mode)")
    check.add_argument("--suggest", action="store_true", help="call configured LLM to suggest rewrites for over-target files")
    check.add_argument("--format", default="table", choices=["json", "table", "gh-annotations"])

    baseline_cmd = sub.add_parser("baseline", help="write or tighten a committed baseline file")
    baseline_cmd.add_argument("files", nargs="+")
    baseline_cmd.add_argument("--preset", default="nycsg7", choices=["nycsg7", "govuk9", "wcag-aaa", "custom"])
    baseline_cmd.add_argument("--max-grade", type=float, default=None)
    baseline_cmd.add_argument("--lang", default="en")
    baseline_cmd.add_argument("--extract", default="html", choices=["html", "dom-rendered"])
    baseline_cmd.add_argument("-o", "--output", required=True)

    fix = sub.add_parser(
        "fix", help="rewrite over-target passages via the configured LLM and apply accepted candidates in place"
    )
    fix.add_argument("files", nargs="+")
    fix.add_argument("--preset", default="nycsg7", choices=["nycsg7", "govuk9", "wcag-aaa", "custom"])
    fix.add_argument("--max-grade", type=float, default=None)
    fix.add_argument("--lang", default="en")
    fix.add_argument("--max-retries", type=int, default=1, help="bounded retry-with-feedback attempts after a denial")
    fix.add_argument("--min-length-ratio", type=float, default=DEFAULT_MIN_LENGTH_RATIO)
    fix.add_argument("--max-length-ratio", type=float, default=DEFAULT_MAX_LENGTH_RATIO)
    fix.add_argument(
        "--inline-dominant-ratio", type=float, default=DEFAULT_INLINE_DOMINANT_RATIO,
        help="deny a mixed-content passage without calling the LLM when inline elements "
             "(links, bold, etc.) make up at least this fraction of its text",
    )
    fix.add_argument("--format", default="table", choices=["json", "table"])

    return parser


def run_check(args) -> int:
    preset = resolve_preset(args)
    baseline = load_baseline(args.baseline) if args.baseline and args.mode == "ratchet" else None
    if args.mode == "ratchet" and baseline is None:
        raise SystemExit("--mode ratchet requires --baseline <file>")

    results = []
    for path in args.files:
        try:
            text = read_source_text(path, args.extract)
        except DomRenderedNotImplemented as exc:
            raise SystemExit(str(exc)) from exc
        m = measure(text, language=args.lang)
        results.append(evaluate_file(path, m, preset, args.mode, baseline))

    rewrites = {}
    if args.suggest:
        over_target = [
            r for r in results
            if r.measurement.grade is not None
            and r.max_grade is not None
            and r.measurement.grade > r.max_grade
        ]
        if over_target:
            try:
                client = LLMClient(LLMConfig.from_env())
            except RewriteUnavailable as exc:
                print(f"--suggest requested but unavailable: {exc}", file=sys.stderr)
                client = None
            if client is not None:
                for r in over_target:
                    text = read_source_text(r.path, args.extract)
                    rewrites[r.path] = rewrite_passage(text, r.max_grade, r.measurement.language, client)

    print(format_results(results, args.format, rewrites))

    if rewrites:
        print()
        for path, rewrite in rewrites.items():
            print(rewrite_suggestion_markdown(path, rewrite))
            print()

    return 0 if overall_passed(results) else 1


def run_baseline(args) -> int:
    preset = resolve_preset(args)
    try:
        data = load_baseline(args.output)
    except (FileNotFoundError, OSError):
        data = new_baseline(preset.name)

    changed = False
    for path in args.files:
        try:
            text = read_source_text(path, args.extract)
        except DomRenderedNotImplemented as exc:
            raise SystemExit(str(exc)) from exc
        m = measure(text, language=args.lang)
        if m.grade is None:
            continue
        if tighten_entry(data, path, m.grade, m.grade_formula, m.language):
            changed = True

    save_baseline(args.output, data)
    print(f"baseline written to {args.output} ({'updated' if changed else 'unchanged'})")
    return 0


def run_fix(args, llm_client=None) -> int:
    preset = resolve_preset(args)
    if preset.max_grade is None:
        raise SystemExit("fix mode requires a preset with a numeric max_grade")

    if llm_client is None:
        try:
            llm_client = LLMClient(LLMConfig.from_env())
        except RewriteUnavailable as exc:
            raise SystemExit(f"fix mode requires a configured LLM: {exc}") from exc

    denial_config = DenialConfig(
        min_length_ratio=args.min_length_ratio,
        max_length_ratio=args.max_length_ratio,
        inline_dominant_ratio=args.inline_dominant_ratio,
    )

    reports = []
    any_denied = False
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            raw = f.read()

        skipped = 0
        if path.endswith(HTML_EXTENSIONS):
            new_content, results, skipped = fix_html(
                raw, preset.max_grade, args.lang, llm_client, denial_config, args.max_retries
            )
        else:
            new_content, results = fix_text(
                raw, preset.max_grade, args.lang, llm_client, denial_config, args.max_retries
            )

        changed = new_content != raw
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

        any_denied = any_denied or any(not r.applied for r in results) or skipped > 0
        reports.append(FileFixReport(path=path, changed=changed, results=results, skipped_nested_markup=skipped))

    print(format_fix_report(reports, args.format))
    return 1 if any_denied else 0


def main(argv=None, llm_client=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        return run_check(args)
    if args.command == "baseline":
        return run_baseline(args)
    if args.command == "fix":
        return run_fix(args, llm_client=llm_client)
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
