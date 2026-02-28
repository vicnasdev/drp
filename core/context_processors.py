from django.conf import settings


def ads(request):
    return {
        "adsense_client": getattr(settings, "ADSENSE_CLIENT", ""),
        "adsense_slot":   getattr(settings, "ADSENSE_SLOT", ""),
    }


def domain(request):
    return {
        "DOMAIN":   getattr(settings, "DOMAIN", ""),
        "SITE_URL": getattr(settings, "SITE_URL", ""),
    }


def helpbot(request):
    enabled = bool(getattr(settings, "LLM_BASE_URL", ""))
    return {"gemini_enabled": enabled}
