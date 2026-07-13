import unittest

from readable_or_else.llm import (
    LLMConfig,
    RewriteUnavailable,
    check_meaning_preserved,
    rewrite_passage,
)
from tests.fakes import ErroringLLMClient, FakeLLMClient

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


class TestCheckMeaningPreserved(unittest.TestCase):
    def test_identical_text_passes(self):
        result = check_meaning_preserved(COMPLEX_PASSAGE, COMPLEX_PASSAGE)
        self.assertTrue(result.passed)

    def test_dropped_number_fails(self):
        candidate = COMPLEX_PASSAGE.replace("$500", "a fee")
        result = check_meaning_preserved(COMPLEX_PASSAGE, candidate)
        self.assertFalse(result.passed)
        self.assertIn("numbers", result.missing)

    def test_dropped_url_fails(self):
        candidate = COMPLEX_PASSAGE.replace("https://example.gov/pay", "our website")
        result = check_meaning_preserved(COMPLEX_PASSAGE, candidate)
        self.assertFalse(result.passed)
        self.assertIn("urls", result.missing)

    def test_dropped_entity_fails(self):
        candidate = COMPLEX_PASSAGE.replace("New York City Council", "the council")
        result = check_meaning_preserved(COMPLEX_PASSAGE, candidate)
        self.assertFalse(result.passed)
        self.assertIn("entities", result.missing)

    def test_good_rewrite_passes(self):
        result = check_meaning_preserved(COMPLEX_PASSAGE, GOOD_SIMPLE_REWRITE)
        self.assertTrue(result.passed)


class TestRewritePassage(unittest.TestCase):
    def test_accepts_good_simple_rewrite(self):
        client = FakeLLMClient(lambda system, user: GOOD_SIMPLE_REWRITE)
        result = rewrite_passage(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertTrue(result.accepted)
        self.assertEqual(result.candidate_text, GOOD_SIMPLE_REWRITE)
        self.assertIsNotNone(result.before_grade)
        self.assertLessEqual(result.after_grade, 7)
        self.assertEqual(len(client.calls), 1)

    def test_rejects_candidate_still_over_target(self):
        client = FakeLLMClient(lambda system, user: COMPLEX_PASSAGE)  # "rewrite" = no change
        result = rewrite_passage(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertFalse(result.accepted)
        self.assertIn("still over target", result.reason)

    def test_rejects_candidate_that_drops_a_number(self):
        stripped = GOOD_SIMPLE_REWRITE.replace("$500", "a fee")
        client = FakeLLMClient(lambda system, user: stripped)
        result = rewrite_passage(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertFalse(result.accepted)
        self.assertIn("meaning-preservation", result.reason)

    def test_never_auto_applies_only_returns_suggestion(self):
        client = FakeLLMClient(lambda system, user: GOOD_SIMPLE_REWRITE)
        result = rewrite_passage(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertEqual(result.original_text, COMPLEX_PASSAGE)
        # candidate is only ever data on the result, never written back anywhere
        self.assertTrue(result.accepted)

    def test_client_error_yields_unavailable_reason(self):
        client = ErroringLLMClient(RewriteUnavailable("endpoint down"))
        result = rewrite_passage(COMPLEX_PASSAGE, target_grade=7, language="en", client=client)
        self.assertFalse(result.accepted)
        self.assertIn("endpoint down", result.reason)
        self.assertIsNone(result.candidate_text)


class TestLLMConfigFromEnv(unittest.TestCase):
    def test_missing_env_raises(self):
        import os

        env_backup = {
            k: os.environ.pop(k, None)
            for k in ("READABLE_OR_ELSE_LLM_BASE", "READABLE_OR_ELSE_LLM_MODEL", "READABLE_OR_ELSE_LLM_KEY")
        }
        try:
            with self.assertRaises(RewriteUnavailable):
                LLMConfig.from_env()
        finally:
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v

    def test_present_env_builds_config(self):
        import os

        os.environ["READABLE_OR_ELSE_LLM_BASE"] = "https://api.example.com/v1"
        os.environ["READABLE_OR_ELSE_LLM_MODEL"] = "gpt-4o-mini"
        os.environ.pop("READABLE_OR_ELSE_LLM_KEY", None)
        try:
            config = LLMConfig.from_env()
            self.assertEqual(config.base_url, "https://api.example.com/v1")
            self.assertEqual(config.model, "gpt-4o-mini")
            self.assertEqual(config.api_key, "")
        finally:
            os.environ.pop("READABLE_OR_ELSE_LLM_BASE", None)
            os.environ.pop("READABLE_OR_ELSE_LLM_MODEL", None)


if __name__ == "__main__":
    unittest.main()
