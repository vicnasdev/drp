from django.contrib import admin
from .models import (
    File, Folder, FolderItem, FileBookmark,
    UserProfile, APIToken, Like, BugReport, HelpBotHistory,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ("user", "plan", "email_verified", "storage_used_bytes", "ls_subscription_status")
    list_filter   = ("plan", "email_verified")
    search_fields = ("user__username", "user__email", "ls_customer_id")
    readonly_fields = ("storage_used_bytes",)


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display  = ("key", "owner", "filename", "content_type", "size", "expires_at", "is_public", "created_at")
    list_filter   = ("is_public", "content_type")
    search_fields = ("key", "filename", "owner__username")
    readonly_fields = ("created_at", "updated_at", "view_count", "last_viewed_at")


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display  = ("slug", "owner", "is_public", "created_at")
    search_fields = ("slug", "owner__username")


@admin.register(FileBookmark)
class FileBookmarkAdmin(admin.ModelAdmin):
    list_display  = ("user", "file_key", "created_at")
    search_fields = ("user__username", "file_key")


@admin.register(BugReport)
class BugReportAdmin(admin.ModelAdmin):
    list_display  = ("category", "user", "created_at", "description")
    list_filter   = ("category",)
    readonly_fields = ("created_at",)


@admin.register(APIToken)
class APITokenAdmin(admin.ModelAdmin):
    list_display  = ("user", "label", "last_used", "created_at")
    search_fields = ("user__username", "label")


admin.site.register(Like)
admin.site.register(FolderItem)
admin.site.register(HelpBotHistory)
