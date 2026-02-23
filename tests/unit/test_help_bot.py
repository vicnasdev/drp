"""Tests for the /help/ask/ Gemini-powered help bot endpoint."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings

URL = "/help/ask/"

_GEMINI_OK = {
    "candidates": [{"content": {"parts": [{"text": "Use `drp up` to upload."}]}}]
}

_LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "helpbot-test",
    }
}


def _post(client, q="test"):
    return client.post(URL, json.dumps({"question": q}), content_type="application/json")


@override_settings(GEMINI_API_KEY="test-key")
class HelpBotTests(TestCase):
    """Validation, auth, config, and happy-path tests (DummyCache is fine)."""

    def setUp(self):
        self.user = User.objects.create_user("botuser", password="pw")
        self.client.login(username="botuser", password="pw")

    # ── method / validation ───────────────────────────────────────────────

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_empty_question(self):
        self.assertEqual(_post(self.client, "").status_code, 400)

    def test_question_too_long(self):
        self.assertEqual(_post(self.client, "x" * 301).status_code, 400)

    def test_invalid_json(self):
        resp = self.client.post(URL, "not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    # ── auth / plan gating ────────────────────────────────────────────────

    def test_anonymous_denied(self):
        self.client.logout()
        self.assertEqual(_post(self.client).status_code, 403)

    @override_settings(GEMINI_API_KEY="")
    def test_no_api_key_returns_503(self):
        self.assertEqual(_post(self.client).status_code, 503)

    # ── success ───────────────────────────────────────────────────────────

    @patch("help.views.requests.post")
    def test_successful_answer(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _GEMINI_OK
        mock_post.return_value = mock_resp

        resp = _post(self.client, "how do I upload?")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("answer", data)
        self.assertIn("drp up", data["answer"])

    # ── Gemini error ──────────────────────────────────────────────────────

    @patch("help.views._report_gemini_error")
    @patch("help.views.requests.post")
    def test_gemini_network_error(self, mock_post, _mock_report):
        from requests.exceptions import ConnectionError as ReqConnError
        mock_post.side_effect = ReqConnError("fail")
        self.assertEqual(_post(self.client).status_code, 502)

    @patch("help.views._report_gemini_error")
    @patch("help.views.requests.post")
    def test_gemini_http_error_reports_issue(self, mock_post, mock_report):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "API key not valid"
        mock_post.return_value = mock_resp

        resp = _post(self.client)
        self.assertEqual(resp.status_code, 502)
        mock_report.assert_called_once()
        self.assertIn("GeminiHTTP403", mock_report.call_args[0][0])

    @patch("help.views.requests.post")
    def test_gemini_empty_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"candidates": []}
        mock_post.return_value = mock_resp

        resp = _post(self.client)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("answer", resp.json())


# ── Rate-limit tests need a real cache backend ───────────────────────────────


@override_settings(GEMINI_API_KEY="test-key", CACHES=_LOCMEM)
class HelpBotRateLimitTests(TestCase):
    """Free plan gets 5 questions/hr; verify the limit is enforced."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("rluser", password="pw")
        self.client.login(username="rluser", password="pw")

    @patch("help.views.requests.post")
    def test_free_plan_limit(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _GEMINI_OK
        mock_post.return_value = mock_resp

        for i in range(5):
            r = _post(self.client, f"q{i}")
            self.assertEqual(r.status_code, 200, f"request {i} failed")

        self.assertEqual(_post(self.client, "one more").status_code, 429)

    @patch("help.views.requests.post")
    def test_starter_gets_25(self, mock_post):
        self.user.profile.plan = "starter"
        self.user.profile.save()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _GEMINI_OK
        mock_post.return_value = mock_resp

        # Should be able to make 25 requests
        for i in range(25):
            r = _post(self.client, f"q{i}")
            self.assertEqual(r.status_code, 200, f"request {i} failed")

        self.assertEqual(_post(self.client, "one more").status_code, 429)


# ── CLI cmd_ask tests ─────────────────────────────────────────────────────────

class TestCmdAsk:
    """Pure unit tests for cli/commands/ask.py — no Django, mock all network."""

    def _make_args(self, question=None):
        from argparse import Namespace
        return Namespace(question=question)

    @patch("cli.commands.ask.load_context")
    def test_success(self, mock_ctx, capsys):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"answer": "<p>Use <code>drp up</code>.</p>"}
        session.post.return_value = resp
        mock_ctx.return_value = ({}, "https://drp.fyi", session)

        from cli.commands.ask import cmd_ask
        cmd_ask(self._make_args("how to upload?"))

        out = capsys.readouterr().out
        assert "drp up" in out

    @patch("cli.commands.ask.load_context")
    def test_rate_limit(self, mock_ctx, capsys):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 429
        session.post.return_value = resp
        mock_ctx.return_value = ({}, "https://drp.fyi", session)

        from cli.commands.ask import cmd_ask
        with pytest.raises(SystemExit):
            cmd_ask(self._make_args("test"))

        assert "limit" in capsys.readouterr().out.lower()

    @patch("cli.commands.ask.load_context")
    def test_403_denied(self, mock_ctx, capsys):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 403
        resp.headers = {"content-type": "application/json"}
        resp.json.return_value = {"error": "Log in to use the help bot."}
        session.post.return_value = resp
        mock_ctx.return_value = ({}, "https://drp.fyi", session)

        from cli.commands.ask import cmd_ask
        with pytest.raises(SystemExit):
            cmd_ask(self._make_args("test"))

        assert "log in" in capsys.readouterr().out.lower()
