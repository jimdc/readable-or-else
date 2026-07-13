"""Threshold gate / warn / ratchet decision logic.

Pure arithmetic and policy — no LLM calls, no I/O beyond what's handed in.
See baseline.py for the ratchet contract.
"""

from dataclasses import dataclass

from .baseline import entry_grade
from .measure import Measurement
from .presets import Preset

RATCHET_TOLERANCE = 0.01

VALID_MODES = ("gate", "warn", "ratchet")


@dataclass
class FileResult:
    path: str
    measurement: Measurement
    status: str  # "pass" | "warn" | "fail" | "measure-only"
    reason: str
    baseline_grade: float | None = None
    max_grade: float | None = None


def evaluate_file(
    path: str,
    measurement: Measurement,
    preset: Preset,
    mode: str,
    baseline: dict | None = None,
) -> FileResult:
    if mode not in VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {VALID_MODES}")

    grade = measurement.grade
    max_grade = preset.max_grade

    if grade is None:
        return FileResult(
            path=path,
            measurement=measurement,
            status="measure-only",
            reason=(
                f"language {measurement.language!r} has no gating formula in v1 "
                "(measured, not gated)"
            ),
            max_grade=max_grade,
        )

    # WCAG-AAA-style presets never hard-fail a build; downgrade to warn semantics.
    effective_mode = mode if preset.hard_gate else "warn"
    over_target = max_grade is not None and grade > max_grade

    if effective_mode == "warn":
        status = "warn" if over_target else "pass"
        reason = (
            f"grade {grade:.2f} exceeds preset max {max_grade}"
            if over_target
            else f"grade {grade:.2f} within preset max {max_grade}"
        )
        if not preset.hard_gate and over_target:
            reason += " (flag-only preset: provide a simplified supplement)"
        return FileResult(path, measurement, status, reason, max_grade=max_grade)

    if effective_mode == "gate":
        status = "fail" if over_target else "pass"
        reason = (
            f"grade {grade:.2f} exceeds preset max {max_grade}"
            if over_target
            else f"grade {grade:.2f} within preset max {max_grade}"
        )
        return FileResult(path, measurement, status, reason, max_grade=max_grade)

    # ratchet
    baseline_grade = entry_grade(baseline, path) if baseline else None
    if baseline_grade is None:
        status = "fail" if over_target else "pass"
        reason = (
            f"no baseline entry for {path!r}; new files must meet preset max_grade "
            f"directly (grade {grade:.2f}, max {max_grade})"
        )
        return FileResult(path, measurement, status, reason, baseline_grade, max_grade)

    if grade > baseline_grade + RATCHET_TOLERANCE:
        status = "fail"
        reason = (
            f"regression: grade {grade:.2f} is worse than committed baseline "
            f"{baseline_grade:.2f}"
        )
    else:
        status = "pass"
        reason = f"grade {grade:.2f} meets committed baseline {baseline_grade:.2f}"
        if over_target:
            reason += f" (still over preset target {max_grade}, tracked for future ratchet)"

    return FileResult(path, measurement, status, reason, baseline_grade, max_grade)


def overall_passed(results: list[FileResult]) -> bool:
    return not any(r.status == "fail" for r in results)
