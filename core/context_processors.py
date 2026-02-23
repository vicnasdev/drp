"""
Template context processors for drp.
"""

from django.conf import settings


def ads(request):
    """
    Injects ad config into every template.

    Set ADSENSE_CLIENT=ca-pub-xxxxxxxxxxxxxxxx in env to enable AdSense.
    Optionally set ADSENSE_SLOT=xxxxxxxxxx for a specific ad unit.
    When unset, the slot.html template falls back to the Railway referral.
    """
    return {
        'adsense_client': getattr(settings, 'ADSENSE_CLIENT', ''),
        'adsense_slot':   getattr(settings, 'ADSENSE_SLOT', ''),
    }


def domain(request):
    """Expose settings.DOMAIN to every template."""
    return {'domain': getattr(settings, 'DOMAIN', '') or 'localhost'}


def helpbot(request):
    """Tell templates whether the Gemini-powered help bot is available."""
    return {'gemini_enabled': bool(getattr(settings, 'GEMINI_API_KEY', ''))}