import unittest

from reading_gate.baseline import new_baseline, tighten_entry
from reading_gate.gate import evaluate_file, overall_passed
from reading_gate.measure import Measurement
from reading_gate.presets import custom_preset, get_preset


def m(grade, language="en"):
    return Measurement(
        language=language,
        word_count=10,
        sentence_count=2,
        grade=grade,
        grade_formula="flesch_kincaid_grade",
    )


class TestGateMode(unittest.TestCase):
    def test_pass_under_max(self):
        r = evaluate_file("a.html", m(5.0), custom_preset(7), "gate")
        self.assertEqual(r.status, "pass")

    def test_fail_over_max(self):
        r = evaluate_file("a.html", m(9.0), custom_preset(7), "gate")
        self.assertEqual(r.status, "fail")
        self.assertFalse(overall_passed([r]))

    def test_boundary_equal_to_max_passes(self):
        r = evaluate_file("a.html", m(7.0), custom_preset(7), "gate")
        self.assertEqual(r.status, "pass")


class TestWarnMode(unittest.TestCase):
    def test_over_max_warns_but_never_fails(self):
        r = evaluate_file("a.html", m(12.0), custom_preset(7), "warn")
        self.assertEqual(r.status, "warn")
        self.assertTrue(overall_passed([r]))


class TestRatchetMode(unittest.TestCase):
    def test_no_baseline_entry_falls_back_to_gate(self):
        baseline = new_baseline("custom")
        r = evaluate_file("a.html", m(9.0), custom_preset(7), "ratchet", baseline)
        self.assertEqual(r.status, "fail")

        r2 = evaluate_file("a.html", m(5.0), custom_preset(7), "ratchet", baseline)
        self.assertEqual(r2.status, "pass")

    def test_regression_fails(self):
        baseline = new_baseline("custom")
        tighten_entry(baseline, "a.html", 10.0, "flesch_kincaid_grade", "en")
        r = evaluate_file("a.html", m(11.0), custom_preset(7), "ratchet", baseline)
        self.assertEqual(r.status, "fail")
        self.assertIn("regression", r.reason)

    def test_improvement_passes_even_if_still_over_target(self):
        baseline = new_baseline("custom")
        tighten_entry(baseline, "a.html", 10.0, "flesch_kincaid_grade", "en")
        r = evaluate_file("a.html", m(9.5), custom_preset(7), "ratchet", baseline)
        self.assertEqual(r.status, "pass")
        self.assertIn("still over preset target", r.reason)

    def test_equal_to_baseline_passes(self):
        baseline = new_baseline("custom")
        tighten_entry(baseline, "a.html", 10.0, "flesch_kincaid_grade", "en")
        r = evaluate_file("a.html", m(10.0), custom_preset(7), "ratchet", baseline)
        self.assertEqual(r.status, "pass")


class TestMeasureOnlyLanguage(unittest.TestCase):
    def test_spanish_result_is_measure_only_not_gated(self):
        r = evaluate_file("a.html", m(None, language="es"), custom_preset(7), "gate")
        self.assertEqual(r.status, "measure-only")
        self.assertTrue(overall_passed([r]))


class TestWcagAaaNeverHardFails(unittest.TestCase):
    def test_gate_mode_downgrades_to_warn(self):
        preset = get_preset("wcag-aaa")
        r = evaluate_file("a.html", m(15.0), preset, "gate")
        self.assertEqual(r.status, "warn")
        self.assertTrue(overall_passed([r]))

    def test_ratchet_mode_also_downgrades_to_warn(self):
        preset = get_preset("wcag-aaa")
        baseline = new_baseline("wcag-aaa")
        r = evaluate_file("a.html", m(15.0), preset, "ratchet", baseline)
        self.assertEqual(r.status, "warn")


class TestPresets(unittest.TestCase):
    def test_nycsg7_max_grade_is_seven(self):
        self.assertEqual(get_preset("nycsg7").max_grade, 7)

    def test_unknown_preset_raises(self):
        with self.assertRaises(ValueError):
            get_preset("not-a-real-preset")


if __name__ == "__main__":
    unittest.main()
