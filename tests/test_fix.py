import unittest

from readable_or_else.denial_rules import DenialConfig
from readable_or_else.fix import attempt_fix, fix_text
from tests.fakes import ErroringLLMClient, FakeLLMClient
from readable_or_else.llm import CallBudgetExceeded, RewriteUnavailable

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


class TestAttemptFix(unittest.TestCase):
    def test_accepts_and_applies_on_first_try(self):
        client = FakeLLMClient(lambda system, user: GOOD_SIMPLE_REWRITE)
        result = attempt_fix(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertTrue(result.applied)
        self.assertEqual(result.candidate_text, GOOD_SIMPLE_REWRITE)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.rule, "")

    def test_retries_with_feedback_and_succeeds_second_attempt(self):
        responses = iter([
            GOOD_SIMPLE_REWRITE.replace("$500", "a fee"),  # first attempt: on-grade but drops the number
            GOOD_SIMPLE_REWRITE,                            # second attempt: good
        ])
        client = FakeLLMClient(lambda system, user: next(responses))
        result = attempt_fix(COMPLEX_PASSAGE, target_grade=7, language="en", client=client, max_retries=1)

        self.assertTrue(result.applied)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(client.calls), 2)
        # The retry prompt must name the rule and reason the first attempt was denied.
        second_system = client.calls[1][0]
        self.assertIn("meaning_preserved", second_system)

    def test_denied_after_exhausting_retries_reports_last_rule(self):
        # "Rewrite" never changes anything -- always over target.
        client = FakeLLMClient(lambda system, user: COMPLEX_PASSAGE)
        result = attempt_fix(COMPLEX_PASSAGE, target_grade=7, language="en", client=client, max_retries=1)

        self.assertFalse(result.applied)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.rule, "grade_target")
        self.assertEqual(len(client.calls), 2)

    def test_max_retries_zero_makes_a_single_attempt(self):
        client = FakeLLMClient(lambda system, user: COMPLEX_PASSAGE)
        result = attempt_fix(COMPLEX_PASSAGE, target_grade=7, language="en", client=client, max_retries=0)
        self.assertFalse(result.applied)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(client.calls), 1)

    def test_llm_unavailable_short_circuits(self):
        client = ErroringLLMClient(RewriteUnavailable("endpoint down"))
        result = attempt_fix(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertFalse(result.applied)
        self.assertEqual(result.rule, "llm_unavailable")
        self.assertIn("endpoint down", result.reason)

    def test_call_budget_exceeded_reports_its_own_rule(self):
        client = ErroringLLMClient(CallBudgetExceeded("call budget exceeded: reached"))
        result = attempt_fix(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertFalse(result.applied)
        self.assertEqual(result.rule, "budget_exceeded")
        self.assertIn("call budget exceeded", result.reason)

    def test_configured_denial_config_threads_through(self):
        # Force a length-ratio denial via a tight custom config, on an otherwise-good rewrite.
        client = FakeLLMClient(lambda system, user: GOOD_SIMPLE_REWRITE)
        tight_config = DenialConfig(max_length_ratio=0.5)
        result = attempt_fix(
            COMPLEX_PASSAGE, target_grade=7, language="en", client=client,
            denial_config=tight_config, max_retries=0,
        )
        self.assertFalse(result.applied)
        self.assertEqual(result.rule, "length_ratio")


class TestFixText(unittest.TestCase):
    def test_under_target_passage_is_left_untouched(self):
        client = FakeLLMClient(lambda system, user: "should never be called")
        text = "The cat sat. It was happy. We saw it run."
        new_text, results = fix_text(text, target_grade=7, language="en", client=client)
        self.assertEqual(new_text, text)
        self.assertEqual(results, [])
        self.assertEqual(len(client.calls), 0)

    def test_over_target_passage_gets_applied(self):
        client = FakeLLMClient(lambda system, user: GOOD_SIMPLE_REWRITE)
        new_text, results = fix_text(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertEqual(new_text, GOOD_SIMPLE_REWRITE)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].applied)

    def test_denied_passage_leaves_file_unchanged(self):
        client = FakeLLMClient(lambda system, user: COMPLEX_PASSAGE)
        new_text, results = fix_text(COMPLEX_PASSAGE, target_grade=7, language="en", client=client, max_retries=0)
        self.assertEqual(new_text, COMPLEX_PASSAGE)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].applied)


if __name__ == "__main__":
    unittest.main()
