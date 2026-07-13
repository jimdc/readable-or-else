import os
import sys
import unittest

from readable_or_else.llm import (
    BUDGET_EXCEEDED_PREFIX,
    BudgetedClient,
    CallBudgetExceeded,
    CommandLLMClient,
    CommandLLMConfig,
    RewriteUnavailable,
    client_from_env,
)
from tests.fakes import FakeLLMClient

ECHO_UPPER = f"{sys.executable} -c \"import sys; sys.stdout.write(sys.stdin.read().strip().upper())\""
SLEEP_FOREVER = f"{sys.executable} -c \"import time; time.sleep(5)\""
EXIT_NONZERO = f"{sys.executable} -c \"import sys; sys.stderr.write('boom'); sys.exit(3)\""
NOT_A_COMMAND = "definitely-not-a-real-binary-xyz"


class TestCommandLLMConfig(unittest.TestCase):
    def setUp(self):
        self._backup = {
            k: os.environ.pop(k, None)
            for k in ("READABLE_OR_ELSE_LLM_CMD", "READABLE_OR_ELSE_LLM_TIMEOUT")
        }

    def tearDown(self):
        for k, v in self._backup.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_missing_cmd_raises(self):
        with self.assertRaises(RewriteUnavailable):
            CommandLLMConfig.from_env()

    def test_present_cmd_builds_with_default_timeout(self):
        os.environ["READABLE_OR_ELSE_LLM_CMD"] = "claude -p --model sonnet"
        config = CommandLLMConfig.from_env()
        self.assertEqual(config.command, "claude -p --model sonnet")
        self.assertEqual(config.timeout, 60.0)

    def test_custom_timeout_from_env(self):
        os.environ["READABLE_OR_ELSE_LLM_CMD"] = "ollama run llama3.1"
        os.environ["READABLE_OR_ELSE_LLM_TIMEOUT"] = "5"
        config = CommandLLMConfig.from_env()
        self.assertEqual(config.timeout, 5.0)


class TestCommandLLMClient(unittest.TestCase):
    def test_happy_path_prompt_via_stdin(self):
        client = CommandLLMClient(CommandLLMConfig(command=ECHO_UPPER))
        result = client.complete("system prompt", "some passage")
        self.assertEqual(result, "SYSTEM PROMPT\n\nSOME PASSAGE")

    def test_passage_text_never_shell_interpolated(self):
        # A passage carrying shell metacharacters must reach the subprocess as
        # inert stdin text, never get executed as part of the command line.
        client = CommandLLMClient(CommandLLMConfig(command=ECHO_UPPER))
        dangerous = "; rm -rf / #"
        result = client.complete("sys", dangerous)
        self.assertIn(dangerous.upper(), result)

    def test_timeout_raises_backend_error(self):
        client = CommandLLMClient(CommandLLMConfig(command=SLEEP_FOREVER, timeout=0.2))
        with self.assertRaises(RewriteUnavailable) as ctx:
            client.complete("sys", "user")
        self.assertIn("backend_error", str(ctx.exception))
        self.assertIn("timed out", str(ctx.exception))

    def test_nonzero_exit_raises_backend_error(self):
        client = CommandLLMClient(CommandLLMConfig(command=EXIT_NONZERO))
        with self.assertRaises(RewriteUnavailable) as ctx:
            client.complete("sys", "user")
        self.assertIn("backend_error", str(ctx.exception))
        self.assertIn("exited 3", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_missing_binary_raises_backend_error(self):
        client = CommandLLMClient(CommandLLMConfig(command=NOT_A_COMMAND))
        with self.assertRaises(RewriteUnavailable) as ctx:
            client.complete("sys", "user")
        self.assertIn("backend_error", str(ctx.exception))


class TestClientFromEnv(unittest.TestCase):
    ENV_KEYS = (
        "READABLE_OR_ELSE_LLM_BACKEND",
        "READABLE_OR_ELSE_LLM_BASE",
        "READABLE_OR_ELSE_LLM_MODEL",
        "READABLE_OR_ELSE_LLM_KEY",
        "READABLE_OR_ELSE_LLM_CMD",
        "READABLE_OR_ELSE_LLM_TIMEOUT",
        "READABLE_OR_ELSE_MAX_CALLS",
    )

    def setUp(self):
        self._backup = {k: os.environ.pop(k, None) for k in self.ENV_KEYS}

    def tearDown(self):
        for k, v in self._backup.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_default_backend_is_http(self):
        os.environ["READABLE_OR_ELSE_LLM_BASE"] = "https://api.example.com/v1"
        os.environ["READABLE_OR_ELSE_LLM_MODEL"] = "gpt-4o-mini"
        client = client_from_env()
        self.assertIsInstance(client, BudgetedClient)
        self.assertEqual(type(client.client).__name__, "LLMClient")

    def test_command_backend_selected_explicitly(self):
        os.environ["READABLE_OR_ELSE_LLM_BACKEND"] = "command"
        os.environ["READABLE_OR_ELSE_LLM_CMD"] = ECHO_UPPER
        client = client_from_env()
        self.assertIsInstance(client, BudgetedClient)
        self.assertIsInstance(client.client, CommandLLMClient)

    def test_unknown_backend_raises(self):
        os.environ["READABLE_OR_ELSE_LLM_BACKEND"] = "carrier-pigeon"
        with self.assertRaises(RewriteUnavailable):
            client_from_env()

    def test_max_calls_defaults_to_50(self):
        os.environ["READABLE_OR_ELSE_LLM_BACKEND"] = "command"
        os.environ["READABLE_OR_ELSE_LLM_CMD"] = ECHO_UPPER
        client = client_from_env()
        self.assertEqual(client.max_calls, 50)

    def test_max_calls_overridden_from_env(self):
        os.environ["READABLE_OR_ELSE_LLM_BACKEND"] = "command"
        os.environ["READABLE_OR_ELSE_LLM_CMD"] = ECHO_UPPER
        os.environ["READABLE_OR_ELSE_MAX_CALLS"] = "3"
        client = client_from_env()
        self.assertEqual(client.max_calls, 3)


class TestBudgetedClient(unittest.TestCase):
    def test_calls_under_budget_pass_through(self):
        inner = FakeLLMClient(lambda system, user: "ok")
        budgeted = BudgetedClient(inner, max_calls=2)
        self.assertEqual(budgeted.complete("s", "u"), "ok")
        self.assertEqual(budgeted.complete("s", "u"), "ok")
        self.assertEqual(inner.calls, [("s", "u"), ("s", "u")])

    def test_exceeding_budget_raises_without_calling_inner(self):
        inner = FakeLLMClient(lambda system, user: "ok")
        budgeted = BudgetedClient(inner, max_calls=1)
        budgeted.complete("s", "u")
        with self.assertRaises(CallBudgetExceeded) as ctx:
            budgeted.complete("s", "u")
        self.assertIn(BUDGET_EXCEEDED_PREFIX, str(ctx.exception))
        # The ceiling short-circuits before delegating — no second real call made.
        self.assertEqual(len(inner.calls), 1)

    def test_call_budget_exceeded_is_a_rewrite_unavailable(self):
        # fix.py/llm.py only ever catch RewriteUnavailable — the budget guard
        # must degrade through that same path, not a new exception type callers
        # need to know about.
        self.assertTrue(issubclass(CallBudgetExceeded, RewriteUnavailable))


if __name__ == "__main__":
    unittest.main()
