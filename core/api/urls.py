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
    # FIX: added GET handler to files_upload view so authenticated users can
    # list their own drops — needed by shell `ls` at root to show loose drops
    # (drops not in any folder).
    path("files/",                      views.files_list_or_upload, name="api_files"),
    path("files/<str:key>/",            views.files_detail,         name="api_files_detail"),
    path("files/<str:key>/fork/",       views.files_fork,           name="api_files_fork"),

    # Folders
    path("folders/",                    views.folders_list_create,  name="api_folders"),
    path("folders/<int:folder_id>/",    views.folders_detail,       name="api_folders_detail"),

    # Drive cache version (cheap hash for CLI autocomplete polling)
    path("drive/version/",              views.drive_version,        name="api_drive_version"),

    # Path resolver (shell cd)
    path("resolve/",                    views.resolve,              name="api_resolve"),

    # Share tokens
    path("share/",                      views.share_list_create,    name="api_share"),
    path("share/<int:token_id>/",       views.share_detail,         name="api_share_detail"),

    # API tokens
    path("tokens/",                     views.tokens_list_create,   name="api_tokens"),
    path("tokens/<int:token_id>/",      views.tokens_detail,        name="api_tokens_detail"),

    # Crash reporting
    path("crash/",                      views.crash_report,         name="api_crash"),
]