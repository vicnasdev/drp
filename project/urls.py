from django.contrib import admin
from django.urls import path

from api import views as api_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/ping/", api_views.ping, name="api_ping"),
    path("api/v1/helpbot/", api_views.helpbot, name="api_helpbot"),
]