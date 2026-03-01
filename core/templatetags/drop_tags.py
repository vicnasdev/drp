"""
Template tags used in drop/explore templates.
Stubs — implement as features are built.
"""

from django import template

register = template.Library()


@register.filter
def filesizeformat_mb(value):
    """Format bytes as MB."""
    try:
        return f"{value / (1024 * 1024):.1f} MB"
    except (TypeError, ValueError, ZeroDivisionError):
        return value


@register.filter
def humanize_expiry(value):
    """Human-friendly remaining time."""
    from django.utils import timezone

    if not value:
        return "never"
    delta = value - timezone.now()
    if delta.total_seconds() < 0:
        return "expired"
    days = delta.days
    if days >= 365:
        return f"{days // 365}y"
    if days >= 1:
        return f"{days}d"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours}h"
    return f"{delta.seconds // 60}m"


@register.filter
def tag_color(tag):
    """Deterministic colour class for a tag."""
    colors = ["blue", "green", "orange", "purple", "red", "teal"]
    return colors[hash(tag) % len(colors)]


@register.filter
def split(value, delimiter=","):
    """Split a string by delimiter.  If already a list, return as-is."""
    if isinstance(value, list):
        return value
    try:
        return [x.strip() for x in value.split(delimiter)]
    except (AttributeError, TypeError):
        return []


@register.filter
def is_saved_by(drop, user):
    """Check if a drop/key is bookmarked by the user."""
    if not user or not user.is_authenticated:
        return False
    try:
        from drive.models import Bookmark
        key_obj = drop if hasattr(drop, "key") else None
        if key_obj is None:
            return False
        return Bookmark.objects.filter(user=user, key=key_obj).exists()
    except Exception:
        return False
