"""Committed-baseline file format for ratchet mode.

A baseline is a small JSON file, committed to the repo, that records the
readability grade of each gated input at the time it was last accepted. Ratchet
mode (see gate.py) fails a file only if its grade regresses (gets worse) versus
its committed baseline entry — the same "may only shrink" contract used by
allowlist-style CI gates elsewhere. A file with no baseline entry has no history
to ratchet against, so it falls back to a direct gate against the preset's
max_grade.
"""

import json

BASELINE_VERSION = 1


def load_baseline(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != BASELINE_VERSION:
        raise ValueError(
            f"unsupported baseline version {data.get('version')!r} in {path!r}; "
            f"expected {BASELINE_VERSION}"
        )
    return data


def new_baseline(preset_name: str) -> dict:
    return {"version": BASELINE_VERSION, "preset": preset_name, "entries": {}}


def save_baseline(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def entry_grade(baseline: dict, file_path: str) -> float | None:
    entry = baseline.get("entries", {}).get(file_path)
    return entry["grade"] if entry else None


def tighten_entry(baseline: dict, file_path: str, grade: float, formula: str, language: str) -> bool:
    """Record `grade` for `file_path` only if it improves (lowers) on the
    existing entry, or if there is no existing entry. Returns True if the
    baseline was changed."""
    entries = baseline.setdefault("entries", {})
    current = entries.get(file_path)
    if current is not None and grade >= current["grade"]:
        return False
    entries[file_path] = {"grade": grade, "formula": formula, "language": language}
    return True
