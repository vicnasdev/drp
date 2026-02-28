"""
core/api/urls.py

REST API routes consumed by the drp CLI.
Mount in project/urls.py with:
    path("api/v1/", include("core.api.urls")),
"""
from django.urls import path
from core.api import views

urlpatterns = [
    # Ping
    path("ping/",                       views.ping,                 name="api_ping"),

    # Auth
    path("auth/login/",                 views.auth_login,           name="api_auth_login"),
    path("auth/logout/",                views.auth_logout,          name="api_auth_logout"),
    path("auth/me/",                    views.auth_me,              name="api_auth_me"),

    # Files (drops)
    path("files/",                      views.files_upload,         name="api_files_upload"),
    path("files/<str:key>/",            views.files_detail,         name="api_files_detail"),
    path("files/<str:key>/fork/",       views.files_fork,           name="api_files_fork"),

    # Folders
    path("folders/",                    views.folders_list_create,  name="api_folders"),
    path("folders/<int:folder_id>/",    views.folders_detail,       name="api_folders_detail"),

    # Path resolver (shell cd)
    path("resolve/",                    views.resolve,              name="api_resolve"),

    # Share tokens
    path("share/",                      views.share_list_create,    name="api_share"),
    path("share/<int:token_id>/",       views.share_detail,         name="api_share_detail"),

    # API tokens
    path("tokens/",                     views.tokens_list_create,   name="api_tokens"),
    path("tokens/<int:token_id>/",      views.tokens_detail,        name="api_tokens_detail"),

    # FIX: crash reporting endpoint was missing entirely — the CLI was POSTing here
    # but getting 404s, so no CrashReport records were created and no GitHub issues
    # were ever filed. Added the route and its view below in views.py.
    path("crash/",                      views.crash_report,         name="api_crash"),
]