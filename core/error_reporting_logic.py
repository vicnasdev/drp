"""
core/error_reporting_logic.py

Deduplicates errors and optionally files GitHub issues.
Called from help/views.py (LLM errors) and can be used anywhere.
"""

import hashlib
import json
import logging
import urllib.request
import urllib.error

from django.conf import settings

log = logging.getLogger(__name__)


def maybe_file_issue(data: dict) -> None:
    """
    Deduplicate by fingerprint and optionally open a GitHub issue.
    Safe to call from a background thread — never raises.

    data keys: exc_type, exc_message, traceback (list), command,
               cli_version, python_version, platform
    """
    try:
        from core.models import CrashReport

        exc_type    = data.get("exc_type", "UnknownError")
        exc_message = str(data.get("exc_message", ""))[:500]
        tb_lines    = data.get("traceback", [])
        tb_str      = "".join(tb_lines)[-2000:]

        # Fingerprint: hash of exc_type + scrubbed traceback
        raw         = f"{exc_type}:{tb_str or exc_message}"
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        title       = f"[{exc_type}] {exc_message[:120]}"

        report, created = CrashReport.objects.get_or_create(
            fingerprint=fingerprint,
            defaults={
                "exc_type": exc_type,
                "title":    title,
            },
        )

        if not created:
            CrashReport.objects.filter(pk=report.pk).update(
                hit_count=report.hit_count + 1,
            )
            log.debug("error_reporting: existing issue #%s hit_count+1", report.pk)
            return

        # First occurrence — try to file a GitHub issue
        _post_github_issue(title, exc_type, exc_message, tb_str, data, report)

    except Exception as e:
        log.exception("error_reporting: maybe_file_issue failed: %s", e)


def _post_github_issue(title, exc_type, exc_message, tb_str, data, report):
    token = getattr(settings, "GITHUB_WEBHOOK_SECRET", "")
    repo  = getattr(settings, "GITHUB_REPO", "vicnasdev/drp")

    if not token:
        log.debug("error_reporting: no GITHUB_WEBHOOK_SECRET, skipping issue")
        return

    body = (
        f"## `{exc_type}`\n\n"
        f"**Message:** `{exc_message}`\n\n"
        f"**Command:** `{data.get('command', 'unknown')}`\n"
        f"**CLI version:** `{data.get('cli_version', 'server')}`\n"
        f"**Python:** `{data.get('python_version', '')}`\n"
        f"**Platform:** `{data.get('platform', '')}`\n\n"
        f"```\n{tb_str or '(no traceback)'}\n```\n"
    )

    payload = json.dumps({
        "title":  title,
        "body":   body,
        "labels": ["bug", "auto-reported"],
    }).encode()

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept":        "application/vnd.github+json",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result    = json.loads(resp.read())
            issue_url = result.get("html_url", "")
            if issue_url:
                from core.models import CrashReport
                CrashReport.objects.filter(pk=report.pk).update(github_issue_url=issue_url)
                log.info("error_reporting: filed GitHub issue %s", issue_url)
    except urllib.error.HTTPError as e:
        log.warning("error_reporting: GitHub API %s: %s", e.code, e.read().decode()[:300])
    except Exception as e:
        log.warning("error_reporting: GitHub issue post failed: %s", e)
