from django import template
from core.models import FileBookmark

register = template.Library()


@register.filter
def is_saved_by(drop, user):
    """{% if drop|is_saved_by:user %}"""
    if not user or not user.is_authenticated:
        return False
    return FileBookmark.objects.filter(user=user, file_key=drop.key).exists()
