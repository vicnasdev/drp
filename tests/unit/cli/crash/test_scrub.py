"""Unit tests for cli.crash.scrub — data scrubbing."""

import os

from cli.crash.scrub import scrub


class TestScrub:
    """User-identifying data is removed before the payload leaves the machine."""

    def test_home_directory_replaced(self):
        home = os.path.expanduser("~")
        text = f'File "{home}/projects/drp/cli/shell.py", line 42'
        assert home not in scrub(text)
        assert "~" in scrub(text)

    def test_email_replaced(self):
        text = "User vic@example.com triggered the crash"
        result = scrub(text)
        assert "vic@example.com" not in result
        assert "<email>" in result

    def test_bearer_token_replaced(self):
        text = "Authorization: Bearer sk-abc123longtoken"
        result = scrub(text)
        assert "sk-abc123longtoken" not in result
        assert "<token>" in result

    def test_hex_token_replaced(self):
        token = "a" * 40
        text = f"hash: {token}"
        result = scrub(text)
        assert token not in result
        assert "<token>" in result

    def test_secret_env_replaced(self):
        text = "GITHUB_ISSUES_TOKEN=ghp_secret123abc"
        result = scrub(text)
        assert "ghp_secret123abc" not in result
        assert "***" in result

    def test_clean_text_unchanged(self):
        text = "ValueError: invalid literal for int()"
        assert scrub(text) == text

    def test_multiple_scrubs_combined(self):
        home = os.path.expanduser("~")
        text = (
            f'File "{home}/cli/main.py", line 10\n'
            "sent to user@test.com with Bearer ghp_token"
        )
        result = scrub(text)
        assert home not in result
        assert "user@test.com" not in result
        assert "ghp_token" not in result
