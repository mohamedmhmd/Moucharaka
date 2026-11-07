from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import redirect, render

from apps.investments.models import BuybackOffer, Distribution, Holding, Investment, Payout
from apps.investments.services import can_cancel
from apps.projects.forms import BuybackOfferForm
from apps.projects.models import FeePolicy, Kind, Project
from apps.trust.services import get_score

from .models import PlatformSettings


# Open to new investors: a campaign in progress, or a company whose parts are still on sale
ON_SALE = Q(status="funding") | Q(kind="company", status="active", offering_open=True)

def home(request):
    live = Project.objects.filter(ON_SALE).select_related("sector", "wilaya", "moughataa")
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
    from apps.core.staff_tasks import annotate

    ctx = {"notifications": annotate(u.notifications.all()[:8]), "my_projects": u.projects.all()[:20]}
    if u.is_approved:
        holdings = Holding.objects.filter(user=u, shares__gt=0).select_related("project")
        ctx["wallet"] = u.wallet
        ctx["holdings_value"] = sum((h.nominal_value for h in holdings), Decimal("0"))
        ctx["received"] = Payout.objects.filter(user=u).aggregate(s=Sum("amount"))["s"] or 0
        ctx["held_investments"] = Investment.objects.filter(investor=u, status="held").select_related("project")
        ctx["recommended"] = (Project.objects.filter(ON_SALE).exclude(owner=u)
                              .exclude(investments__investor=u).order_by("campaign_end")[:3])
        ctx["score"] = get_score(u)
        ctx["followed"] = (Project.objects.filter(Q(favorited_by__user=u) | Q(interests__user=u))
                           .select_related("sector", "wilaya", "moughataa").distinct()[:6])
        ctx["no_accounts"] = not u.payment_accounts.filter(is_active=True).exists()
    return render(request, "core/dashboard.html", ctx)


@login_required
def portfolio(request):
    u = request.user
    holdings = list(Holding.objects.filter(user=u, shares__gt=0).select_related("project", "project__sector"))
    offers = list(BuybackOffer.objects.filter(holder=u, status="pending").select_related("project"))
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
        "by_kind": by_kind, "offers": offers,
        "offer_form": BuybackOfferForm(),
    })


@login_required
def notifications(request):
    from apps.core.staff_tasks import annotate

    qs = request.user.notifications.all()
    show = request.GET.get("show", "")
    items = annotate(qs[:300] if show == "todo" else qs[:100])
    if show == "todo":
        items = [n for n in items if n.task_state == "open"]
    resp = render(request, "core/notifications.html", {"items": items, "show": show,
                                                        "is_team": request.user.is_staff})
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return resp


def page(request, name):
    templates = {"how": "core/how.html", "fees": "core/fees.html", "sharia": "core/sharia.html",
                 "faq": "core/faq.html", "terms": "core/terms.html", "privacy": "core/privacy.html",
                 "contact": "core/contact.html"}
    if name not in templates:
        from django.http import Http404

        raise Http404
    ctx = {"policies": FeePolicy.objects.filter(is_enabled=True, financing_model="moucharaka"),
           "settings": PlatformSettings.get()}
    if name == "fees":
        from apps.wallet.models import PaymentMethod, WithdrawalFee

        grids = {}
        for r in WithdrawalFee.objects.all():
            grids.setdefault(r.method, []).append(r)
        ctx["withdrawal_grids"] = [(label, grids[m]) for m, label in PaymentMethod.choices if m in grids]
        ctx["withdrawal_general_for"] = [label for m, label in PaymentMethod.choices if m not in grids and m != "cash"]
    return render(request, templates[name], ctx)


def set_language(request):
    """Language switch (FR / ع button). Arabic pages have no prefix, French ones live under /fr/.

    Django's own view keeps /fr/... when going back to Arabic with these URLs, so the page stayed
    in French. Here the current path is stripped of its language prefix, the new prefix is added
    (none for Arabic), and the choice is remembered in the language cookie."""
    from django.conf import settings
    from django.http import HttpResponseNotAllowed
    from django.utils.http import url_has_allowed_host_and_scheme
    from django.utils.translation import check_for_language

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    lang = request.POST.get("language", "")
    nxt = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        nxt = "/"
    if not check_for_language(lang) or lang not in dict(settings.LANGUAGES):
        return redirect(nxt)
    # keep only the path part (a Referer is a full URL)
    from urllib.parse import urlsplit
    parts = urlsplit(nxt)
    path, query = parts.path or "/", parts.query
    for code, _name in settings.LANGUAGES:
        if path == f"/{code}" or path.startswith(f"/{code}/"):
            path = path[len(code) + 1:] or "/"
            break
    if lang != settings.LANGUAGE_CODE:
        path = f"/{lang}{path}"
    response = redirect(path + (f"?{query}" if query else ""))
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=settings.LANGUAGE_COOKIE_AGE,
                        path=settings.LANGUAGE_COOKIE_PATH, domain=settings.LANGUAGE_COOKIE_DOMAIN,
                        secure=settings.LANGUAGE_COOKIE_SECURE, httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
                        samesite=settings.LANGUAGE_COOKIE_SAMESITE)
    return response
