"""
core/views/mobile_blueprint.py

Staff-only mobile API reference.
All plan limits are read live from PlanLimit (DB-driven).
Base URL is read from settings.SITE_URL.
"""

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from core.models import Plan, PlanLimit


@staff_member_required
def mobile_blueprint(request):
    limits = PlanLimit.all_as_dicts()
    plans_ordered = [
        (Plan.ANON,    limits.get(Plan.ANON,    {})),
        (Plan.FREE,    limits.get(Plan.FREE,    {})),
        (Plan.STARTER, limits.get(Plan.STARTER, {})),
        (Plan.PRO,     limits.get(Plan.PRO,     {})),
    ]
    plan_fields = [
        'max_file_mb', 'max_text_kb', 'max_expiry_days',
        'clipboard_idle_hours', 'clipboard_max_lifetime_days',
        'anon_file_lifetime_days', 'storage_gb', 'renewals',
        'password_protection', 'max_collections',
    ]
    return render(request, 'mobile_blueprint.html', {
        'base_url':    settings.SITE_URL,
        'plans':       plans_ordered,
        'plan_fields': plan_fields,
    })