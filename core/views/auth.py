"""
Auth views: register, login, logout, account dashboard, export, import.
"""

import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import models
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from core.models import Drop, Folder, FolderItem, Plan
from .helpers import check_signup_rate, user_plan, claim_anon_drops, validate_username

ANON_COOKIE = 'drp_anon'


def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    error = None
    if request.method == 'POST':
        if not check_signup_rate(request):
            error = 'Too many signups from your location. Try again in an hour.'
        else:
            email = request.POST.get('email', '').strip().lower()
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
            password2 = request.POST.get('password2', '')
            plan_choice = request.POST.get('plan', 'free').strip().lower()

            username_error = validate_username(username)
            if not email or not password:
                error = 'Email and password are required.'
            elif username_error:
                error = username_error
            elif User.objects.filter(username__iexact=username).exists():
                error = 'That username is already taken.'
            elif password != password2:
                error = 'Passwords do not match.'
            elif len(password) < 8:
                error = 'Password must be at least 8 characters.'
            elif User.objects.filter(email=email).exists():
                error = 'An account with that email already exists.'
            else:
                user = User.objects.create_user(username=username, email=email, password=password)
                login(request, user)

                # Send email verification — fire and forget, never block signup
                try:
                    from core.views.verify import _send_verification_email
                    _send_verification_email(user)
                except Exception:
                    pass

                token = request.COOKIES.get(ANON_COOKIE)
                claimed = claim_anon_drops(user, token)
                if claimed:
                    request.session['claimed_drops'] = claimed

                if plan_choice in ('starter', 'pro'):
                    response = redirect(f'/billing/checkout/{plan_choice}/')
                else:
                    response = redirect('home')

                if token:
                    response.delete_cookie(ANON_COOKIE)
                return response

    return render(request, 'auth/register.html', {
        'error': error,
        'admin_email': settings.ADMIN_EMAIL,
    })


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    error = None
    if request.method == 'POST':
        identifier = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        # Accept username or email
        if '@' in identifier:
            try:
                user_obj = User.objects.get(email__iexact=identifier)
                username = user_obj.username
            except User.DoesNotExist:
                username = identifier  # let authenticate fail naturally
        else:
            username = identifier
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)

            token = request.COOKIES.get(ANON_COOKIE)
            claimed = claim_anon_drops(user, token)
            if claimed:
                request.session['claimed_drops'] = claimed

            response = redirect(request.GET.get('next', '/'))
            if token:
                response.delete_cookie(ANON_COOKIE)
            return response

        error = 'Invalid username/email or password.'

    return render(request, 'auth/login.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('home')


@login_required
def account_view(request):
    profile = request.user.profile
    profile.recalc_storage()

    for d in Drop.objects.filter(owner=request.user):
        if d.is_expired():
            d.hard_delete()

    drops = Drop.objects.filter(owner=request.user).order_by('-created_at')
    root = Folder.objects.filter(owner=request.user, parent=None, slug="drops").first()
    saved_items = FolderItem.objects.filter(folder=root).order_by('-added_at') if root else FolderItem.objects.none()
    plan_limits = Plan.LIMITS.get(profile.plan, Plan.LIMITS[Plan.FREE])

    if 'application/json' in request.headers.get('Accept', ''):
        folders = request.user.folders.prefetch_related('items').order_by('-created_at')
        return JsonResponse({
            'username':            request.user.username,
            'email':               request.user.email,
            'plan':                profile.plan,
            'storage_used_bytes':  profile.storage_used_bytes,
            'storage_quota_bytes': profile.storage_quota_bytes,
            'plan_limits':         plan_limits,
            'drops': [_drop_dict(d) for d in drops],
            'saved': [{'key': i.key, 'saved_at': i.added_at.isoformat()} for i in saved_items],
            'folders': [
                {
                    'id':   f.pk,
                    'name': f.name,
                    'slug': f.slug,
                    'path': f.full_path,
                    'parent_id': f.parent_id,
                    'children': list(f.children.values_list('slug', flat=True)),
                    'drops': [{'key': m.key} for m in f.items.all()],
                }
                for f in folders
            ],
        })

    return render(request, 'auth/account.html', {
        'profile': profile,
        'drops': drops,
        'saved': saved_items,
        'plan_limits': plan_limits,
        'Plan': Plan,
    })


@login_required
def manage_view(request):
    """Manage page — bulk actions on drops, saved drops, folders."""
    from core.models import Folder

    profile = request.user.profile
    profile.recalc_storage()

    for d in Drop.objects.filter(owner=request.user):
        if d.is_expired():
            d.hard_delete()

    drops = Drop.objects.filter(owner=request.user).order_by('-created_at')
    root = Folder.objects.filter(owner=request.user, parent=None, slug="drops").first()
    saved_items = FolderItem.objects.filter(folder=root).order_by('-added_at') if root else FolderItem.objects.none()
    folders = request.user.folders.annotate(
        drop_count=models.Count('items')
    ).order_by('-created_at')

    return render(request, 'auth/manage.html', {
        'profile': profile,
        'drops': drops,
        'saved': saved_items,
        'folders': folders,
    })


@login_required
@require_POST
def update_account_settings(request):
    """Update user account notification preferences."""
    profile = request.user.profile
    profile.notify_bug_fix        = request.POST.get('notify_bug_fix')        == '1'
    profile.notify_product_updates = request.POST.get('notify_product_updates') == '1'
    profile.notify_billing         = request.POST.get('notify_billing')         == '1'
    profile.save(update_fields=['notify_bug_fix', 'notify_product_updates', 'notify_billing'])
    return redirect('account')


@login_required
def export_drops(request):
    drops = Drop.objects.filter(owner=request.user).order_by('-created_at')
    root = Folder.objects.filter(owner=request.user, parent=None, slug="drops").first()
    saved_items = FolderItem.objects.filter(folder=root).order_by('-added_at') if root else FolderItem.objects.none()
    folders = request.user.folders.prefetch_related('items').order_by('-created_at')

    owned_data = []
    for d in drops:
        entry = _drop_dict(d)
        url = f'{settings.SITE_URL}/{d.key}/'
        entry.update({'url': url, 'host': settings.SITE_URL})
        owned_data.append(entry)

    saved_data = [
        {'key': i.key, 'saved_at': i.added_at.isoformat(), 'url': f'{settings.SITE_URL}/{i.key}/'}
        for i in saved_items
    ]

    folders_data = [
        {
            'name': f.name,
            'slug': f.slug,
            'path': f.full_path,
            'parent_id': f.parent_id,
            'url':  f'{settings.SITE_URL}/@{request.user.username}/{f.full_path}/',
            'drops': [
                {'key': m.key}
                for m in f.items.all()
            ],
        }
        for f in folders
    ]

    response = JsonResponse(
        {'drops': owned_data, 'saved': saved_data, 'folders': folders_data},
        json_dumps_params={'indent': 2},
    )
    response['Content-Disposition'] = 'attachment; filename="drp-export.json"'
    return response


@login_required
@require_POST
def import_drops(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    if isinstance(data, list):
        entries = data
    else:
        entries = data.get('drops', []) + data.get('saved', [])

    if not entries:
        return JsonResponse({'imported': 0, 'skipped': 0})

    imported = 0
    skipped = 0

    for entry in entries:
        key = (entry.get('key') or '').strip()

        if not key:
            skipped += 1
            continue

        if Drop.objects.filter(key=key, owner=request.user).exists():
            skipped += 1
            continue

        root = Folder.objects.filter(owner=request.user, parent=None, slug="drops").first()
        if not root:
            root, _ = Folder.objects.get_or_create(
                owner=request.user, parent=None, slug="drops",
                defaults={"name": "My Drops"},
            )
        _, created = FolderItem.objects.get_or_create(
            folder=root, key=key,
        )
        if created:
            imported += 1
        else:
            skipped += 1

    return JsonResponse({'imported': imported, 'skipped': skipped})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _drop_dict(d):
    return {
        'key':            d.key,
        'kind':           d.kind,
        'created_at':     d.created_at.isoformat(),
        'last_accessed_at': d.last_accessed_at.isoformat() if d.last_accessed_at else None,
        'expires_at':     d.expires_at.isoformat() if d.expires_at else None,
        'filename':       d.filename or None,
        'filesize':       d.filesize,
        'locked':         d.locked,
        'view_count':     d.view_count,
        'last_viewed_at': d.last_viewed_at.isoformat() if d.last_viewed_at else None,
        'burn':           d.burn,
        'password_protected': d.is_password_protected,
        'is_public':      d.is_public,
        'tags':           d.tags,
    }