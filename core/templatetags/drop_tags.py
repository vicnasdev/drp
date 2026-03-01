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
