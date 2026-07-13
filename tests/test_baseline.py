import json
import os
import tempfile
import unittest

from reading_gate.baseline import (
    BASELINE_VERSION,
    entry_grade,
    load_baseline,
    new_baseline,
    save_baseline,
    tighten_entry,
)


class TestBaseline(unittest.TestCase):
    def test_new_baseline_shape(self):
        b = new_baseline("nycsg7")
        self.assertEqual(b["version"], BASELINE_VERSION)
        self.assertEqual(b["preset"], "nycsg7")
        self.assertEqual(b["entries"], {})

    def test_tighten_entry_adds_missing(self):
        b = new_baseline("nycsg7")
        changed = tighten_entry(b, "a.html", 10.0, "flesch_kincaid_grade", "en")
        self.assertTrue(changed)
        self.assertEqual(entry_grade(b, "a.html"), 10.0)

    def test_tighten_entry_lowers_grade(self):
        b = new_baseline("nycsg7")
        tighten_entry(b, "a.html", 10.0, "flesch_kincaid_grade", "en")
        changed = tighten_entry(b, "a.html", 8.0, "flesch_kincaid_grade", "en")
        self.assertTrue(changed)
        self.assertEqual(entry_grade(b, "a.html"), 8.0)

    def test_tighten_entry_refuses_to_raise_grade(self):
        b = new_baseline("nycsg7")
        tighten_entry(b, "a.html", 8.0, "flesch_kincaid_grade", "en")
        changed = tighten_entry(b, "a.html", 10.0, "flesch_kincaid_grade", "en")
        self.assertFalse(changed)
        self.assertEqual(entry_grade(b, "a.html"), 8.0)

    def test_entry_grade_missing_is_none(self):
        b = new_baseline("nycsg7")
        self.assertIsNone(entry_grade(b, "missing.html"))

    def test_save_and_load_roundtrip(self):
        b = new_baseline("nycsg7")
        tighten_entry(b, "a.html", 8.0, "flesch_kincaid_grade", "en")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baseline.json")
            save_baseline(path, b)
            loaded = load_baseline(path)
            self.assertEqual(loaded, b)

    def test_load_rejects_unknown_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baseline.json")
            with open(path, "w") as f:
                json.dump({"version": 999, "preset": "nycsg7", "entries": {}}, f)
            with self.assertRaises(ValueError):
                load_baseline(path)


if __name__ == "__main__":
    unittest.main()
