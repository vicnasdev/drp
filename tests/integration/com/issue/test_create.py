"""
Integration test for com.issue.

Creates a real GitHub issue, verifies it was filed, then closes it.
Requires GITHUB_ISSUES_TOKEN in env.
"""

import pytest
import requests
from django.conf import settings

from com.issue import create


@pytest.mark.skipif(
    not settings.GITHUB_ISSUES_TOKEN,
    reason="GITHUB_ISSUES_TOKEN required",
)
def test_create_and_close_issue():
    result = create(
        "[test] integration test issue — safe to delete",
        body="Automated integration test. This issue will be closed immediately.",
        labels=["test"],
    )

    assert result is not None
    assert result["title"] == "[test] integration test issue — safe to delete"
    assert "test" in [l["name"] for l in result["labels"]]

    # Close the issue so it doesn't litter the repo
    requests.patch(
        result["url"],
        headers={
            "Authorization": f"Bearer {settings.GITHUB_ISSUES_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={"state": "closed"},
        timeout=10,
    ).raise_for_status()
