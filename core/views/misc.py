from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from core.models import BugReport


def features_view(request):
    return render(request, "features.html")


def use_cases_view(request):
    return render(request, "use_cases.html")


BUG_CATEGORIES = BugReport.CATEGORIES


def bug_report_view(request):
    if not request.user.is_authenticated:
        return redirect(f"/auth/login/?next=/report-bug/")

    profile = request.user.profile
    if not profile.email_verified:
        return render(request, "auth/verify_required.html", {"email": request.user.email})

    if request.method == "POST":
        from django.conf import settings
        daily_limit = getattr(settings, "BUG_REPORT_DAILY_LIMIT", 3)
        today_count = BugReport.objects.filter(
            user=request.user,
            created_at__date=timezone.now().date(),
        ).count()
        if today_count >= daily_limit:
            return render(request, "bug_report.html", {
                "categories": BUG_CATEGORIES,
                "error": f"You've submitted {daily_limit} reports today. Please wait until tomorrow.",
            })

        category    = request.POST.get("category", "")
        description = request.POST.get("description", "").strip()
        hide        = bool(request.POST.get("hide_identity"))

        if not category or not description or len(description) < 20:
            return render(request, "bug_report.html", {
                "categories": BUG_CATEGORIES,
                "error": "Please fill in all fields (description must be at least 20 characters).",
            })

        BugReport.objects.create(
            user          = None if hide else request.user,
            category      = category,
            description   = description,
            hide_identity = hide,
        )
        return redirect("bug_report_done")

    return render(request, "bug_report.html", {"categories": BUG_CATEGORIES})


def bug_report_done_view(request):
    return render(request, "bug_report_done.html")
