from django.urls import path

from core import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("account/", views.account_view, name="account"),
    path("account/settings/", views.account_settings, name="account_settings"),
    path("verify/<str:token>/", views.verify_email, name="verify_email"),
    path("verify-resend/", views.verify_resend, name="verify_resend"),
]
