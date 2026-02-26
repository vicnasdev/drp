"""
Email verification views and helpers.

Flow:
  1. User signs up → _send_verification_email() creates an EmailVerification
     token and emails a link to /auth/verify/<token>/
  2. User clicks link → verify_email_view() marks profile.email_verified=True
     and deletes the token.
  3. User can request a fresh link from /auth/verify/resend/ if the token
     expired or the email never arrived.

Gating:
  Use @verified_required on any view that needs a verified email.
  It redirects to a prompt page rather than returning 403, so the UX
  is friendly rather than a dead end.
"""

import secrets

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import render, redirect
from django.utils import timezone

from core.models import EmailVerification


def _send_verification_email(user):
    """Create (or replace) a verification token and send the email."""
    from core.models import EmailTemplate

    token = secrets.token_urlsafe(48)
    EmailVerification.objects.filter(user=user).delete()
    EmailVerification.objects.create(user=user, token=token)

    verify_url = f'{settings.SITE_URL}/auth/verify/{token}/'

    tpl = EmailTemplate.get('verify_email')
    if tpl:
        subject = tpl.render_subject(verify_url=verify_url)
        message = tpl.render_text(verify_url=verify_url)
        from_email = tpl.get_from_email()
    else:
        subject = 'Verify your drp email address'
        message = (
            f'Hi,\n\n'
            f'Click the link below to verify your drp email address.\n'
            f'The link expires in 24 hours.\n\n'
            f'{verify_url}\n\n'
            f'If you did not create a drp account, ignore this email.\n\n'
            f'— drp'
        )
        from_email = settings.DEFAULT_FROM_EMAIL

    send_mail(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=[user.email],
        fail_silently=False,
    )


def verify_email_view(request, token):
    """GET /auth/verify/<token>/ — mark email as verified."""
    try:
        ev = EmailVerification.objects.select_related('user').get(token=token)
    except EmailVerification.DoesNotExist:
        return render(request, 'auth/verify_invalid.html', status=400)

    if ev.is_expired():
        ev.delete()
        return render(request, 'auth/verify_expired.html', {
            'email': ev.user.email,
        }, status=400)

    profile = ev.user.profile
    profile.email_verified = True
    profile.save(update_fields=['email_verified'])
    ev.delete()

    return render(request, 'auth/verify_done.html', {'user': ev.user})


@login_required
def resend_verification_view(request):
    """POST /auth/verify/resend/ — send a fresh verification email."""
    if request.method != 'POST':
        return redirect('home')

    if request.user.profile.email_verified:
        return redirect('home')

    try:
        _send_verification_email(request.user)
        sent = True
    except Exception:
        sent = False

    return render(request, 'auth/verify_resend.html', {
        'sent': sent,
        'email': request.user.email,
    })


def verified_required(view_func):
    """
    Decorator: user must be logged in AND have a verified email.
    Redirects to a prompt page otherwise.
    """
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.conf import settings as s
            return redirect(f'{s.LOGIN_URL}?next={request.path}')
        if not request.user.profile.email_verified:
            return render(request, 'auth/verify_required.html', {
                'email': request.user.email,
            }, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper