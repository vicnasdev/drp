import hashlib
import hmac
import json
import urllib.request
import urllib.error

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.models import UserProfile, Plan

import logging
logger = logging.getLogger(__name__)

# ── Plan → Lemon Squeezy variant mapping ──────────────────────────────────────

PLAN_VARIANT_IDS = {
    Plan.STARTER: settings.LEMONSQUEEZY_STARTER_VARIANT_ID,
    Plan.PRO:     settings.LEMONSQUEEZY_PRO_VARIANT_ID,
}

# Reverse: variant ID → plan name
VARIANT_PLAN_MAP = {v: k for k, v in PLAN_VARIANT_IDS.items() if v}


# ── Checkout redirect ─────────────────────────────────────────────────────────

@login_required
def checkout(request, plan):
    """
    Redirect to the Lemon Squeezy hosted checkout for the chosen plan.
    Uses the current LS checkout URL format:
      https://store.lemonsqueezy.com/buy/<variant_id>?checkout[email]=...
    Email and user_id are prefilled so the webhook can locate the account.
    """
    variant_id = PLAN_VARIANT_IDS.get(plan)
    if not variant_id:
        return redirect("account")

    email   = request.user.email
    user_id = request.user.pk

    # LS checkout format as of 2024 — /buy/<variant_id> (not /checkout/buy/)
    url = (
        f"https://store.lemonsqueezy.com/buy/{variant_id}"
        f"?checkout[email]={email}"
        f"&checkout[custom][user_id]={user_id}"
    )
    return HttpResponseRedirect(url)


# ── Customer portal redirect ──────────────────────────────────────────────────

@login_required
def portal(request):
    """
    Redirect to the Lemon Squeezy customer portal for subscription management.
    Fetches the portal URL from the LS API using the stored customer ID.
    """
    profile = request.user.profile
    if not profile.ls_customer_id:
        return redirect("account")

    api_key     = settings.LEMONSQUEEZY_API_KEY
    customer_id = profile.ls_customer_id

    req = urllib.request.Request(
        f"https://api.lemonsqueezy.com/v1/customers/{customer_id}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept":        "application/vnd.api+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data       = json.loads(resp.read())
            portal_url = data["data"]["attributes"]["urls"]["customer_portal"]
            return HttpResponseRedirect(portal_url)
    except urllib.error.HTTPError as e:
        logger.warning("LS portal redirect failed for customer %s: HTTP %s", customer_id, e.code)
    except Exception as e:
        logger.warning("LS portal redirect failed for customer %s: %s", customer_id, e)

    return redirect("account")


# ── Webhook ───────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def webhook(request):
    """
    Receive and verify Lemon Squeezy webhook events, then update the user's plan.

    Signature verification: LS sends X-Signature as a hex HMAC-SHA256 of the
    raw body signed with LEMONSQUEEZY_SIGNING_SECRET.

    Events handled:
      subscription_created / subscription_updated  — activate or deactivate plan
      subscription_cancelled                        — mark cancelled (keeps plan until period ends)
      subscription_expired                          — downgrade to free
    """
    # ── Verify signature ──────────────────────────────────────────────────────
    secret    = settings.LEMONSQUEEZY_SIGNING_SECRET
    if not secret:
        logger.error("LS webhook: LEMONSQUEEZY_SIGNING_SECRET is not configured")
        return HttpResponse("Server misconfiguration", status=500)

    signature = request.headers.get("X-Signature", "")
    digest    = hmac.digest(secret.encode("utf-8"), request.body, hashlib.sha256).hex()

    if not hmac.compare_digest(digest, signature):
        logger.warning("LS webhook: invalid signature")
        return HttpResponse("Invalid signature", status=400)

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Bad JSON", status=400)

    meta    = payload.get("meta", {})
    # Event name comes from header (preferred) or meta fallback
    event   = request.headers.get("X-Event-Name", "") or meta.get("event_name", "")
    data    = payload.get("data", {})
    attrs   = data.get("attributes", {})

    user_id         = meta.get("custom_data", {}).get("user_id")
    customer_id     = str(attrs.get("customer_id", ""))
    subscription_id = str(data.get("id", ""))
    status          = attrs.get("status", "")
    variant_id      = str(attrs.get("variant_id", ""))

    logger.info("LS webhook: event=%s status=%s variant=%s user_id=%s", event, status, variant_id, user_id)

    # ── Locate the profile ────────────────────────────────────────────────────
    profile = None

    if user_id:
        profile = UserProfile.objects.filter(user_id=user_id).first()

    # Fallback: look up by customer ID (handles renewals where user_id may be absent)
    if not profile and customer_id:
        profile = UserProfile.objects.filter(ls_customer_id=customer_id).first()

    if not profile:
        # Return 200 so LS doesn't retry endlessly
        logger.warning("LS webhook: no profile found for user_id=%s customer_id=%s", user_id, customer_id)
        return HttpResponse("User not found", status=200)

    # ── Handle events ─────────────────────────────────────────────────────────

    if event in ("subscription_created", "subscription_updated"):
        plan = VARIANT_PLAN_MAP.get(variant_id, Plan.FREE)

        if status == "active":
            profile.plan       = plan
            profile.plan_since = timezone.now()
        elif status in ("cancelled", "expired", "unpaid", "paused", "past_due"):
            profile.plan       = Plan.FREE
            profile.plan_since = None

        profile.ls_customer_id         = customer_id
        profile.ls_subscription_id     = subscription_id
        profile.ls_subscription_status = status
        profile.save(update_fields=[
            "plan", "plan_since",
            "ls_customer_id", "ls_subscription_id", "ls_subscription_status",
        ])

    elif event == "subscription_cancelled":
        # Cancelled but still in billing period — keep plan active, just note it.
        # LS fires subscription_updated with status=expired when period actually ends.
        profile.ls_subscription_status = "cancelled"
        profile.save(update_fields=["ls_subscription_status"])

    elif event == "subscription_expired":
        profile.plan                   = Plan.FREE
        profile.plan_since             = None
        profile.ls_subscription_status = "expired"
        profile.save(update_fields=["plan", "plan_since", "ls_subscription_status"])

    elif event == "subscription_resumed":
        plan = VARIANT_PLAN_MAP.get(variant_id, Plan.FREE)
        profile.plan                   = plan
        profile.plan_since             = timezone.now()
        profile.ls_subscription_status = "active"
        profile.save(update_fields=["plan", "plan_since", "ls_subscription_status"])

    else:
        logger.info("LS webhook: unhandled event type '%s' — ignoring", event)

    return HttpResponse("OK", status=200)
