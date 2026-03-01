"""
File GitHub issues.

    from com.issue import create
    create("Bug: upload fails", body="Traceback...", labels=["bug", "crash"])

Uses GITHUB_ISSUES_TOKEN and GITHUB_REPO from settings.
Falls back to console output when the token is not set.
"""

import requests
from django.conf import settings


def create(title: str, body: str = "", labels: list[str] | None = None) -> dict | None:
    token = settings.GITHUB_ISSUES_TOKEN
    repo = settings.GITHUB_REPO

    if not token:
        print(f"[issue] (no token) {title}\n  Labels: {labels or []}\n  {body[:200]}")
        return None

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": title,
            "body": body,
            "labels": labels or [],
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
