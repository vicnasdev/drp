"""
manage.py promote_feature
~~~~~~~~~~~~~~~~~~~~~~~~~~
Pick the top-voted open feature proposal, create a GitHub issue tagged
``community-pick``, then delete the proposal from the DB.

Run periodically (e.g. weekly cron on Railway) or on-demand:

    python manage.py promote_feature          # promote #1
    python manage.py promote_feature --top 3  # promote top 3
    python manage.py promote_feature --dry-run
"""
import logging
import os

import requests as http
from django.core.management.base import BaseCommand
from django.db.models import Sum, Value, IntegerField
from django.db.models.functions import Coalesce

from core.models import FeatureProposal

log = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_ISSUES_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "vicnasdev/drp")
GITHUB_API   = "https://api.github.com"
LABEL        = "community-pick"


def _ensure_label():
    """Create the 'community-pick' label if it doesn't exist yet."""
    if not GITHUB_TOKEN:
        return
    try:
        http.post(
            f"{GITHUB_API}/repos/{GITHUB_REPO}/labels",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={"name": LABEL, "color": "7057ff", "description": "Voted by the community"},
            timeout=8,
        )
    except Exception:
        pass  # 422 = already exists, fine


def _create_issue(proposal, score):
    """Create a GitHub issue for the winning proposal. Returns issue URL or None."""
    if not GITHUB_TOKEN:
        log.warning("GITHUB_ISSUES_TOKEN not set — skipping")
        return None

    proposer = proposal.proposed_by.username if proposal.proposed_by else "anonymous"
    body = (
        f"## {proposal.title}\n\n"
        f"{proposal.description}\n\n"
        f"---\n"
        f"**Proposed by:** {proposer}  \n"
        f"**Community score:** {score}  \n"
        f"*Auto-promoted from the feature voting board.*\n"
    )

    try:
        res = http.post(
            f"{GITHUB_API}/repos/{GITHUB_REPO}/issues",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "title": f"[feature] {proposal.title}",
                "body": body,
                "labels": [LABEL],
            },
            timeout=10,
        )
        if res.status_code == 201:
            url = res.json().get("html_url", "")
            log.info("Created issue: %s", url)
            return url
        log.error("GitHub API %s: %s", res.status_code, res.text[:300])
    except Exception as exc:
        log.error("GitHub request failed: %s", exc)
    return None


def promote_top(n=1, dry_run=False):
    """
    Promote the top *n* voted proposals to GitHub issues.
    Returns list of (proposal_title, issue_url) tuples.
    """
    proposals = (
        FeatureProposal.objects
        .filter(closed=False)
        .annotate(score=Coalesce(
            Sum("votes__weight"), Value(0), output_field=IntegerField(),
        ))
        .order_by("-score", "-created_at")[:n]
    )

    if not proposals:
        log.info("No open proposals to promote.")
        return []

    if not dry_run:
        _ensure_label()

    results = []
    for proposal in proposals:
        score = proposal.score
        if dry_run:
            log.info("[dry-run] Would promote: '%s' (score %d)", proposal.title, score)
            results.append((proposal.title, None))
            continue

        url = _create_issue(proposal, score)
        if url:
            proposal.delete()
            results.append((proposal.title, url))
        else:
            log.warning("Skipped '%s' — issue creation failed", proposal.title)

    return results


class Command(BaseCommand):
    help = "Promote the top-voted feature proposal(s) to GitHub issues."

    def add_arguments(self, parser):
        parser.add_argument(
            "--top", type=int, default=1,
            help="Number of top proposals to promote (default: 1)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print what would happen without creating issues or deleting proposals.",
        )

    def handle(self, *args, **options):
        results = promote_top(n=options["top"], dry_run=options["dry_run"])
        if not results:
            self.stdout.write("No proposals to promote.")
            return
        for title, url in results:
            if url:
                self.stdout.write(self.style.SUCCESS(f"✓ '{title}' → {url}"))
            else:
                self.stdout.write(f"  '{title}' (dry-run)" if options["dry_run"]
                                  else self.style.WARNING(f"✗ '{title}' — failed"))
