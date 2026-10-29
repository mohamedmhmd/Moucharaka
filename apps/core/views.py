from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render

from apps.investments.models import Distribution, Holding, Investment, Payout
from apps.investments.services import can_cancel
from apps.projects.models import FeePolicy, Kind, Project
from apps.trust.services import get_score

from .models import PlatformSettings


def home(request):
    live = Project.objects.filter(status=Project.Status.FUNDING).select_related("sector", "wilaya", "moughataa")
    featured = list(live.order_by("-featured_until", "campaign_end")[:6])
    showcase = (Project.objects.filter(kind=Kind.BOUTIQUE, status__in=["funding", "active"], boutique__isnull=False)
                .select_related("boutique", "moughataa").order_by("-status", "-raised_amount").first())
    stats = {
        "raised": Project.objects.filter(status__in=["active", "completed", "funded"]).aggregate(
            s=Sum("raised_amount"))["s"] or 0,
        "distributed": Distribution.objects.aggregate(s=Sum("net_amount"))["s"] or 0,
        "projects": Project.objects.filter(status__in=["active", "completed", "funded"]).count(),
        "investors": Holding.objects.filter(shares__gt=0).values("user").distinct().count(),
    }
    flow = showcase.boutique.model() if showcase else None
    return render(request, "core/home.html", {"featured": featured, "showcase": showcase, "flow": flow, "stats": stats})


@login_required
def dashboard(request):
    u = request.user
    if u.status == u.Status.NEW and not hasattr(u, "kyc"):
        return redirect("accounts:kyc")
    ctx = {"notifications": u.notifications.all()[:8], "my_projects": u.projects.all()[:20]}
    if u.is_approved:
        holdings = Holding.objects.filter(user=u, shares__gt=0).select_related("project")
        ctx["wallet"] = u.wallet
        ctx["holdings_value"] = sum((h.nominal_value for h in holdings), Decimal("0"))
        ctx["received"] = Payout.objects.filter(user=u).aggregate(s=Sum("amount"))["s"] or 0
        ctx["held_investments"] = Investment.objects.filter(investor=u, status="held").select_related("project")
        ctx["recommended"] = (Project.objects.filter(status="funding").exclude(owner=u)
                              .exclude(investments__investor=u).order_by("campaign_end")[:3])
        ctx["score"] = get_score(u)
    return render(request, "core/dashboard.html", ctx)


@login_required
def portfolio(request):
    u = request.user
    holdings = list(Holding.objects.filter(user=u, shares__gt=0).select_related("project", "project__sector"))
    investments = list(Investment.objects.filter(investor=u).select_related("project")[:100])
    for inv in investments:
        inv.cancellable = can_cancel(inv)
    payouts = Payout.objects.filter(user=u).select_related("distribution__project")[:100]
    invested = sum((h.cost_basis for h in holdings), Decimal("0"))
    received = Payout.objects.filter(user=u).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    by_kind = {}
    for h in holdings:
        by_kind.setdefault(h.project.get_kind_display(), Decimal("0"))
        by_kind[h.project.get_kind_display()] += h.nominal_value
    return render(request, "core/portfolio.html", {
        "holdings": holdings, "investments": investments, "payouts": payouts, "invested": invested,
        "received": received, "market_value": sum((h.market_value for h in holdings), Decimal("0")),
        "by_kind": by_kind,
    })


@login_required
def notifications(request):
    qs = request.user.notifications.all()[:100]
    resp = render(request, "core/notifications.html", {"items": qs})
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return resp


def page(request, name):
    templates = {"how": "core/how.html", "fees": "core/fees.html", "sharia": "core/sharia.html",
                 "faq": "core/faq.html", "terms": "core/terms.html", "privacy": "core/privacy.html"}
    if name not in templates:
        from django.http import Http404

        raise Http404
    ctx = {"policies": FeePolicy.objects.all(), "settings": PlatformSettings.get()}
    return render(request, templates[name], ctx)
