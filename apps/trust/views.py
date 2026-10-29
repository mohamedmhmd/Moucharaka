from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render

from apps.accounts.models import User
from apps.investments.models import Distribution
from apps.projects.models import Project

from .models import Review, TrustEvent
from .services import COMPONENT_MAX, get_score


def public_profile(request, public_id):
    """Public track record of a member: projects, payments, reviews, score."""
    user = get_object_or_404(User, public_id=public_id, is_active=True)
    score = get_score(user)
    projects = (Project.objects.filter(owner=user, status__in=Project.PUBLIC_STATUSES)
                .select_related("sector", "wilaya")
                .annotate(paid=Sum("distributions__net_amount", filter=Q(distributions__status="paid")),
                          n_dist=Count("distributions", distinct=True))
                .order_by("-campaign_start"))
    distributions = (Distribution.objects.filter(project__owner=user).select_related("project")
                     .order_by("-paid_at")[:50])
    on_time = sum(1 for d in distributions if d.on_time)
    reviews = Review.objects.filter(owner=user, is_hidden=False).select_related("project", "reviewer")[:30]
    events = TrustEvent.objects.filter(user=user, is_public=True).exclude(points=0).select_related("project")[:40]
    components = [
        {"key": k, "value": score.components.get(k, 0), "max": m, "pct": int(score.components.get(k, 0) * 100 / m)}
        for k, m in COMPONENT_MAX.items()
    ]
    totals = {
        "raised": sum((p.raised_amount for p in projects if p.status not in ("failed",)), 0),
        "distributed": sum((p.paid or 0 for p in projects), 0),
        "projects": len(projects),
        "on_time_pct": int(on_time * 100 / len(distributions)) if distributions else None,
    }
    return render(request, "trust/profile.html", {
        "member": user, "score": score, "components": components, "projects": projects,
        "distributions": distributions, "reviews": reviews, "events": events, "totals": totals,
        "kyc": getattr(user, "kyc", None),
    })


def score_method(request):
    return render(request, "trust/method.html", {"max": COMPONENT_MAX})
