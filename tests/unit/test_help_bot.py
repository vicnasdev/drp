"""Tests for the /help/ask/ Gemini-powered help bot endpoint."""

import json
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings


URL = "/help/ask/"

_GEMINI_OK = {
    "candidates": [{"content": {"parts": [{"text": "Use `drp up` to upload."}]}}]
}


@override_settings(GEMINI_API_KEY="test-key")
class HelpBotTests(TestCase):
    """Validation, config, and happy-path tests (DummyCache is fine here)."""

    # ── method / validation ───────────────────────────────────────────────

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_empty_question(self):
        resp = self.client.post(
            URL, json.dumps({"question": ""}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_question_too_long(self):
        resp = self.client.post(
            URL, json.dumps({"question": "x" * 301}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_json(self):
        resp = self.client.post(URL, "not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    # ── missing config ────────────────────────────────────────────────────

    @override_settings(GEMINI_API_KEY="")
    def test_no_api_key_returns_503(self):
        resp = self.client.post(
            URL, json.dumps({"question": "hi"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 503)

    # ── success ───────────────────────────────────────────────────────────

    @patch("help.views.requests.post")
    def test_successful_answer(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _GEMINI_OK
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        resp = self.client.post(
            URL,
            json.dumps({"question": "how do I upload?"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("answer", data)
        self.assertIn("drp up", data["answer"])

    # ── Gemini error ──────────────────────────────────────────────────────

    @patch("help.views.requests.post")
    def test_gemini_network_error(self, mock_post):
        from requests.exceptions import ConnectionError as ReqConnError

        mock_post.side_effect = ReqConnError("fail")

        resp = self.client.post(
            URL, json.dumps({"question": "test"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 502)

    @patch("help.views.requests.post")
    def test_gemini_empty_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"candidates": []}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        resp = self.client.post(
            URL, json.dumps({"question": "test"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("answer", resp.json())


# ── Rate-limit tests need a real cache backend ───────────────────────────────

_LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "helpbot-test",
    }
}


@override_settings(GEMINI_API_KEY="test-key", CACHES=_LOCMEM)
class HelpBotRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("help.views.requests.post")
    def test_rate_limit_after_10(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _GEMINI_OK
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        for i in range(10):
            r = self.client.post(
                URL,
                json.dumps({"question": f"q{i}"}),
                content_type="application/json",
            )
            self.assertEqual(r.status_code, 200, f"request {i} failed")

        resp = self.client.post(
            URL, json.dumps({"question": "one more"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 429)
