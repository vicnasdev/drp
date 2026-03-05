import json
import logging

import requests as http_requests
from django.conf import settings
from django.db import IntegrityError
from django.db.models import F
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from api.models import CrashReport
from bot.models import Exchange

logger = logging.getLogger(__name__)


@require_GET
def ping(request):
    return JsonResponse({"status": "ok"})


# ── Crash reporting ───────────────────────────────────────────────────────────

_REQUIRED_CRASH_FIELDS = ("fingerprint", "exc_type")
_MAX_TRACEBACK_LEN = 8_000  # protect against oversized payloads


def _maybe_file_issue(report: CrashReport) -> str | None:
    """Create a GitHub issue for a *new* crash. Returns the issue URL or None."""
    from com.issue import create

    title = f"[crash] {report.exc_type}: {report.exc_message[:80]}"
    body_parts = [
        f"**Command:** `{report.command}`",
        f"**CLI version:** {report.cli_version}",
        f"**Python:** {report.python_version}",
        f"**Platform:** {report.platform}",
        f"**Fingerprint:** `{report.fingerprint}`",
        "",
        "```",
        report.traceback[:_MAX_TRACEBACK_LEN],
        "```",
    ]
    labels = ["bug", "cli", "auto-reported"]
    if report.command:
        labels.append(f"cmd:{report.command}")

    result = create(title, body="\n".join(body_parts), labels=labels)
    if result and "html_url" in result:
        return result["html_url"]
    return None


@csrf_exempt
@require_POST
def crash_report(request):
    """
    POST /api/v1/crash/

    Accepts a JSON crash payload from the CLI.  No auth required — anyone
    can report a crash.  Deduplicates on ``fingerprint``: first occurrence
    files a GitHub issue; subsequent hits bump ``hit_count``.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    if not all(body.get(f) for f in _REQUIRED_CRASH_FIELDS):
        return JsonResponse(
            {"error": f"required fields: {', '.join(_REQUIRED_CRASH_FIELDS)}"},
            status=400,
        )

    fp = body["fingerprint"]

    # ── Dedup: existing fingerprint → increment and return ────────
    updated = CrashReport.objects.filter(fingerprint=fp).update(
        hit_count=F("hit_count") + 1,
    )
    if updated:
        return JsonResponse({"status": "known", "fingerprint": fp})

    # ── New crash ─────────────────────────────────────────────────
    try:
        report = CrashReport.objects.create(
            fingerprint=fp,
            exc_type=body.get("exc_type", ""),
            exc_message=body.get("exc_message", "")[:500],
            traceback=body.get("traceback", "")[:_MAX_TRACEBACK_LEN],
            command=body.get("command", "")[:64],
            cli_version=body.get("cli_version", "")[:32],
            python_version=body.get("python_version", "")[:32],
            platform=body.get("platform", "")[:128],
        )
    except IntegrityError:
        # Race condition: another worker inserted between our SELECT and
        # INSERT.  Just bump the count.
        CrashReport.objects.filter(fingerprint=fp).update(
            hit_count=F("hit_count") + 1,
        )
        return JsonResponse({"status": "known", "fingerprint": fp})

    # File GitHub issue (best-effort).
    try:
        issue_url = _maybe_file_issue(report)
        if issue_url:
            report.issue_url = issue_url
            report.save(update_fields=["issue_url"])
    except Exception:
        logger.exception("Failed to file GitHub issue for %s", fp[:8])

    return JsonResponse(
        {"status": "created", "fingerprint": fp, "issue_url": report.issue_url},
        status=201,
    )
