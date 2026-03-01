"""
Drive models — files, folders, and keys.

Every uploaded file lives here.  Keys are the public identifiers (URLs).
Folders organise files into a tree.  Path access is gated by the
``path_public`` flag on folders (Pro only).
"""

import secrets
import string

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


def _generate_key(length=6):
    """Generate a short random alphanumeric key."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Folder(models.Model):
    """A directory in a user's drive.  Folders nest via ``parent``."""

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="folders"
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.CASCADE, related_name="children",
    )
    password_hash = models.CharField(
        max_length=256, blank=True, default="",
        help_text="PBKDF2 hash.  Empty = no password.",
    )
    path_public = models.BooleanField(
        default=False,
        help_text="Pro only.  When True, non-owners can browse via /@user/path/.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "parent", "slug"],
                name="unique_folder_slug_per_parent",
            ),
        ]

    def __str__(self):
        return self.full_path

    @property
    def full_path(self):
        """Build the drive path: /folder/sub/."""
        parts = []
        node = self
        while node is not None:
            parts.append(node.slug)
            node = node.parent
        return "/" + "/".join(reversed(parts)) + "/"

    @property
    def is_password_protected(self):
        return bool(self.password_hash)

    def nearest_password_ancestor(self):
        """Walk up from self to root.  Return the first folder (including self)
        that has a password set, or None if the chain is unprotected."""
        node = self
        while node is not None:
            if node.password_hash:
                return node
            node = node.parent
        return None

    def path_access_allowed(self):
        """Walk up to root — path access is allowed if this folder or any
        ancestor has ``path_public=True`` (children inherit)."""
        node = self
        while node is not None:
            if node.path_public:
                return True
            node = node.parent
        return False


class File(models.Model):
    """An uploaded file.  Content lives in B2; metadata lives here."""

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="files"
    )
    folder = models.ForeignKey(
        Folder, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="files",
    )
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, default="application/octet-stream")
    filesize = models.BigIntegerField(default=0)
    b2_key = models.CharField(
        max_length=512,
        help_text="Object key in B2: {uuid}/{filename}",
    )
    encrypted = models.BooleanField(
        default=False,
        help_text="True if client-side AES encrypted before upload.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["folder", "filename"],
                condition=models.Q(folder__isnull=False),
                name="unique_filename_per_folder",
            ),
        ]

    def __str__(self):
        return self.filename


class Key(models.Model):
    """A public identifier for a file.  Keys expire, not files."""

    key = models.CharField(max_length=64, unique=True, db_index=True)
    file = models.ForeignKey(
        File, on_delete=models.CASCADE, related_name="keys"
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    burn = models.BooleanField(
        default=False,
        help_text="Invalidate after first view.",
    )
    burned = models.BooleanField(default=False)
    password_hash = models.CharField(
        max_length=256, blank=True, default="",
        help_text="PBKDF2 hash.  Empty = no password.",
    )
    publish = models.BooleanField(
        default=False,
        help_text="Listed on /explore/ and owner profile.",
    )
    tags = models.JSONField(default=list, blank=True)
    custom = models.BooleanField(
        default=False,
        help_text="True if the user chose this key (not randomly generated).",
    )
    like_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.key

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return timezone.now() >= self.expires_at

    @property
    def is_burned(self):
        return self.burn and self.burned

    @property
    def is_valid(self):
        """Key is usable: not expired and not burned."""
        return not self.is_expired and not self.is_burned

    @property
    def is_password_protected(self):
        return bool(self.password_hash)

    def mark_burned(self):
        """Mark as burned after first view.  No-op if not a burn key."""
        if self.burn and not self.burned:
            self.burned = True
            self.save(update_fields=["burned"])

    # ── Proxy properties (templates use drop.filename etc.) ───────────
    @property
    def filename(self):
        return self.file.filename

    @property
    def content_type(self):
        return self.file.content_type

    @property
    def filesize(self):
        return self.file.filesize

    @property
    def owner(self):
        return self.file.owner

    @property
    def encrypted(self):
        return self.file.encrypted


class Like(models.Model):
    """One like per user per key.  Tracked by IP for anonymous sessions."""

    key = models.ForeignKey(Key, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.CASCADE, related_name="likes",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["key", "user"],
                condition=models.Q(user__isnull=False),
                name="one_like_per_user",
            ),
            models.UniqueConstraint(
                fields=["key", "ip"],
                condition=models.Q(user__isnull=True),
                name="one_like_per_ip",
            ),
        ]

    def __str__(self):
        return f"Like on {self.key_id} by {self.user or self.ip}"


class Bookmark(models.Model):
    """User-saved keys for quick access."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="bookmarks"
    )
    key = models.ForeignKey(Key, on_delete=models.CASCADE, related_name="bookmarks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key"],
                name="one_bookmark_per_user_key",
            ),
        ]

    def __str__(self):
        return f"Bookmark: {self.user} → {self.key}"
