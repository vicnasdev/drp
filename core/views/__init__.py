from .drops import (
    home, check_key, save_drop, drop_view, download_drop,
    upload_prepare, upload_confirm, upload_from_url, set_drop_password,
)
from .actions import rename_drop, delete_drop, renew_drop, copy_drop
from .auth import register_view, login_view, logout_view, account_view, manage_view, export_drops, import_drops, update_account_settings
from .bookmarks import save_bookmark, unsave_bookmark
from .bug_report import report_bug_view
from .legal import privacy_view, terms_view
from .use_cases import use_cases_view
from .verify import resend_verification_view, verify_email_view
# from .mobile_blueprint import mobile_blueprint
from .folders import (
    user_folders, folder_view, folder_or_alias_view,
    create_folder, add_to_folder, remove_from_folder,
    rename_folder, delete_folder, toggle_inbox,
)

__all__ = [
    "home", "check_key", "save_drop", "drop_view", "download_drop",
    "upload_prepare", "upload_confirm", "upload_from_url", "set_drop_password",
    "rename_drop", "delete_drop", "renew_drop", "copy_drop",
    "register_view", "login_view", "logout_view", "account_view", "manage_view",
    "export_drops", "import_drops", "update_account_settings",
    "save_bookmark", "unsave_bookmark",
    "privacy_view", "terms_view",
    "report_bug_view",
    "use_cases_view",
    "resend_verification_view",
    "verify_email_view",
    # "mobile_blueprint",
    "user_folders", "folder_view", "folder_or_alias_view",
    "create_folder", "add_to_folder", "remove_from_folder",
    "rename_folder", "delete_folder", "toggle_inbox",
]