import unittest

from bs4 import BeautifulSoup

from readable_or_else.apply import fix_html
from readable_or_else.denial_rules import DenialConfig, rule_placeholder_preserved
from readable_or_else.fix import attempt_fix_mixed
from readable_or_else.llm import RewriteUnavailable
from readable_or_else.mixed_content import dehydrate, reassemble, serialize_mixed_content
from tests.fakes import ErroringLLMClient, FakeLLMClient


def _el(html, tag="p"):
    return BeautifulSoup(html, "html.parser").find(tag)


class TestSerializeMixedContent(unittest.TestCase):
    def test_link_mid_sentence(self):
        el = _el('<p>See <a href="https://x.gov/pay">the payment portal</a> for details.</p>')
        passage = serialize_mixed_content(el)
        self.assertIsNotNone(passage)
        self.assertEqual(passage.placeholder_text, "See [LINK1:the payment portal] for details.")
        self.assertEqual(passage.dehydrated_text, "See the payment portal for details.")
        self.assertEqual(set(passage.nodes), {"LINK1"})

    def test_multiple_links_indexed_separately(self):
        el = _el('<p>Read <a href="/a">the first notice</a> and <a href="/b">the second notice</a>.</p>')
        passage = serialize_mixed_content(el)
        self.assertEqual(
            passage.placeholder_text,
            "Read [LINK1:the first notice] and [LINK2:the second notice].",
        )
        self.assertEqual(set(passage.nodes), {"LINK1", "LINK2"})

    def test_bold_span(self):
        el = _el("<p>Notices total <b>1.09 million</b> going back to 2003.</p>")
        passage = serialize_mixed_content(el)
        self.assertEqual(
            passage.placeholder_text, "Notices total [BOLD1:1.09 million] going back to 2003."
        )

    def test_mixed_link_and_emphasis(self):
        el = _el('<p>Follow <a href="/x">a contract</a> <em>by interest</em>, not by section.</p>')
        passage = serialize_mixed_content(el)
        self.assertEqual(
            passage.placeholder_text,
            "Follow [LINK1:a contract] [EM1:by interest], not by section.",
        )
        self.assertEqual(set(passage.nodes), {"LINK1", "EM1"})

    def test_pure_leaf_returns_none(self):
        # No inline children at all -- apply.py's existing leaf path already handles this.
        el = _el("<p>No inline markup here at all.</p>")
        self.assertIsNone(serialize_mixed_content(el))

    def test_nested_inline_in_inline_returns_none(self):
        el = _el('<p>See <a href="/x">the <b>payment</b> portal</a> for details.</p>')
        self.assertIsNone(serialize_mixed_content(el))

    def test_unsupported_tag_code_returns_none(self):
        el = _el("<p>Run <code>ror check</code> to verify.</p>")
        self.assertIsNone(serialize_mixed_content(el))

    def test_bracket_bearing_inner_text_returns_none(self):
        el = _el('<p>See <a href="/x">the [payment] portal</a> for details.</p>')
        self.assertIsNone(serialize_mixed_content(el))

    def test_inline_ratio_computed_for_dominant_case(self):
        el = _el('<p><a href="/x">Read more</a></p>')  # entirely link text
        passage = serialize_mixed_content(el)
        self.assertEqual(passage.inline_ratio, 1.0)


class TestDehydrate(unittest.TestCase):
    def test_replaces_tokens_with_original_inner_text(self):
        el = _el('<p>See <a href="/x">the payment portal</a> for details.</p>')
        passage = serialize_mixed_content(el)
        candidate = "For details, see [LINK1:the payment portal]."  # token moved, unaltered
        self.assertEqual(dehydrate(candidate, passage.nodes), "For details, see the payment portal.")

    def test_unknown_token_returns_none(self):
        el = _el('<p>See <a href="/x">the payment portal</a> for details.</p>')
        passage = serialize_mixed_content(el)
        self.assertIsNone(dehydrate("[LINK9:ghost]", passage.nodes))


class TestReassemble(unittest.TestCase):
    def test_reorders_tag_keeps_attributes(self):
        html = '<p>See <a href="https://x.gov/pay" rel="noopener">the payment portal</a> for details.</p>'
        el = BeautifulSoup(html, "html.parser").find("p")
        passage = serialize_mixed_content(el)
        ok = reassemble(el, "For details, see [LINK1:the payment portal].", passage.nodes)
        self.assertTrue(ok)
        self.assertEqual(
            str(el),
            '<p>For details, see <a href="https://x.gov/pay" rel="noopener">the payment portal</a>.</p>',
        )

    def test_unknown_token_leaves_element_untouched(self):
        html = '<p>See <a href="/x">the payment portal</a> for details.</p>'
        el = BeautifulSoup(html, "html.parser").find("p")
        passage = serialize_mixed_content(el)
        ok = reassemble(el, "See [LINK9:ghost] for details.", passage.nodes)
        self.assertFalse(ok)
        self.assertEqual(str(el), html)


class TestRulePlaceholderPreserved(unittest.TestCase):
    def test_passes_when_reordered_but_unaltered(self):
        original = "See [LINK1:the payment portal] for details."
        candidate = "For details, see [LINK1:the payment portal]."
        self.assertFalse(rule_placeholder_preserved(original, candidate).denied)

    def test_denies_when_token_dropped(self):
        original = "See [LINK1:the payment portal] for details."
        candidate = "See the payment portal for details."
        outcome = rule_placeholder_preserved(original, candidate)
        self.assertTrue(outcome.denied)
        self.assertEqual(outcome.rule, "placeholder_preserved")

    def test_denies_when_inner_text_altered(self):
        original = "See [LINK1:the payment portal] for details."
        candidate = "See [LINK1:the payment page] for details."
        self.assertTrue(rule_placeholder_preserved(original, candidate).denied)

    def test_denies_when_token_duplicated(self):
        original = "See [LINK1:the payment portal] for details."
        candidate = "See [LINK1:the payment portal] twice: [LINK1:the payment portal]."
        self.assertTrue(rule_placeholder_preserved(original, candidate).denied)

    def test_denies_when_extra_token_invented(self):
        original = "See [LINK1:the payment portal] for details."
        candidate = "See [LINK1:the payment portal] and [LINK2:a new link] for details."
        self.assertTrue(rule_placeholder_preserved(original, candidate).denied)


HARD_MIXED_HTML = (
    "<p>Notwithstanding the aforementioned regulatory considerations, applicants "
    "must remit $500 to the Department of Buildings via "
    '<a href="https://example.gov/pay">the payment portal</a> in order to obtain '
    "provisional authorization from the New York City Council.</p>"
)

GOOD_MIXED_REWRITE = (
    "You must pay $500 to the Department of Buildings. Pay at "
    "[LINK1:the payment portal]. This gets you provisional approval from the "
    "New York City Council."
)


class TestAttemptFixMixed(unittest.TestCase):
    def _passage(self, html=HARD_MIXED_HTML):
        return serialize_mixed_content(_el(html))

    def test_accepts_and_returns_raw_candidate_for_reassembly(self):
        passage = self._passage()
        client = FakeLLMClient(lambda system, user: GOOD_MIXED_REWRITE)
        result, raw_candidate = attempt_fix_mixed(passage, target_grade=7, language="en", client=client)
        self.assertTrue(result.applied)
        self.assertEqual(raw_candidate, GOOD_MIXED_REWRITE)
        self.assertNotIn("[LINK1", result.candidate_text)  # reporting sees dehydrated prose

    def test_inline_dominant_denies_without_calling_llm(self):
        passage = self._passage('<p><a href="/x">Read more about this program here</a></p>')
        client = FakeLLMClient(lambda system, user: "should never be called")
        result, raw_candidate = attempt_fix_mixed(passage, target_grade=7, language="en", client=client)
        self.assertFalse(result.applied)
        self.assertEqual(result.rule, "inline_dominant")
        self.assertIsNone(raw_candidate)
        self.assertEqual(len(client.calls), 0)

    def test_configurable_inline_dominant_ratio(self):
        # Same passage as the dominant-denial case above, but a looser
        # threshold lets it through to the LLM.
        passage = self._passage('<p><a href="/x">Read more about this program here</a></p>')
        loose_config = DenialConfig(inline_dominant_ratio=1.1)  # ratio is exactly 1.0 here
        client = FakeLLMClient(lambda system, user: "should not matter for this assertion")
        result, _ = attempt_fix_mixed(
            passage, target_grade=7, language="en", client=client,
            denial_config=loose_config, max_retries=0,
        )
        self.assertNotEqual(result.rule, "inline_dominant")
        self.assertEqual(len(client.calls), 1)  # this time the LLM was actually called

    def test_placeholder_denial_then_retry_succeeds(self):
        passage = self._passage()
        responses = iter([
            "You must pay $500 to the Department of Buildings. Pay at the payment "
            "portal. This gets you provisional approval from the New York City "
            "Council.",  # drops the token -- denied
            GOOD_MIXED_REWRITE,  # retry: good
        ])
        client = FakeLLMClient(lambda system, user: next(responses))
        result, raw_candidate = attempt_fix_mixed(
            passage, target_grade=7, language="en", client=client, max_retries=1
        )
        self.assertTrue(result.applied)
        self.assertEqual(result.attempts, 2)
        self.assertIn("placeholder_preserved", client.calls[1][0])  # retry feedback names the rule

    def test_denied_after_exhausting_retries(self):
        passage = self._passage()
        no_token = (
            "You must pay $500 to the Department of Buildings. Pay at the payment "
            "portal. This gets you provisional approval from the New York City Council."
        )
        client = FakeLLMClient(lambda system, user: no_token)
        result, raw_candidate = attempt_fix_mixed(
            passage, target_grade=7, language="en", client=client, max_retries=1
        )
        self.assertFalse(result.applied)
        self.assertEqual(result.rule, "placeholder_preserved")
        self.assertIsNone(raw_candidate)

    def test_llm_unavailable_short_circuits(self):
        passage = self._passage()
        client = ErroringLLMClient(RewriteUnavailable("endpoint down"))
        result, raw_candidate = attempt_fix_mixed(passage, target_grade=7, language="en", client=client)
        self.assertFalse(result.applied)
        self.assertEqual(result.rule, "llm_unavailable")
        self.assertIsNone(raw_candidate)


class TestCrolListRegressionFixture(unittest.TestCase):
    """A real over-target paragraph from crol-list's about.html (the first
    paragraph, https://github.com/jimdc/crol-list/blob/main/about.html,
    measured 2026-07-13). Before this feature, apply.py's leaf-only rule
    would have counted this passage as skipped_nested_markup -- it has two
    <a> tags and one <em> -- with the LLM never even called. It is exactly
    the kind of passage crol-list PR #17 found: most of the over-target
    prose on that site carries at least one inline link.
    """

    CROL_ABOUT_PARAGRAPH = (
        "<p>CROL-List is a search interface over "
        '<a href="https://a856-cityrecord.nyc.gov/" rel="noopener" target="_blank">The City Record</a> '
        "— the\nCity of New York's official daily journal, where "
        '<a href="https://codelibrary.amlegal.com/codes/newyorkcity/latest/NYCcharter/0-0-0-3113" '
        'rel="noopener" target="_blank">every agency must publish</a> its\n'
        "contracts, hearings, rule changes, rezonings, and personnel moves. CROL-List makes that "
        "record searchable\n<em>by interest</em>: follow a contract, decode a job title, track a "
        "rezoning, or get an email when something new matches.</p>"
    )

    GOOD_REWRITE = (
        "CROL-List searches [LINK1:The City Record]. That is the City of New York's daily "
        "public journal. A rule says [LINK2:every agency must publish] there. It covers "
        "contracts, hearings, rule changes, rezonings, and staff changes. You can search it "
        "[EM1:by interest]. Follow a contract. Look up a job. Track a rezoning. Or get an "
        "email when something new matches."
    )

    def test_was_over_target_and_had_nested_markup(self):
        el = _el(self.CROL_ABOUT_PARAGRAPH)
        self.assertTrue(el.find_all(True))  # nested tags present -- pre-feature, an automatic skip

    def test_now_eligible_for_mixed_content_rewrite(self):
        el = _el(self.CROL_ABOUT_PARAGRAPH)
        passage = serialize_mixed_content(el)
        self.assertIsNotNone(passage)
        self.assertEqual(set(passage.nodes), {"LINK1", "LINK2", "EM1"})
        self.assertLess(passage.inline_ratio, 0.5)  # not inline_dominant

    def test_fix_html_end_to_end_rewrites_prose_keeps_links(self):
        client = FakeLLMClient(lambda system, user: self.GOOD_REWRITE)
        new_html, results, skipped = fix_html(
            self.CROL_ABOUT_PARAGRAPH, target_grade=7, language="en", client=client
        )

        self.assertEqual(skipped, 0)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].applied)
        self.assertLessEqual(results[0].after_grade, 7)
        self.assertGreater(results[0].before_grade, 7)

        # Both original <a> tags survive, attributes and anchor text untouched.
        self.assertIn(
            '<a href="https://a856-cityrecord.nyc.gov/" rel="noopener" target="_blank">The City Record</a>',
            new_html,
        )
        self.assertIn(
            '<a href="https://codelibrary.amlegal.com/codes/newyorkcity/latest/NYCcharter/0-0-0-3113" '
            'rel="noopener" target="_blank">every agency must publish</a>',
            new_html,
        )
        self.assertIn("<em>by interest</em>", new_html)
        self.assertNotIn("[LINK", new_html)
        self.assertNotIn("[EM", new_html)
        self.assertNotIn("Notwithstanding", new_html)  # old prose gone (sanity: not the wrong fixture)


if __name__ == "__main__":
    unittest.main()
