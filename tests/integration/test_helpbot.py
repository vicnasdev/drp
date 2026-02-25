"""
tests/integration/test_helpbot.py

Integration tests for the /help/ask/ LLM-powered help bot.
These hit the real LLM API to verify the bot gives useful,
non-deflecting answers about drp features.
"""

import pytest
from tests.integration.conftest import HOST, api_post


ASK_URL = f"{HOST}/help/ask/"

# Phrases that signal the bot is deflecting instead of answering.
_DEFLECT_PHRASES = [
    "the documentation does not",
    "i cannot answer",
    "i don't have information",
    "not covered in the documentation",
    "no information available",
    "outside the scope",
]


def _ask(session, question):
    """Post a question and return (status_code, answer_html)."""
    resp = api_post(session, ASK_URL, json_body={"question": question})
    data = resp.json()
    return resp.status_code, data.get("answer", data.get("error", ""))


def _assert_useful(answer, *expected_fragments):
    """Assert the answer is not a deflection and contains expected text."""
    lower = answer.lower()
    for phrase in _DEFLECT_PHRASES:
        assert phrase not in lower, (
            f"Bot deflected with '{phrase}' — answer: {answer[:200]}"
        )
    for frag in expected_fragments:
        alternatives = [a.strip().lower() for a in frag.split("|")]
        assert any(a in lower for a in alternatives), (
            f"Expected one of {alternatives} in answer — got: {answer[:200]}"
        )


class TestHelpBotAnswers:
    """Verify the bot can answer common questions about drp features."""

    def test_how_to_embed(self, free_user):
        status, answer = _ask(free_user.session, "How do I embed a drop in markdown?")
        assert status == 200
        _assert_useful(answer, "embed|markdown|![")

    def test_how_to_upload(self, free_user):
        status, answer = _ask(free_user.session, "How do I upload text?")
        assert status == 200
        _assert_useful(answer, "drp up")

    def test_burn_after_reading(self, free_user):
        status, answer = _ask(free_user.session, "How do I share a secret that deletes itself?")
        assert status == 200
        _assert_useful(answer, "burn")

    def test_plans_question(self, free_user):
        status, answer = _ask(free_user.session, "What plans are available?")
        assert status == 200
        _assert_useful(answer, "free")

    def test_comparison_is_biased(self, free_user):
        status, answer = _ask(free_user.session, "Is pastebin better than drp?")
        assert status == 200
        _assert_useful(answer, "drp")

    def test_anon_blocked(self, anon):
        status, _ = _ask(anon, "hello")
        assert status == 403
