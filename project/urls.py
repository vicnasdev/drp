from django.contrib import admin
from django.urls import include, path

from core.views import error_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
    path("auth/", include("core.urls")),
    path("help/", include("help.urls")),
    path("billing/", include("billing.urls")),
    # Drive routes (explore, embed, profiles, keys) — must be last
    path("", include("drive.urls")),
]

handler400 = error_view
handler403 = error_view
handler404 = error_view
handler500 = error_view