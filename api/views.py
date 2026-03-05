import json
import logging
from datetime import timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.db.models import F
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from api.models import CrashReport
from core.models import create_guest_user, create_token

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_DAYS = 30


def _parse_duration(value: str | None) -> timedelta:
    """Parse a duration string like '7d', '2h', '30m'. Falls back to default."""
    units = {"d": "days", "h": "hours", "m": "minutes"}
    if value and value[-1] in units and value[:-1].isdigit():
        return timedelta(**{units[value[-1]]: int(value[:-1])})
    return timedelta(days=_DEFAULT_TOKEN_DAYS)


# ── Auth ──────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def guest_login(request):
    """POST /api/v1/auth/guest/ — create a guest user and return a token."""
    token = create_guest_user()
    return JsonResponse({"token": token})


@csrf_exempt
@require_POST
def login_view(request):
    """POST /api/v1/auth/login/ — authenticate and return a token."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    identifier = body.get("username", "").strip()
    password = body.get("password", "")

    if not identifier or not password:
        return JsonResponse({"error": "username and password required"}, status=400)

    user = authenticate(username=identifier, password=password)
    if user is None:
        try:
            u = User.objects.get(email=identifier)
            user = authenticate(username=u.username, password=password)
        except User.DoesNotExist:
            pass

    if user is None:
        return JsonResponse({"error": "invalid credentials"}, status=401)

    token = create_token(user, _parse_duration(body.get("duration")))
    return JsonResponse({"token": token.key})


# ── Ping ──────────────────────────────────────────────────────────────────────

@require_GET
def ping(request):
    return JsonResponse({"status": "ok"})


# ── Crash reporting ───────────────────────────────────────────────────────────

_REQUIRED_CRASH_FIELDS = ("fingerprint", "exc_type")
_MAX_TRACEBACK_LEN = 8_000


def _maybe_file_issue(report: CrashReport) -> str | None:
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

    updated = CrashReport.objects.filter(fingerprint=fp).update(hit_count=F("hit_count") + 1)
    if updated:
        return JsonResponse({"status": "known", "fingerprint": fp})

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
        CrashReport.objects.filter(fingerprint=fp).update(hit_count=F("hit_count") + 1)
        return JsonResponse({"status": "known", "fingerprint": fp})

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