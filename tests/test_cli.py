import contextlib
import io
import json
import os
import tempfile
import unittest

from readable_or_else.cli import main
from readable_or_else.llm import BudgetedClient
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


class TestCliCheck(unittest.TestCase):
    def _write(self, tmp, name, content):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_gate_mode_exits_nonzero_on_over_target_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "hard.html",
                "<html><body><script>ignored()</script>"
                "<p>Notwithstanding the aforementioned regulatory considerations, "
                "applicants must remit payment via the designated online portal in "
                "order to obtain provisional authorization from the relevant municipal "
                "authority.</p></body></html>",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["check", path, "--preset", "nycsg7", "--format", "json"])
            self.assertEqual(code, 1)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload[0]["status"], "fail")
            self.assertNotIn("ignored", out.getvalue())

    def test_gate_mode_exits_zero_on_simple_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "easy.html",
                "<html><body><p>The cat sat. It was happy. We saw it run.</p></body></html>",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["check", path, "--preset", "nycsg7", "--format", "json"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload[0]["status"], "pass")

    def test_warn_mode_never_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "hard.html",
                "<p>Notwithstanding the aforementioned regulatory considerations, "
                "applicants must remit payment via the designated online portal in "
                "order to obtain provisional authorization from the relevant municipal "
                "authority.</p>",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["check", path, "--preset", "nycsg7", "--mode", "warn", "--format", "json"])
            self.assertEqual(code, 0)

    def test_table_format_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "easy.html", "<p>The cat sat. It was happy.</p>")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["check", path, "--preset", "nycsg7", "--format", "table"])
            self.assertEqual(code, 0)
            self.assertIn("STATUS", out.getvalue())
            self.assertIn(path, out.getvalue())

    def test_gh_annotations_format_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "hard.html",
                "<p>Notwithstanding the aforementioned regulatory considerations, "
                "applicants must remit payment via the designated online portal in "
                "order to obtain provisional authorization from the relevant municipal "
                "authority.</p>",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["check", path, "--preset", "nycsg7", "--format", "gh-annotations"])
            self.assertEqual(code, 1)
            self.assertIn("::error", out.getvalue())

    def test_custom_preset_requires_max_grade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "easy.html", "<p>The cat sat.</p>")
            with self.assertRaises(SystemExit):
                main(["check", path, "--preset", "custom"])

    def test_ratchet_without_baseline_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "easy.html", "<p>The cat sat.</p>")
            with self.assertRaises(SystemExit):
                main(["check", path, "--preset", "nycsg7", "--mode", "ratchet"])


class TestCliBaseline(unittest.TestCase):
    def test_baseline_command_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "page.html")
            with open(src, "w", encoding="utf-8") as f:
                f.write("<p>Notwithstanding the aforementioned considerations, remit payment.</p>")
            baseline_path = os.path.join(tmp, "baseline.json")

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["baseline", src, "--preset", "nycsg7", "-o", baseline_path])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(baseline_path))

            with open(baseline_path) as f:
                data = json.load(f)
            self.assertIn(src, data["entries"])

    def test_ratchet_check_uses_written_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "page.html")
            with open(src, "w", encoding="utf-8") as f:
                f.write("<p>Notwithstanding the aforementioned considerations, remit payment.</p>")
            baseline_path = os.path.join(tmp, "baseline.json")

            with contextlib.redirect_stdout(io.StringIO()):
                main(["baseline", src, "--preset", "nycsg7", "-o", baseline_path])
                code = main(
                    ["check", src, "--preset", "nycsg7", "--mode", "ratchet", "--baseline", baseline_path]
                )
            self.assertEqual(code, 0)


class TestCliFix(unittest.TestCase):
    def _write(self, tmp, name, content):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_fix_applies_accepted_rewrite_and_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "hard.html", f"<p>{HARD_SENTENCE}</p>")
            client = FakeLLMClient(lambda system, user: GOOD_REWRITE)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["fix", path, "--preset", "nycsg7"], llm_client=client)

            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as f:
                written = f.read()
            self.assertIn(GOOD_REWRITE, written)
            self.assertNotIn(HARD_SENTENCE, written)
            self.assertIn("yes", out.getvalue())

    def test_fix_leaves_file_untouched_on_denial_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "hard.html", f"<p>{HARD_SENTENCE}</p>")
            original = open(path, encoding="utf-8").read()
            client = FakeLLMClient(lambda system, user: HARD_SENTENCE)  # never improves

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["fix", path, "--preset", "nycsg7", "--max-retries", "0"], llm_client=client)

            self.assertEqual(code, 1)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), original)
            self.assertIn("grade_target", out.getvalue())

    def test_fix_json_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "hard.html", f"<p>{HARD_SENTENCE}</p>")
            client = FakeLLMClient(lambda system, user: GOOD_REWRITE)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["fix", path, "--preset", "nycsg7", "--format", "json"], llm_client=client)

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload[0]["changed"])
            self.assertTrue(payload[0]["passages"][0]["applied"])

    def test_fix_on_passing_file_makes_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "easy.html", "<p>The cat sat. It was happy.</p>")
            original = open(path, encoding="utf-8").read()
            client = FakeLLMClient(lambda system, user: "should never be called")

            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["fix", path, "--preset", "nycsg7"], llm_client=client)

            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), original)
            self.assertEqual(len(client.calls), 0)

    def test_fix_reports_call_budget_exceeded_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "hard.html", f"<p>{HARD_SENTENCE}</p>")
            original = open(path, encoding="utf-8").read()
            inner = FakeLLMClient(lambda system, user: GOOD_REWRITE)
            client = BudgetedClient(inner, max_calls=0)

            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["fix", path, "--preset", "nycsg7"], llm_client=client)

            self.assertEqual(code, 1)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), original)
            self.assertEqual(len(inner.calls), 0)
            self.assertIn("budget_exceeded", out.getvalue())
            self.assertIn("call budget exceeded", err.getvalue())


if __name__ == "__main__":
    unittest.main()
