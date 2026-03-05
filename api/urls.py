from django.urls import path

from api import views

app_name = "api"

urlpatterns = [
    path("ping/", views.ping, name="ping"),
    path("crash/", views.crash_report, name="crash"),
]
