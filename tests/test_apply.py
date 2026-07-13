import unittest

from readable_or_else.apply import fix_html
from tests.fakes import FakeLLMClient

HARD_SENTENCE = (
    "Notwithstanding the aforementioned regulatory considerations, applicants "
    "must remit $500 to the Department of Buildings via https://example.gov/pay "
    "in order to obtain provisional authorization from the New York City Council."
)

GOOD_REWRITE = (
    "You must pay $500 to the Department of Buildings. Pay at "
    "https://example.gov/pay. This gets you provisional approval from the "
    "New York City Council."
)


class TestFixHtmlAppliesInPlace(unittest.TestCase):
    def test_over_target_paragraph_is_rewritten_markup_untouched_elsewhere(self):
        html = (
            '<html><head><title>City Rules</title></head>'
            '<body class="page">'
            '<h1 id="top">City Rules</h1>'
            f"<p>{HARD_SENTENCE}</p>"
            '<footer>&copy; 2026 City</footer>'
            "</body></html>"
        )
        client = FakeLLMClient(lambda system, user: GOOD_REWRITE)
        new_html, results, skipped = fix_html(html, target_grade=7, language="en", client=client)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].applied)
        self.assertEqual(skipped, 0)
        self.assertIn(GOOD_REWRITE, new_html)
        self.assertNotIn(HARD_SENTENCE, new_html)
        # Everything else is untouched.
        self.assertIn('<title>City Rules</title>', new_html)
        self.assertIn('<h1 id="top">City Rules</h1>', new_html)
        self.assertIn('<body class="page">', new_html)
        self.assertIn("2026 City", new_html)

    def test_denied_candidate_leaves_html_unchanged(self):
        html = f"<p>{HARD_SENTENCE}</p>"
        client = FakeLLMClient(lambda system, user: HARD_SENTENCE)  # "rewrite" = no change
        new_html, results, skipped = fix_html(html, target_grade=7, language="en", client=client, max_retries=0)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].applied)
        self.assertEqual(results[0].rule, "grade_target")
        self.assertIn(HARD_SENTENCE, new_html)

    def test_paragraph_with_nested_link_is_skipped_not_touched(self):
        html = (
            "<p>"
            + HARD_SENTENCE
            + ' See <a href="https://example.gov/pay">the payment portal</a> for details.'
            "</p>"
        )
        client = FakeLLMClient(lambda system, user: GOOD_REWRITE)
        new_html, results, skipped = fix_html(html, target_grade=7, language="en", client=client)

        self.assertEqual(results, [])
        self.assertEqual(skipped, 1)
        self.assertEqual(len(client.calls), 0)  # never even attempted -- cost-conscious
        self.assertIn('<a href="https://example.gov/pay">the payment portal</a>', new_html)
        self.assertIn(HARD_SENTENCE, new_html)

    def test_under_target_paragraph_is_left_alone(self):
        html = "<p>The cat sat. It was happy. We saw it run.</p>"
        client = FakeLLMClient(lambda system, user: "should never be called")
        new_html, results, skipped = fix_html(html, target_grade=7, language="en", client=client)

        self.assertEqual(results, [])
        self.assertEqual(skipped, 0)
        self.assertEqual(len(client.calls), 0)
        self.assertIn("The cat sat. It was happy. We saw it run.", new_html)

    def test_multiple_leaf_elements_only_over_target_ones_touched(self):
        html = (
            "<ul>"
            "<li>The cat sat.</li>"
            f"<li>{HARD_SENTENCE}</li>"
            "</ul>"
        )
        client = FakeLLMClient(lambda system, user: GOOD_REWRITE)
        new_html, results, skipped = fix_html(html, target_grade=7, language="en", client=client)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].applied)
        self.assertIn("<li>The cat sat.</li>", new_html)
        self.assertIn(GOOD_REWRITE, new_html)

    def test_script_and_style_content_never_considered(self):
        html = (
            "<html><body>"
            "<script>var x = 'Notwithstanding aforementioned considerations apply here.';</script>"
            "<style>.a { content: 'aforementioned regulatory considerations'; }</style>"
            "<p>The cat sat. It was happy.</p>"
            "</body></html>"
        )
        client = FakeLLMClient(lambda system, user: "should never be called")
        new_html, results, skipped = fix_html(html, target_grade=7, language="en", client=client)
        self.assertEqual(results, [])
        self.assertEqual(len(client.calls), 0)


if __name__ == "__main__":
    unittest.main()
