"""
core/templatetags/drop_tags.py

Custom template filters for drop-related logic.
"""

from django import template
from core.models import Folder, FolderItem

register = template.Library()


@register.filter
def split(value, sep=','):
    """Split a string by separator. Usage: {{ value|split:',' }}"""
    if not value:
        return []
    return [item.strip() for item in value.split(sep) if item.strip()]


@register.filter
def is_saved_by(drop, user):
    """
    Usage: {% if drop|is_saved_by:user %}

    Returns True if the given user has saved this drop to their root folder.
    """
    if not user or not user.is_authenticated:
        return False
    root = Folder.objects.filter(owner=user, parent=None, slug="drops").first()
    if not root:
        return False
    return FolderItem.objects.filter(folder=root, key=drop.key).exists()