from django.urls import path

from api import views

app_name = "api"

urlpatterns = [
    path("ping/", views.ping, name="ping"),
    path("crash/", views.crash_report, name="crash"),
    path("auth/guest/", views.guest_login, name="guest_login"),
    path("auth/login/", views.login_view, name="login"),
]