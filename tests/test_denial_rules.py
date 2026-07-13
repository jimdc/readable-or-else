import unittest

from readable_or_else.denial_rules import (
    DenialConfig,
    DenialOutcome,
    rule_grade_target,
    rule_length_ratio,
    rule_markup_integrity,
    rule_meaning_preserved,
    run_denial_rules,
)

COMPLEX_PASSAGE = (
    "Notwithstanding the aforementioned regulatory considerations, applicants "
    "must remit $500 to the Department of Buildings via https://example.gov/pay "
    "in order to obtain provisional authorization from the New York City Council."
)

GOOD_SIMPLE_REWRITE = (
    "You must pay $500 to the Department of Buildings. Pay at "
    "https://example.gov/pay. This gets you provisional approval from the "
    "New York City Council."
)


class TestRuleGradeTarget(unittest.TestCase):
    def test_passes_when_candidate_meets_target(self):
        outcome = rule_grade_target(COMPLEX_PASSAGE, GOOD_SIMPLE_REWRITE, target_grade=7, language="en")
        self.assertFalse(outcome.denied)

    def test_denies_when_candidate_still_over_target(self):
        outcome = rule_grade_target(COMPLEX_PASSAGE, COMPLEX_PASSAGE, target_grade=7, language="en")
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "grade_target")


class TestRuleMeaningPreserved(unittest.TestCase):
    def test_passes_when_tokens_preserved(self):
        outcome = rule_meaning_preserved(COMPLEX_PASSAGE, GOOD_SIMPLE_REWRITE)
        self.assertFalse(outcome.denied)

    def test_denies_when_number_dropped(self):
        candidate = GOOD_SIMPLE_REWRITE.replace("$500", "a fee")
        outcome = rule_meaning_preserved(COMPLEX_PASSAGE, candidate)
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "meaning_preserved")
        self.assertIn("numbers", outcome.detail)

    def test_denies_when_url_dropped(self):
        candidate = GOOD_SIMPLE_REWRITE.replace("https://example.gov/pay", "our website")
        outcome = rule_meaning_preserved(COMPLEX_PASSAGE, candidate)
        self.assertTrue(outcome.denied)
        self.assertIn("urls", outcome.detail)

    def test_denies_when_entity_dropped(self):
        candidate = GOOD_SIMPLE_REWRITE.replace("New York City Council", "the council")
        outcome = rule_meaning_preserved(COMPLEX_PASSAGE, candidate)
        self.assertTrue(outcome.denied)
        self.assertIn("entities", outcome.detail)


class TestRuleLengthRatio(unittest.TestCase):
    def test_passes_within_default_band(self):
        outcome = rule_length_ratio("The cat sat on the mat.", "The cat sat there.")
        self.assertFalse(outcome.denied)

    def test_denies_drastic_truncation(self):
        outcome = rule_length_ratio(COMPLEX_PASSAGE, "Yes.")
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "length_ratio")

    def test_denies_drastic_padding(self):
        outcome = rule_length_ratio("Pay the fee.", "Pay the fee. " * 20)
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "length_ratio")

    def test_respects_configured_ratio_bounds(self):
        original = "Pay the fee now."
        candidate = "Pay."
        self.assertTrue(rule_length_ratio(original, candidate).denied)
        outcome = rule_length_ratio(original, candidate, min_length_ratio=0.1)
        self.assertFalse(outcome.denied)

    def test_empty_original_never_denies(self):
        outcome = rule_length_ratio("   ", "anything at all here")
        self.assertFalse(outcome.denied)


class TestRuleMarkupIntegrity(unittest.TestCase):
    def test_passes_plain_text(self):
        outcome = rule_markup_integrity("The cat sat.", "The cat sat there.")
        self.assertFalse(outcome.denied)

    def test_denies_candidate_with_raw_angle_bracket(self):
        outcome = rule_markup_integrity("The cat sat.", "The cat <b>sat</b>.")
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "markup_integrity")


class TestRunDenialRules(unittest.TestCase):
    def test_all_rules_pass_returns_ok(self):
        outcome = run_denial_rules(
            COMPLEX_PASSAGE, GOOD_SIMPLE_REWRITE, target_grade=7, language="en"
        )
        self.assertFalse(outcome.denied)

    def test_stops_at_first_denial_grade_before_meaning(self):
        # Still over target AND drops a number -- grade_target should fire first.
        candidate = COMPLEX_PASSAGE.replace("$500", "a fee")
        outcome = run_denial_rules(COMPLEX_PASSAGE, candidate, target_grade=7, language="en")
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "grade_target")

    def test_extra_denial_can_reject_a_passing_candidate(self):
        def banned_word(original, candidate):
            if "approve" in candidate.lower() or "approval" in candidate.lower():
                return DenialOutcome.deny("house_style", "candidate uses banned word 'approval'")
            return DenialOutcome.ok()

        config = DenialConfig(extra_denials=[banned_word])
        outcome = run_denial_rules(
            COMPLEX_PASSAGE, GOOD_SIMPLE_REWRITE, target_grade=7, language="en", config=config
        )
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "house_style")

    def test_configured_length_ratio_threads_through(self):
        original = "Pay the fee now."
        candidate = "Pay the fee now in full immediately without any delay whatsoever please."
        config = DenialConfig(max_length_ratio=1.5)
        outcome = run_denial_rules(original, candidate, target_grade=20, language="en", config=config)
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "length_ratio")


if __name__ == "__main__":
    unittest.main()
