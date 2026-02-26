from django.urls import path, re_path
from django.contrib.auth import views as auth_views
from core import views
from core.views.error_reporting import report_error
from core.views.github_webhook import github_webhook
from core.views.drops import raw_view, raw_file, set_drop_password, embed_view, public_feed
from core.views.helpers import qr_view
from core.views.legal import privacy_view, terms_view
from core.views.groups import (
    resolve_handle, create_group, create_invite, join_group,
    change_member_role, remove_member,
)
from core.views.tokens import create_token, list_tokens, revoke_token
from core.views.aliases import create_alias, list_aliases, delete_alias, resolve_alias
from core.views.templates import create_template, list_templates, get_template, delete_template
from core.views.features import feature_list, feature_submit, feature_vote
from core.views.transfers import send_transfer, claim_transfer
from core.views.likes import toggle_like

KEY = r"(?P<key>[^/\s]+)"

urlpatterns = [
    path("api/report-error/",   report_error,          name="report_error"),
    # path("staff/mobile/", views.mobile_blueprint, name="mobile_blueprint"),
    path("api/github-webhook/", github_webhook,         name="github_webhook"),
    path("save/",               views.save_drop,        name="save_drop"),
    path("check-key/",          views.check_key,        name="check_key"),
    path("upload/prepare/",     views.upload_prepare,   name="upload_prepare"),
    path("upload/confirm/",     views.upload_confirm,   name="upload_confirm"),
    path("upload/from-url/",    views.upload_from_url,  name="upload_from_url"),
    re_path(rf"^raw/{KEY}/$",   raw_view,               name="raw_view"),
    re_path(rf"^embed/{KEY}/$", embed_view,             name="embed_view"),
    path("explore/",            public_feed,            name="public_feed"),
    path("qr/",                 qr_view,                name="qr_view"),
    path("privacy/",            privacy_view,           name="privacy"),
    path("terms/",              terms_view,             name="terms"),
    path("auth/register/",      views.register_view,    name="register"),
    path("auth/login/",         views.login_view,       name="login"),
    path("auth/logout/",        views.logout_view,      name="logout"),
    path("auth/account/",       views.account_view,     name="account"),
    path("auth/manage/",        views.manage_view,      name="manage"),
    path("auth/account/export/", views.export_drops,    name="export_drops"),
    path("auth/account/import/", views.import_drops,    name="import_drops"),
    path("auth/account/settings/", views.update_account_settings, name="account_settings"),
    # API tokens
    path("auth/tokens/",                  list_tokens,    name="token_list"),
    path("auth/tokens/create/",           create_token,   name="token_create"),
    path("auth/tokens/<int:token_id>/revoke/", revoke_token, name="token_revoke"),
    # Aliases
    path("auth/aliases/",                   list_aliases,   name="alias_list"),
    path("auth/aliases/create/",            create_alias,   name="alias_create"),
    path("auth/aliases/<int:alias_id>/delete/", delete_alias, name="alias_delete"),
    # Drop templates
    path("auth/templates/",                        list_templates,   name="template_list"),
    path("auth/templates/create/",                 create_template,  name="template_create"),
    path("auth/templates/<slug:slug>/",            get_template,     name="template_get"),
    path("auth/templates/<int:template_id>/delete/", delete_template, name="template_delete"),
    path("auth/verify/resend/", views.resend_verification_view, name="verify_resend"),
    re_path(r"^auth/verify/(?P<token>[^/]+)/$", views.verify_email_view, name="verify_email"),
    path("report-bug/",         views.report_bug_view,  name="report_bug"),
    path("use-cases/",          views.use_cases_view,   name="use_cases"),
    # Feature voting board
    path("features/",                          feature_list,    name="feature_list"),
    path("features/submit/",                   feature_submit,  name="feature_submit"),
    path("features/<int:proposal_id>/vote/",   feature_vote,    name="feature_vote"),
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
    # Groups
    path("groups/create/",                              create_group,          name="group_create"),
    path("groups/join/",                                join_group,            name="group_join"),
    path("groups/<int:group_id>/invite/",               create_invite,         name="group_invite"),
    path("groups/<int:group_id>/members/<int:user_id>/role/",    change_member_role, name="group_member_role"),
    path("groups/<int:group_id>/members/<int:user_id>/remove/",  remove_member,      name="group_member_remove"),
    # Collections — must be before the /<key>/ catch-all
    path("collections/create/",                   views.create_collection,        name="collection_create"),
    path("collections/<int:collection_id>/add/",   views.add_to_collection,        name="collection_add"),
    path("collections/<int:collection_id>/remove/", views.remove_from_collection,  name="collection_remove"),
    path("collections/<int:collection_id>/rename/", views.rename_collection,       name="collection_rename"),
    path("collections/<int:collection_id>/delete/", views.delete_collection,       name="collection_delete"),
    path("collections/<int:collection_id>/toggle-inbox/", views.toggle_inbox,     name="collection_toggle_inbox"),
    re_path(r"^@(?P<handle>[^/]+)/$",                    resolve_handle,         name="resolve_handle"),
    re_path(r"^@(?P<username>[^/]+)/(?P<path>.+)/$", views.collection_or_alias_view, name="collection_view"),
    re_path(rf"^f/{KEY}/download/$",      views.download_drop,                         name="download_drop"),
    re_path(rf"^f/{KEY}/raw/$",            raw_file,                                    name="raw_file"),
    re_path(rf"^f/{KEY}/rename/$",        views.rename_drop,    {"ns": "f"},           name="rename_file"),
    re_path(rf"^f/{KEY}/delete/$",        views.delete_drop,    {"ns": "f"},           name="delete_file"),
    re_path(rf"^f/{KEY}/renew/$",         views.renew_drop,     {"ns": "f"},           name="renew_file"),
    re_path(rf"^f/{KEY}/copy/$",          views.copy_drop,      {"ns": "f"},           name="copy_file"),
    re_path(rf"^f/{KEY}/switch/$",        views.switch_drop,    {"ns": "f"},           name="switch_file"),
    re_path(rf"^f/{KEY}/save/$",          views.save_bookmark,  {"ns": "f"},           name="save_bookmark_file"),
    re_path(rf"^f/{KEY}/unsave/$",        views.unsave_bookmark, {"ns": "f"},          name="unsave_bookmark_file"),
    re_path(rf"^f/{KEY}/set-password/$",  set_drop_password,    {"ns": "f"},           name="set_password_file"),
    re_path(rf"^f/{KEY}/send/$",          send_transfer,        {"ns": "f"},           name="send_file"),
    re_path(rf"^f/{KEY}/like/$",          toggle_like,          {"ns": "f"},           name="like_file"),
    re_path(rf"^f/{KEY}/$",               views.file_view,                             name="file_view"),
    re_path(rf"^{KEY}/rename/$",       views.rename_drop,    {"ns": "c"},              name="rename_clipboard"),
    re_path(rf"^{KEY}/delete/$",       views.delete_drop,    {"ns": "c"},              name="delete_clipboard"),
    re_path(rf"^{KEY}/renew/$",        views.renew_drop,     {"ns": "c"},              name="renew_clipboard"),
    re_path(rf"^{KEY}/copy/$",         views.copy_drop,      {"ns": "c"},              name="copy_clipboard"),
    re_path(rf"^{KEY}/switch/$",       views.switch_drop,    {"ns": "c"},              name="switch_clipboard"),
    re_path(rf"^{KEY}/save/$",         views.save_bookmark,  {"ns": "c"},              name="save_bookmark_clipboard"),
    re_path(rf"^{KEY}/unsave/$",       views.unsave_bookmark, {"ns": "c"},             name="unsave_bookmark_clipboard"),
    re_path(rf"^{KEY}/set-password/$", set_drop_password,    {"ns": "c"},              name="set_password_clipboard"),
    re_path(rf"^{KEY}/send/$",         send_transfer,        {"ns": "c"},              name="send_clipboard"),
    re_path(rf"^{KEY}/like/$",         toggle_like,          {"ns": "c"},              name="like_clipboard"),
    path("claim/<str:token>/",          claim_transfer,                                name="claim_transfer"),
    re_path(rf"^{KEY}/$",              views.clipboard_view,                            name="clipboard_view"),
]