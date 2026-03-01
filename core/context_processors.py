from django.conf import settings


def ads(request):
    return {
        "ADSENSE_CLIENT": getattr(settings, "ADSENSE_CLIENT", ""),
        "ADSENSE_SLOT": getattr(settings, "ADSENSE_SLOT", ""),
    }


def domain(request):
    return {
        "DOMAIN": getattr(settings, "DOMAIN", ""),
        "SITE_URL": getattr(settings, "SITE_URL", ""),
    }


def helpbot(request):
    return {
        "HELPBOT_ENABLED": bool(getattr(settings, "LLM_BASE_URL", "")),
    }
