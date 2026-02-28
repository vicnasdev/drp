from django.shortcuts import render


def bad_request(request, exception=None):
    return render(request, "error.html", {"code": 400, "message": "Bad request."}, status=400)


def forbidden(request, exception=None):
    return render(request, "error.html", {"code": 403, "message": "Forbidden."}, status=403)


def not_found(request, exception=None):
    return render(request, "error.html", {"code": 404, "message": "Page not found."}, status=404)


def server_error(request):
    return render(request, "error.html", {"code": 500, "message": "Server error. We've been notified."}, status=500)
