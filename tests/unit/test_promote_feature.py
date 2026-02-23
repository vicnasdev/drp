"""Tests for promote_feature management command and promote_top()."""
import io
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.core.management import call_command

from core.models import FeatureProposal, FeatureVote


class PromoteFeatureTests(TestCase):

    def setUp(self):
        self.u1 = User.objects.create_user("alice", password="x")
        self.u2 = User.objects.create_user("bob", password="x")

        self.p1 = FeatureProposal.objects.create(
            title="Dark mode", description="Add dark theme", proposed_by=self.u1,
        )
        self.p2 = FeatureProposal.objects.create(
            title="API v2", description="New API version", proposed_by=self.u2,
        )

        # p1 gets 2 votes (weight 1 each), p2 gets 1 vote
        FeatureVote.objects.create(proposal=self.p1, user=self.u1, weight=1)
        FeatureVote.objects.create(proposal=self.p1, user=self.u2, weight=1)
        FeatureVote.objects.create(proposal=self.p2, user=self.u1, weight=3)

    # ── promote_top ──────────────────────────────────────────────────────

    def test_dry_run_does_not_delete(self):
        from core.management.commands.promote_feature import promote_top
        results = promote_top(n=1, dry_run=True)
        self.assertEqual(len(results), 1)
        # p2 has score 3, should win
        self.assertEqual(results[0][0], "API v2")
        self.assertIsNone(results[0][1])
        # Proposal still exists
        self.assertTrue(FeatureProposal.objects.filter(pk=self.p2.pk).exists())

    @patch("core.management.commands.promote_feature._create_issue")
    @patch("core.management.commands.promote_feature._ensure_label")
    def test_promote_creates_issue_and_deletes(self, mock_label, mock_create):
        mock_create.return_value = "https://github.com/vicnasdev/drp/issues/42"
        from core.management.commands.promote_feature import promote_top
        results = promote_top(n=1, dry_run=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "API v2")
        self.assertIn("issues/42", results[0][1])
        # Proposal deleted
        self.assertFalse(FeatureProposal.objects.filter(pk=self.p2.pk).exists())
        # Other proposal untouched
        self.assertTrue(FeatureProposal.objects.filter(pk=self.p1.pk).exists())
        mock_label.assert_called_once()

    @patch("core.management.commands.promote_feature._create_issue")
    @patch("core.management.commands.promote_feature._ensure_label")
    def test_promote_top_multiple(self, mock_label, mock_create):
        mock_create.return_value = "https://github.com/vicnasdev/drp/issues/99"
        from core.management.commands.promote_feature import promote_top
        results = promote_top(n=2, dry_run=False)
        self.assertEqual(len(results), 2)
        self.assertEqual(FeatureProposal.objects.count(), 0)

    @patch("core.management.commands.promote_feature._create_issue")
    @patch("core.management.commands.promote_feature._ensure_label")
    def test_promote_skips_on_failure(self, mock_label, mock_create):
        mock_create.return_value = None  # GitHub API failed
        from core.management.commands.promote_feature import promote_top
        results = promote_top(n=1, dry_run=False)
        self.assertEqual(len(results), 0)
        # Proposal NOT deleted
        self.assertTrue(FeatureProposal.objects.filter(pk=self.p2.pk).exists())

    def test_promote_no_proposals(self):
        FeatureProposal.objects.all().delete()
        from core.management.commands.promote_feature import promote_top
        results = promote_top(n=1, dry_run=False)
        self.assertEqual(results, [])

    def test_closed_proposals_skipped(self):
        self.p2.closed = True
        self.p2.save()
        from core.management.commands.promote_feature import promote_top
        results = promote_top(n=1, dry_run=True)
        # p1 (score 2) should be picked since p2 is closed
        self.assertEqual(results[0][0], "Dark mode")

    # ── management command ────────────────────────────────────────────

    @patch("core.management.commands.promote_feature._create_issue")
    @patch("core.management.commands.promote_feature._ensure_label")
    def test_command_runs(self, mock_label, mock_create):
        mock_create.return_value = "https://github.com/vicnasdev/drp/issues/1"
        out = io.StringIO()
        call_command("promote_feature", "--top", "1", stdout=out)
        self.assertIn("API v2", out.getvalue())

    def test_command_dry_run(self):
        out = io.StringIO()
        call_command("promote_feature", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("API v2", output)
        # Nothing deleted
        self.assertEqual(FeatureProposal.objects.count(), 2)

    # ── _create_issue HTTP ────────────────────────────────────────────

    @patch("core.management.commands.promote_feature.http.post")
    @patch("core.management.commands.promote_feature.GITHUB_TOKEN", "fake-token")
    def test_create_issue_http(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"html_url": "https://github.com/x/y/issues/5"}
        mock_post.return_value = mock_resp

        from core.management.commands.promote_feature import _create_issue
        url = _create_issue(self.p1, 2)
        self.assertEqual(url, "https://github.com/x/y/issues/5")

        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        self.assertEqual(payload["labels"], ["community-pick"])
        self.assertIn("[feature]", payload["title"])

    @patch("core.management.commands.promote_feature.GITHUB_TOKEN", "")
    def test_create_issue_no_token(self):
        from core.management.commands.promote_feature import _create_issue
        url = _create_issue(self.p1, 2)
        self.assertIsNone(url)
