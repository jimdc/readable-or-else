"""Test doubles — no live LLM calls anywhere in the test suite."""


class FakeLLMClient:
    """Duck-types LLMClient.complete without any network access."""

    def __init__(self, response_fn):
        self.response_fn = response_fn
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.response_fn(system, user)


def simplifying_response(_system, user):
    """A canned 'good' rewrite: short sentences, keeps numbers/URLs/entities."""
    return user  # overridden per-test via functools.partial-style wrapping


class ErroringLLMClient:
    def __init__(self, exc):
        self.exc = exc

    def complete(self, system, user):
        raise self.exc
