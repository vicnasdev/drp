from django.urls import path, re_path
from django.contrib.auth import views as auth_views
from core import views
from core.views.error_reporting import report_error
from core.views.github_webhook import github_webhook
from core.views.drops import raw_view, raw_file, set_drop_password
from core.views.legal import privacy_view, terms_view

KEY = r"(?P<key>[^/\s]+)"

urlpatterns = [
    path("api/report-error/",   report_error,          name="report_error"),
    path("staff/mobile/", views.mobile_blueprint, name="mobile_blueprint"),
    path("api/github-webhook/", github_webhook,         name="github_webhook"),
    path("save/",               views.save_drop,        name="save_drop"),
    path("check-key/",          views.check_key,        name="check_key"),
    path("upload/prepare/",     views.upload_prepare,   name="upload_prepare"),
    path("upload/confirm/",     views.upload_confirm,   name="upload_confirm"),
    re_path(rf"^raw/{KEY}/$",   raw_view,               name="raw_view"),
    path("privacy/",            privacy_view,           name="privacy"),
    path("terms/",              terms_view,             name="terms"),
    path("auth/register/",      views.register_view,    name="register"),
    path("auth/login/",         views.login_view,       name="login"),
    path("auth/logout/",        views.logout_view,      name="logout"),
    path("auth/account/",       views.account_view,     name="account"),
    path("auth/account/export/", views.export_drops,    name="export_drops"),
    path("auth/account/import/", views.import_drops,    name="import_drops"),
    path("auth/account/settings/", views.update_account_settings, name="account_settings"),
    path("auth/verify/resend/", views.resend_verification_view, name="verify_resend"),
    re_path(r"^auth/verify/(?P<token>[^/]+)/$", views.verify_email_view, name="verify_email"),
    path("report-bug/",         views.report_bug_view,  name="report_bug"),
    path("auth/forgot-password/",
         auth_views.PasswordResetView.as_view(
             template_name="registration/password_reset_form.html",
             email_template_name="registration/password_reset_email.html",
             subject_template_name="registration/password_reset_subject.txt",
         ),
         name="forgot_password"),
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
    # Collections — must be before the /<key>/ catch-all
    path("collections/create/",                   views.create_collection,        name="collection_create"),
    path("collections/<int:collection_id>/add/",   views.add_to_collection,        name="collection_add"),
    path("collections/<int:collection_id>/remove/", views.remove_from_collection,  name="collection_remove"),
    path("collections/<int:collection_id>/rename/", views.rename_collection,       name="collection_rename"),
    path("collections/<int:collection_id>/delete/", views.delete_collection,       name="collection_delete"),
    re_path(r"^@(?P<username>[^/]+)/$",             views.user_collections,         name="user_collections"),
    re_path(r"^@(?P<username>[^/]+)/(?P<slug>[^/]+)/$", views.collection_view,     name="collection_view"),
    re_path(rf"^f/{KEY}/download/$",      views.download_drop,                         name="download_drop"),
    re_path(rf"^f/{KEY}/raw/$",            raw_file,                                    name="raw_file"),
    re_path(rf"^f/{KEY}/rename/$",        views.rename_drop,    {"ns": "f"},           name="rename_file"),
    re_path(rf"^f/{KEY}/delete/$",        views.delete_drop,    {"ns": "f"},           name="delete_file"),
    re_path(rf"^f/{KEY}/renew/$",         views.renew_drop,     {"ns": "f"},           name="renew_file"),
    re_path(rf"^f/{KEY}/copy/$",          views.copy_drop,      {"ns": "f"},           name="copy_file"),
    re_path(rf"^f/{KEY}/save/$",          views.save_bookmark,  {"ns": "f"},           name="save_bookmark_file"),
    re_path(rf"^f/{KEY}/unsave/$",        views.unsave_bookmark, {"ns": "f"},          name="unsave_bookmark_file"),
    re_path(rf"^f/{KEY}/set-password/$",  set_drop_password,    {"ns": "f"},           name="set_password_file"),
    re_path(rf"^f/{KEY}/$",               views.file_view,                             name="file_view"),
    re_path(rf"^{KEY}/rename/$",       views.rename_drop,    {"ns": "c"},              name="rename_clipboard"),
    re_path(rf"^{KEY}/delete/$",       views.delete_drop,    {"ns": "c"},              name="delete_clipboard"),
    re_path(rf"^{KEY}/renew/$",        views.renew_drop,     {"ns": "c"},              name="renew_clipboard"),
    re_path(rf"^{KEY}/copy/$",         views.copy_drop,      {"ns": "c"},              name="copy_clipboard"),
    re_path(rf"^{KEY}/save/$",         views.save_bookmark,  {"ns": "c"},              name="save_bookmark_clipboard"),
    re_path(rf"^{KEY}/unsave/$",       views.unsave_bookmark, {"ns": "c"},             name="unsave_bookmark_clipboard"),
    re_path(rf"^{KEY}/set-password/$", set_drop_password,    {"ns": "c"},              name="set_password_clipboard"),
    re_path(rf"^{KEY}/$",              views.clipboard_view,                            name="clipboard_view"),
]