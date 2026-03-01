from django.urls import path

from . import views

urlpatterns = [
    path("", views.help_index, name="help_index"),
    path("cli/", views.help_cli, name="help_cli"),
    path("plans/", views.help_plans, name="help_plans"),
    path("expiry/", views.help_expiry, name="help_expiry"),
    path("security/", views.help_security, name="help_security"),
]
