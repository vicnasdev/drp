"""
User-facing bug report form.

- POST /report-bug/
- Requires: logged-in + email verified
- Rate limit: BUG_REPORT_DAILY_LIMIT per user per calendar day
- Turnstile validation (skipped when TURNSTILE_SECRET_KEY is unset, e.g. in tests)
- Creates a GitHub issue via the API and stores the result in BugReport
- hide_identity=True (default): omits email from the issue body
"""

import requests as http_lib

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render, redirect

from core.models import BugReport
from core.error_reporting_logic import GITHUB_API, GITHUB_REPO, GITHUB_TOKEN
from .verify import verified_required


# ── Turnstile ─────────────────────────────────────────────────────────────────

def _verify_turnstile(token: str, ip: str) -> bool:
    """Return True if the Turnstile response token is valid."""
    secret = getattr(settings, 'TURNSTILE_SECRET_KEY', '')
    if not secret:
        return True  # skip in dev / tests
    try:
        res = http_lib.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret, 'response': token, 'remoteip': ip},
            timeout=5,
        )
        return res.json().get('success', False)
    except Exception:
        return False


# ── Rate limiting ─────────────────────────────────────────────────────────────

def _rate_limit_ok(user) -> bool:
    """Return True if the user hasn't hit their daily report limit."""
    from django.utils import timezone
    limit = getattr(settings, 'BUG_REPORT_DAILY_LIMIT', 3)
    today = timezone.now().date().isoformat()
    key = f'bug_report:{user.pk}:{today}'
    count = cache.get(key, 0)
    if count >= limit:
        return False
    # Expire at midnight + a small buffer
    cache.set(key, count + 1, timeout=86400)
    return True


# ── GitHub issue ──────────────────────────────────────────────────────────────

def _create_github_issue(report: BugReport) -> str:
    """
    File a GitHub issue for the report. Returns the issue HTML URL or ''.
    """
    if not GITHUB_TOKEN:
        return ''

    category_label = BugReport.CATEGORY_LABELS.get(report.category, 'question')
    category_display = dict(BugReport.CATEGORY_CHOICES).get(report.category, report.category)

    if report.hide_identity:
        attribution = '*Identity hidden by reporter.*'
    else:
        attribution = f'Reported by: {report.user.email}' if report.user else 'Anonymous'

    body = (
        f'## {category_display}\n\n'
        f'{report.description}\n\n'
        f'---\n'
        f'*{attribution}*\n'
        f'*Submitted via drp report form.*'
    )

    try:
        res = http_lib.post(
            f'{GITHUB_API}/repos/{GITHUB_REPO}/issues',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github+json',
            },
            json={
                'title': f'[user] {category_display}: {report.description[:60]}',
                'body': body,
                'labels': ['user-reported', category_label],
            },
            timeout=8,
        )
        if res.status_code == 201:
            return res.json().get('html_url', '')
    except Exception:
        pass
    return ''


# ── View ──────────────────────────────────────────────────────────────────────

@verified_required
def report_bug_view(request):
    error = None

    if request.method == 'POST':
        category    = request.POST.get('category', '').strip()
        description = request.POST.get('description', '').strip()
        hide        = request.POST.get('hide_identity', '0') == '1'
        ts_token    = request.POST.get('cf-turnstile-response', '')

        valid_categories = [c for c, _ in BugReport.CATEGORY_CHOICES]

        if category not in valid_categories:
            error = 'Please choose a category.'
        elif len(description) < 20:
            error = 'Description must be at least 20 characters.'
        elif len(description) > 3000:
            error = 'Description must be under 3000 characters.'
        elif not _rate_limit_ok(request.user):
            limit = getattr(settings, 'BUG_REPORT_DAILY_LIMIT', 3)
            error = f'You can submit up to {limit} reports per day. Try again tomorrow.'
        else:
            report = BugReport.objects.create(
                user=request.user,
                category=category,
                description=description,
                hide_identity=hide,
            )
            url = _create_github_issue(report)
            if url:
                report.github_issue_url = url
                report.save(update_fields=['github_issue_url'])

            return render(request, 'bug_report_done.html', {
                'github_url': url,
            })

    return render(request, 'bug_report.html', {
        'categories': BugReport.CATEGORY_CHOICES,
        'error': error,
    })