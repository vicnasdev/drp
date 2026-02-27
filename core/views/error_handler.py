"""
Custom Django error handlers.

Wire these up in project/urls.py:
    handler400 = 'core.views.error_handler.bad_request'
    handler403 = 'core.views.error_handler.forbidden'
    handler404 = 'core.views.error_handler.not_found'
    handler500 = 'core.views.error_handler.server_error'

400, 403, 404 — expected, user-facing outcomes. Render a nice page, no reporting.
500           — always a bug. Render a nice page AND file a GitHub issue.
"""

import sys

from django.shortcuts import render
from django.views.defaults import server_error as django_server_error

from core.views.error_reporting import report_server_error


def bad_request(request, exception=None, *args, **kwargs):
    return render(request, 'error.html', {'code': 400, 'message': 'Bad request.'}, status=400)


def forbidden(request, exception=None, *args, **kwargs):
    return render(request, 'error.html', {'code': 403, 'message': "You don't have permission to access this page."}, status=403)


def not_found(request, exception=None, *args, **kwargs):
    try:
        return render(request, 'error.html', {'code': 404, 'message': "This page doesn't exist."}, status=404)
    except Exception:
        from django.http import HttpResponse
        return HttpResponse("404 — not found", status=404, content_type="text/plain")


def server_error(request, *args, **kwargs):
    exc = sys.exc_info()[1]
    try:
        report_server_error(request, exc)
    except Exception:
        pass  # never let the reporter crash the error page
    try:
        return render(request, 'error.html', {'code': 500, 'message': "Something went wrong on our end. It's been reported."}, status=500)
    except Exception:
        from django.http import HttpResponse
        return HttpResponse("500 — internal server error", status=500, content_type="text/plain")