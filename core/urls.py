from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [

    # ── Drop actions ──────────────────────────────────────────────────────────
    path("save/",                views.drop_save,            name="drop_save"),
    path("check-key/",           views.check_key,            name="check_key"),

    path("<str:key>/",           views.drop_view,            name="drop_view"),
    path("<str:key>/raw/",       views.drop_raw,             name="drop_raw"),
    path("<str:key>/download/",  views.drop_download,        name="drop_download"),
    path("<str:key>/delete/",    views.drop_delete,          name="drop_delete"),
    path("<str:key>/rename/",    views.drop_rename,          name="drop_rename"),
    path("<str:key>/save/",      views.drop_save_bookmark,   name="drop_save_bookmark"),
    path("<str:key>/unsave/",    views.drop_remove_bookmark, name="drop_remove_bookmark"),
    path("<str:key>/like/",      views.drop_like,            name="drop_like"),
    path("<str:key>/set-password/", views.drop_set_password, name="drop_set_password"),

    # ── Embed ─────────────────────────────────────────────────────────────────
    path("embed/<str:key>/",     views.drop_embed,           name="drop_embed"),

    # ── Auth ──────────────────────────────────────────────────────────────────
    path("auth/login/",          views.login_view,           name="login"),
    path("auth/logout/",         views.logout_view,          name="logout"),
    path("auth/register/",       views.register_view,        name="register"),
    path("auth/account/",        views.account_view,         name="account"),
    path("auth/account/settings/", views.account_settings,  name="account_settings"),
    path("auth/manage/",         views.manage_view,          name="manage"),
    path("auth/account/export/", views.account_export,       name="account_export"),
    path("auth/account/import/", views.account_import,       name="account_import"),

    # Email verification
    path("auth/verify/<str:token>/", views.verify_email,     name="verify_email"),
    path("auth/verify/resend/",      views.verify_resend,    name="verify_resend"),

    # Password reset (Django built-in)
    path("auth/forgot-password/",
         auth_views.PasswordResetView.as_view(
             template_name="registration/password_reset_form.html",
             email_template_name="registration/password_reset_email.html",
             subject_template_name="registration/password_reset_subject.txt",
         ),
         name="password_reset"),
    path("auth/forgot-password/done/",
         auth_views.PasswordResetDoneView.as_view(
             template_name="registration/password_reset_done.html",
         ),
         name="password_reset_done"),
    path("auth/reset/<uidb64>/<token>/",
         auth_views.PasswordResetConfirmView.as_view(
             template_name="registration/password_reset_confirm.html",
         ),
         name="password_reset_confirm"),
    path("auth/reset/done/",
         auth_views.PasswordResetCompleteView.as_view(
             template_name="registration/password_reset_complete.html",
         ),
         name="password_reset_complete"),

    # ── Folders ───────────────────────────────────────────────────────────────
    path("folders/create/",                        views.folder_create,       name="folder_create"),
    path("folders/<int:folder_id>/add/",           views.folder_add,          name="folder_add"),
    path("folders/<int:folder_id>/delete/",        views.folder_delete,       name="folder_delete"),
    path("folders/<int:folder_id>/remove/<str:key>/", views.folder_remove_item, name="folder_remove_item"),

    # ── Public profiles ───────────────────────────────────────────────────────
    path("@<str:username>/",                   views.profile_view, name="profile"),
    path("@<str:username>/<str:folder_slug>/", views.folder_view,  name="folder_view"),

    # ── Explore ───────────────────────────────────────────────────────────────
    path("explore/",   views.explore_view,       name="explore"),

    # ── Static pages ─────────────────────────────────────────────────────────
    path("features/",   views.features_view,     name="features"),
    path("use-cases/",  views.use_cases_view,    name="use_cases"),
    path("report-bug/", views.bug_report_view,   name="bug_report"),
    path("report-bug/done/", views.bug_report_done_view, name="bug_report_done"),
]
