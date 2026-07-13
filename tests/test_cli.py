import contextlib
import io
import json
import os
import tempfile
import unittest

from readable_or_else.cli import main


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


if __name__ == "__main__":
    unittest.main()
