from django.contrib import admin

from .models import Bookmark, File, Folder, Key, Like


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("slug", "owner", "parent", "path_public", "created_at")
    list_filter = ("path_public",)
    search_fields = ("slug", "name", "owner__username")
    raw_id_fields = ("owner", "parent")


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ("filename", "owner", "folder", "content_type", "filesize", "encrypted", "created_at")
    list_filter = ("encrypted", "content_type")
    search_fields = ("filename", "owner__username", "b2_key")
    raw_id_fields = ("owner", "folder")


@admin.register(Key)
class KeyAdmin(admin.ModelAdmin):
    list_display = ("key", "file", "expires_at", "burn", "burned", "publish", "custom", "like_count", "created_at")
    list_filter = ("burn", "burned", "publish", "custom")
    search_fields = ("key", "file__filename")
    raw_id_fields = ("file",)


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ("key", "user", "ip", "created_at")
    raw_id_fields = ("key", "user")


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ("user", "key", "created_at")
    raw_id_fields = ("user", "key")
