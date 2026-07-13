"""Output formatting: json, table, gh-annotations, and PR-comment markdown."""

import json

from .gate import FileResult
from .llm import RewriteResult

STATUS_TO_GH_LEVEL = {"fail": "error", "warn": "warning", "measure-only": "notice"}


def to_json(results: list[FileResult], rewrites: dict[str, RewriteResult] | None = None) -> str:
    payload = []
    rewrites = rewrites or {}
    for r in results:
        entry = {
            "path": r.path,
            "language": r.measurement.language,
            "status": r.status,
            "reason": r.reason,
            "grade": r.measurement.grade,
            "grade_formula": r.measurement.grade_formula,
            "max_grade": r.max_grade,
            "baseline_grade": r.baseline_grade,
            "word_count": r.measurement.word_count,
            "sentence_count": r.measurement.sentence_count,
            "details": r.measurement.details,
        }
        rewrite = rewrites.get(r.path)
        if rewrite is not None:
            entry["rewrite"] = {
                "accepted": rewrite.accepted,
                "reason": rewrite.reason,
                "before_grade": rewrite.before_grade,
                "after_grade": rewrite.after_grade,
                "candidate_text": rewrite.candidate_text,
            }
        payload.append(entry)
    return json.dumps(payload, indent=2)


def to_table(results: list[FileResult]) -> str:
    header = f"{'STATUS':<14}{'PATH':<30}{'GRADE':>8}{'MAX':>8}  REASON"
    lines = [header, "-" * len(header)]
    for r in results:
        grade = f"{r.measurement.grade:.2f}" if r.measurement.grade is not None else "n/a"
        max_grade = f"{r.max_grade}" if r.max_grade is not None else "n/a"
        lines.append(f"{r.status:<14}{r.path:<30}{grade:>8}{max_grade:>8}  {r.reason}")
    return "\n".join(lines)


def to_gh_annotations(results: list[FileResult]) -> str:
    lines = []
    for r in results:
        level = STATUS_TO_GH_LEVEL.get(r.status)
        if level is None:  # "pass" — nothing to annotate
            continue
        message = r.reason.replace("\n", " ").replace("%", "%25").replace("\r", "")
        lines.append(f"::{level} file={r.path}::{message}")
    return "\n".join(lines)


def rewrite_suggestion_markdown(path: str, rewrite: RewriteResult) -> str:
    lines = [f"### Suggested rewrite for `{path}`", ""]
    if rewrite.before_grade is not None:
        lines.append(f"Current grade: **{rewrite.before_grade:.2f}**")
    if not rewrite.accepted:
        lines.append(f"\n_Suggestion not applied: {rewrite.reason}_")
        if rewrite.candidate_text:
            lines.append("\n<details><summary>Rejected candidate (for reference)</summary>\n")
            lines.append(f"```\n{rewrite.candidate_text}\n```")
            lines.append("</details>")
        return "\n".join(lines)

    lines.append(f"Candidate grade: **{rewrite.after_grade:.2f}**")
    lines.append("")
    lines.append("**Original:**")
    lines.append(f"> {rewrite.original_text}")
    lines.append("")
    lines.append("**Suggested rewrite** (not auto-applied — review before accepting):")
    lines.append(f"> {rewrite.candidate_text}")
    return "\n".join(lines)


def format_results(
    results: list[FileResult],
    fmt: str,
    rewrites: dict[str, RewriteResult] | None = None,
) -> str:
    if fmt == "json":
        return to_json(results, rewrites)
    if fmt == "table":
        return to_table(results)
    if fmt == "gh-annotations":
        return to_gh_annotations(results)
    raise ValueError(f"unknown format {fmt!r}; expected json, table, or gh-annotations")
