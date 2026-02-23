"""Feature voting board — public listing, authenticated submission & voting."""
import json

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_http_methods

from core.models import FeatureProposal, FeatureVote, Plan


def _vote_weight(user):
    """Return vote weight: paid plans get 3, free gets 1."""
    if not user.is_authenticated:
        return 0
    try:
        plan = user.profile.plan
    except Exception:
        plan = Plan.FREE
    if plan in (Plan.STARTER, Plan.PRO):
        return 3
    return 1


def feature_list(request):
    """GET /features/ — list proposals sorted by vote score, staff picks first."""
    proposals = FeatureProposal.objects.filter(closed=False)

    # Annotate with total vote weight
    from django.db.models import Sum, Value, IntegerField
    from django.db.models.functions import Coalesce
    proposals = proposals.annotate(
        score=Coalesce(Sum("votes__weight"), Value(0), output_field=IntegerField())
    ).order_by("-staff_pick", "-score", "-created_at")

    if request.headers.get("Accept") == "application/json":
        data = []
        for p in proposals:
            data.append({
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "proposed_by": p.proposed_by.username if p.proposed_by else None,
                "staff_pick": p.staff_pick,
                "score": p.score,
                "created_at": p.created_at.isoformat(),
            })
        return JsonResponse({"proposals": data})

    # For template: attach user's vote status
    user_votes = set()
    if request.user.is_authenticated:
        user_votes = set(
            FeatureVote.objects.filter(user=request.user)
            .values_list("proposal_id", flat=True)
        )

    return render(request, "features.html", {
        "proposals": proposals,
        "user_votes": user_votes,
        "can_vote": request.user.is_authenticated,
    })


@require_http_methods(["POST"])
def feature_submit(request):
    """POST /features/submit/ — authenticated users submit a proposal."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login required"}, status=401)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        body = {}

    title = (body.get("title") or request.POST.get("title", "")).strip()
    description = (body.get("description") or request.POST.get("description", "")).strip()

    if not title:
        return JsonResponse({"error": "title is required"}, status=400)
    if len(title) > 200:
        return JsonResponse({"error": "title too long (200 chars max)"}, status=400)

    proposal = FeatureProposal.objects.create(
        title=title,
        description=description[:2000],
        proposed_by=request.user,
    )

    return JsonResponse({
        "id": proposal.id,
        "title": proposal.title,
        "description": proposal.description,
    }, status=201)


@require_http_methods(["POST"])
def feature_vote(request, proposal_id):
    """POST /features/<id>/vote/ — toggle vote on a proposal."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login required"}, status=401)

    proposal = get_object_or_404(FeatureProposal, id=proposal_id, closed=False)
    weight = _vote_weight(request.user)

    existing = FeatureVote.objects.filter(proposal=proposal, user=request.user).first()
    if existing:
        existing.delete()
        action = "removed"
    else:
        FeatureVote.objects.create(proposal=proposal, user=request.user, weight=weight)
        action = "voted"

    new_score = proposal.total_weight()
    return JsonResponse({"action": action, "score": new_score})
