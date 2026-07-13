import unittest

from reading_gate.extract import extract_visible_text, extract_dom_rendered, DomRenderedNotImplemented


class TestExtractVisibleText(unittest.TestCase):
    def test_strips_script_and_style(self):
        html = """
        <html><head><style>.x{color:red}</style></head>
        <body>
          <script>alert('hi')</script>
          <p>Hello there, this is visible.</p>
          <template><p>Not visible.</p></template>
        </body></html>
        """
        text = extract_visible_text(html)
        self.assertIn("Hello there, this is visible.", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("Not visible.", text)

    def test_whitespace_normalized(self):
        html = "<p>Line one.</p>\n\n<p>   Line   two.  </p>"
        text = extract_visible_text(html)
        self.assertEqual(text, "Line one. Line two.")

    def test_empty_html(self):
        self.assertEqual(extract_visible_text(""), "")


class TestExtractDomRendered(unittest.TestCase):
    def test_raises_not_implemented(self):
        with self.assertRaises(DomRenderedNotImplemented):
            extract_dom_rendered("some/path.html")


if __name__ == "__main__":
    unittest.main()
