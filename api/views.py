import json

import requests as http_requests
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from bot.models import Exchange


@require_GET
def ping(request):
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_POST
def helpbot(request):
    """
    POST /api/v1/helpbot/
    Body: {"question": "..."}
    Requires authenticated user (bearer token or session).
    Proxies to LLM_BASE_URL, stores exchange, returns answer.
    """
    if not request.user or not request.user.is_authenticated:
        return JsonResponse({"error": "auth required"}, status=401)

    if not settings.LLM_BASE_URL:
        return JsonResponse({"error": "helpbot not configured"}, status=503)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid json"}, status=400)

    question = body.get("question", "").strip()
    if not question:
        return JsonResponse({"error": "question required"}, status=400)

    # Build messages with history
    history = Exchange.history(request.user)
    messages = [
        {"role": "system", "content": "You are the drp help bot. Answer questions about drp concisely."},
        *history,
        {"role": "user", "content": question},
    ]

    model = settings.LLM_MODEL

    try:
        resp = http_requests.post(
            f"{settings.LLM_BASE_URL}/chat/completions",
            json={"model": model, "messages": messages},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
    except Exception as e:
        return JsonResponse({"error": f"llm error: {e}"}, status=502)

    Exchange.save_exchange(request.user, question, answer, model=model)

    return JsonResponse({"answer": answer})