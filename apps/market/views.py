from django import forms
from django.contrib import messages
from django.db.models import Count, Max, Min, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import approved_required
from apps.core.models import PlatformSettings
from apps.core.widgets import MoneyInput
from apps.investments.models import Holding
from apps.projects.models import Project

from .models import Listing, Trade
from .services import MarketError, buy, cancel_listing, create_listing, price_bounds, quote


class SellForm(forms.Form):
    shares = forms.IntegerField(label=gettext_lazy("Parts à vendre"), min_value=1)
    price = forms.DecimalField(label=gettext_lazy("Prix par part (MRU)"), min_value=1, widget=MoneyInput())
    allow_partial = forms.BooleanField(label=gettext_lazy("Accepter la vente d'une partie du lot"), required=False,
                                       initial=True)
    note = forms.CharField(label=gettext_lazy("Message (facultatif)"), max_length=200, required=False)


def index(request):
    """Board of active offers grouped by project, with price statistics."""
    projects = (Project.objects.filter(status=Project.Status.ACTIVE, trading_enabled=True)
                .annotate(offers=Count("listings", filter=Q(listings__status="active")),
                          best=Min("listings__price_per_share", filter=Q(listings__status="active")),
                          available=Sum("listings__remaining", filter=Q(listings__status="active")),
                          volume=Sum("trades__shares"), last_trade=Max("trades__created_at"))
                .select_related("sector", "wilaya").order_by("-offers", "-last_trade"))
    project_slug = request.GET.get("project")
    listings = Listing.objects.filter(status="active").select_related("project", "seller")
    selected = None
    if project_slug:
        selected = get_object_or_404(Project, slug=project_slug)
        listings = listings.filter(project=selected)
    return render(request, "market/index.html", {
        "projects": projects, "listings": listings[:100], "selected": selected,
        "recent": Trade.objects.select_related("project")[:12], "settings": PlatformSettings.get()})


@approved_required
def sell(request, slug):
    project = get_object_or_404(Project, slug=slug)
    holding = Holding.objects.filter(user=request.user, project=project).first()
    if not holding or holding.free_shares <= 0:
        messages.error(request, _("Vous n'avez pas de parts disponibles dans ce projet."))
        return redirect("core:portfolio")
    low, high = price_bounds(project)
    form = SellForm(request.POST or None, initial={"shares": holding.free_shares, "price": project.share_price})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            create_listing(request.user, project, d["shares"], d["price"], d["allow_partial"], d["note"])
            messages.success(request, _("Annonce publiée sur le marché."))
            return redirect("market:mine")
        except MarketError as e:
            form.add_error(None, str(e))
    return render(request, "market/sell.html", {
        "project": project, "holding": holding, "form": form, "low": low, "high": high,
        "settings": PlatformSettings.get(), "last_price": project.last_trade_price})


@approved_required
def buy_view(request, pk):
    listing = get_object_or_404(Listing.objects.select_related("project", "seller"), pk=pk)
    try:
        shares = int(request.POST.get("shares") or request.GET.get("shares") or listing.remaining)
    except ValueError:
        shares = listing.remaining
    shares = max(1, min(shares, listing.remaining or 1))
    q = quote(listing, shares)
    if request.method == "POST" and request.POST.get("confirm"):
        try:
            trade = buy(request.user, listing, shares)
            messages.success(request, _("Achat réalisé : %(n)s part(s) de « %(p)s ».") % {
                "n": trade.shares, "p": listing.project.title})
            return redirect("core:portfolio")
        except MarketError as e:
            messages.error(request, str(e))
    return render(request, "market/buy.html", {"listing": listing, "shares": shares, "q": q,
                                               "wallet": request.user.wallet})


@require_POST
@approved_required
def cancel(request, pk):
    listing = get_object_or_404(Listing, pk=pk, seller=request.user)
    try:
        cancel_listing(listing, user=request.user)
        messages.success(request, _("Annonce retirée."))
    except MarketError as e:
        messages.error(request, str(e))
    return redirect("market:mine")


@approved_required
def mine(request):
    return render(request, "market/mine.html", {
        "listings": Listing.objects.filter(seller=request.user).select_related("project")[:100],
        "buys": Trade.objects.filter(buyer=request.user).select_related("project")[:50],
        "sells": Trade.objects.filter(seller=request.user).select_related("project")[:50],
    })
