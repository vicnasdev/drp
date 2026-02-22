"""
GitHub webhook handler — fires when an issue is closed.

When GitHub closes an issue that was created from a user BugReport,
we look up the reporter and (if they opted in) send them a nice
"your bug has been fixed!" email from issues@<domain>.

Webhook secret verification is done via the X-Hub-Signature-256 header.
Set GITHUB_WEBHOOK_SECRET in your environment to enable verification.
Requests without a matching signature are rejected with 400.
If no secret is configured (dev / tests), the check is skipped.

GitHub setup:
  Payload URL : https://<your-domain>/api/github-webhook/
  Content type: application/json
  Secret      : <same value as GITHUB_WEBHOOK_SECRET>
  Events      : Issues
"""

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.models import BugReport

logger = logging.getLogger(__name__)


# ── Signature verification ────────────────────────────────────────────────────

def _verify_signature(request) -> bool:
    secret = getattr(settings, 'GITHUB_WEBHOOK_SECRET', '')
    if not secret:
        return True  # skip in dev / tests

    sig_header = request.headers.get('X-Hub-Signature-256', '')
    if not sig_header.startswith('sha256='):
        return False

    expected = hmac.new(
        secret.encode(),
        request.body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f'sha256={expected}', sig_header)


# ── Email ─────────────────────────────────────────────────────────────────────

def _build_from_email() -> str:
    domain = getattr(settings, 'DOMAIN', None)
    if domain:
        return f'issues@{domain}'
    return getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@localhost')


def _send_fix_notification(report: BugReport, issue_url: str, issue_title: str) -> None:
    """Send a formatted fix notification email to the bug reporter."""
    user = report.user
    if not user or not user.email:
        return

    try:
        profile = user.profile
    except Exception:
        return

    if not profile.notify_bug_fix:
        logger.info('Bug fix notification skipped: user %s has opted out', user.email)
        return

    category_display = dict(BugReport.CATEGORY_CHOICES).get(report.category, report.category)
    short_desc = report.description[:120].strip()
    if len(report.description) > 120:
        short_desc += '…'

    from_email = _build_from_email()
    subject = f'Your bug report has been resolved 🎉'

    # Plain-text version
    text_body = (
        f'Hi,\n\n'
        f'Good news — the issue you reported has been marked as resolved.\n\n'
        f'Category : {category_display}\n'
        f'Report   : {short_desc}\n'
        f'Issue    : {issue_url}\n\n'
        f'Thanks for helping make drp better.\n\n'
        f'— the drp team\n\n'
        f'---\n'
        f'To stop receiving these notifications, visit your account settings\n'
        f'and turn off "Bug fix notifications".\n'
        f'{settings.SITE_URL}/auth/account/\n'
    )

    # HTML version
    account_url = f'{settings.SITE_URL}/auth/account/'
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{subject}</title>
  <style>
    body {{
      margin: 0; padding: 0;
      background: #0d0d0d;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #e0e0e0;
    }}
    .wrapper {{
      max-width: 560px;
      margin: 40px auto;
      background: #161616;
      border: 1px solid #2a2a2a;
      border-radius: 10px;
      overflow: hidden;
    }}
    .header {{
      background: #1a1a1a;
      border-bottom: 1px solid #2a2a2a;
      padding: 24px 32px;
    }}
    .header .logo {{
      font-size: 1.3rem;
      font-weight: 700;
      letter-spacing: -.5px;
      color: #fff;
    }}
    .body {{
      padding: 32px;
    }}
    .badge {{
      display: inline-block;
      background: #0f2a0f;
      color: #4ade80;
      border: 1px solid #166534;
      border-radius: 999px;
      font-size: .78rem;
      font-weight: 600;
      letter-spacing: .04em;
      padding: .25rem .75rem;
      margin-bottom: 1.2rem;
    }}
    h1 {{
      font-size: 1.35rem;
      font-weight: 700;
      color: #fff;
      margin: 0 0 .6rem;
    }}
    p {{
      font-size: .93rem;
      line-height: 1.6;
      color: #aaa;
      margin: 0 0 1rem;
    }}
    .report-box {{
      background: #111;
      border: 1px solid #2a2a2a;
      border-radius: 6px;
      padding: 14px 18px;
      margin: 1.2rem 0;
    }}
    .report-box .label {{
      font-size: .75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: #555;
      margin-bottom: .35rem;
    }}
    .report-box .value {{
      font-size: .9rem;
      color: #ccc;
    }}
    .btn {{
      display: inline-block;
      background: #fff;
      color: #111;
      font-size: .9rem;
      font-weight: 600;
      text-decoration: none;
      padding: .6rem 1.4rem;
      border-radius: 6px;
      margin: .5rem 0 1.2rem;
    }}
    .footer {{
      border-top: 1px solid #222;
      padding: 20px 32px;
      font-size: .78rem;
      color: #444;
      line-height: 1.6;
    }}
    .footer a {{
      color: #555;
    }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <span class="logo">drp</span>
  </div>
  <div class="body">
    <div class="badge">✓ Resolved</div>
    <h1>Your bug report has been fixed 🎉</h1>
    <p>
      Good news — the issue you reported has been marked as resolved.
      Thanks for taking the time to let us know.
    </p>

    <div class="report-box">
      <div class="label">Category</div>
      <div class="value">{category_display}</div>
    </div>

    <div class="report-box">
      <div class="label">Your report</div>
      <div class="value">{short_desc}</div>
    </div>

    <p style="margin-top:1.2rem">
      <a href="{issue_url}" class="btn">View issue on GitHub →</a>
    </p>

    <p style="font-size:.85rem;color:#666">
      Thanks again for helping make drp better.
    </p>
  </div>
  <div class="footer">
    You received this email because you submitted a bug report on drp
    and bug fix notifications are enabled in your account.<br>
    <a href="{account_url}">Manage notification preferences</a>
  </div>
</div>
</body>
</html>"""

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[user.email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send()
        logger.info('Bug fix notification sent to %s for BugReport #%d', user.email, report.pk)
    except Exception:
        logger.exception('Failed to send bug fix notification for BugReport #%d', report.pk)


# ── Webhook view ──────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def github_webhook(request):
    """Receive GitHub issue webhook events."""
    if not _verify_signature(request):
        logger.warning('GitHub webhook: invalid signature from %s', request.META.get('REMOTE_ADDR'))
        return HttpResponse('Invalid signature', status=400)

    event = request.headers.get('X-GitHub-Event', '')
    if event != 'issues':
        # We only care about issue events; silently ack everything else.
        return JsonResponse({'status': 'ignored', 'event': event})

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse('Bad JSON', status=400)

    action = payload.get('action', '')
    if action != 'closed':
        return JsonResponse({'status': 'ignored', 'action': action})

    issue = payload.get('issue', {})
    issue_url = issue.get('html_url', '')
    issue_title = issue.get('title', '')

    if not issue_url:
        return JsonResponse({'status': 'no issue url'})

    # Find all BugReports that link to this GitHub issue URL.
    reports = list(
        BugReport.objects
        .filter(github_issue_url=issue_url)
        .exclude(github_issue_url='')
        .select_related('user__profile')
    )

    if not reports:
        logger.warning(
            'GitHub webhook: no BugReport found for issue %s — '
            'was GITHUB_TOKEN set when the report was submitted?',
            issue_url,
        )
        return JsonResponse({'status': 'ok', 'notified': 0, 'matched': 0})

    notified = 0
    for report in reports:
        _send_fix_notification(report, issue_url, issue_title)
        notified += 1

    logger.info('GitHub webhook: issue closed %s — notified %d/%d reporter(s)',
                issue_url, notified, len(reports))
    return JsonResponse({'status': 'ok', 'notified': notified})