from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import PlatformSettings
from apps.core.utils import fmt_amount, N_, audit, notify, pct, q2
from apps.investments.models import Holding
from apps.projects.models import Project
from apps.wallet.models import Transaction, Wallet, new_reference
from apps.wallet.services import WalletError, collect_fee, post

from .models import Listing, Trade

MIN_PRICE_PCT = Decimal("10")  # a part cannot be listed below 10 % of nominal


class MarketError(Exception):
    pass


def price_bounds(project):
    s = PlatformSettings.get()
    low = q2(project.share_price * MIN_PRICE_PCT / 100)
    high = q2(project.share_price * (100 + s.max_listing_premium_pct) / 100)
    return low, high


@transaction.atomic
def create_listing(user, project, shares, price, allow_partial=True, note="", days=30):
    project = Project.objects.get(pk=project.pk)
    if not user.is_approved:
        raise MarketError(_("Votre compte doit être vérifié."))
    if not project.is_tradable:
        raise MarketError(_("Les parts de ce projet ne sont pas négociables actuellement."))
    shares, price = int(shares), q2(price)
    low, high = price_bounds(project)
    if not low <= price <= high:
        raise MarketError(_("Le prix doit être compris entre %(l)s et %(h)s MRU par part.") % {"l": low, "h": high})
    h = Holding.objects.select_for_update().filter(user=user, project=project).first()
    if not h or shares <= 0 or shares > h.free_shares:
        raise MarketError(_("Vous disposez de %(n)s part(s) disponibles à la vente.") % {"n": h.free_shares if h else 0})
    h.locked_shares += shares
    h.save(update_fields=["locked_shares", "updated_at"])
    listing = Listing.objects.create(seller=user, project=project, shares=shares, remaining=shares,
                                     price_per_share=price, allow_partial=allow_partial, note=note,
                                     expires_at=timezone.now() + timedelta(days=days))
    audit("market.listed", listing, actor=user, shares=shares, price=str(price))
    return listing


@transaction.atomic
def cancel_listing(listing, user=None, reason="", status=Listing.Status.CANCELLED):
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if user is not None and listing.seller_id != user.pk:
        raise MarketError(_("Cette annonce ne vous appartient pas."))
    if listing.status != Listing.Status.ACTIVE:
        return listing
    h = Holding.objects.select_for_update().get(user=listing.seller, project=listing.project)
    h.locked_shares = max(h.locked_shares - listing.remaining, 0)
    h.save(update_fields=["locked_shares", "updated_at"])
    listing.status = status
    listing.save(update_fields=["status"])
    if reason:
        notify(listing.seller, N_("Annonce retirée"), reason, url="/market/mine/")
    return listing


def cancel_project_listings(project, reason=""):
    for listing in Listing.objects.filter(project=project, status=Listing.Status.ACTIVE):
        cancel_listing(listing, reason=str(reason))


def quote(listing, shares):
    s = PlatformSettings.get()
    gross = q2(listing.price_per_share * shares)
    buyer_fee = pct(gross, s.trade_fee_buyer_pct)
    seller_fee = pct(gross, s.trade_fee_seller_pct)
    return {"gross": gross, "buyer_fee": buyer_fee, "seller_fee": seller_fee,
            "buyer_total": gross + buyer_fee, "seller_net": gross - seller_fee}


@transaction.atomic
def buy(buyer, listing, shares):
    listing = Listing.objects.select_for_update().select_related("project").get(pk=listing.pk)
    project = listing.project
    shares = int(shares)
    if not buyer.is_approved:
        raise MarketError(_("Votre compte doit être vérifié."))
    if listing.status != Listing.Status.ACTIVE or (listing.expires_at and listing.expires_at < timezone.now()):
        raise MarketError(_("Cette annonce n'est plus disponible."))
    if not project.is_tradable:
        raise MarketError(_("La négociation est suspendue sur ce projet."))
    if buyer.pk == listing.seller_id:
        raise MarketError(_("Vous ne pouvez pas acheter votre propre annonce."))
    company_buyback = buyer.pk == project.owner_id
    if company_buyback and not project.is_company:
        raise MarketError(_("Le porteur rachète ses parts via la procédure de rachat, pas sur le marché."))
    if shares <= 0 or shares > listing.remaining:
        raise MarketError(_("Quantité indisponible (max. %(n)s).") % {"n": listing.remaining})
    if not listing.allow_partial and shares != listing.remaining:
        raise MarketError(_("Le vendeur vend ce lot en entier uniquement."))
    q = quote(listing, shares)
    ref = new_reference("TRD")
    try:
        post(Wallet.for_user(buyer), Transaction.Kind.TRADE_BUY, -q["gross"], project=project, reference=ref,
             description=project.title)
        if q["buyer_fee"]:
            post(Wallet.for_user(buyer), Transaction.Kind.TRADE_FEE, -q["buyer_fee"], project=project, reference=ref)
    except WalletError as e:
        raise MarketError(str(e)) from e
    seller_wallet = Wallet.for_user(listing.seller)
    post(seller_wallet, Transaction.Kind.TRADE_SELL, q["gross"], project=project, reference=ref, description=project.title)
    if q["seller_fee"]:
        post(seller_wallet, Transaction.Kind.TRADE_FEE, -q["seller_fee"], project=project, reference=ref)
    collect_fee(Transaction.Kind.TRADE_FEE, q["buyer_fee"] + q["seller_fee"], description=project.title,
                project=project, reference=ref)
    # Move the parts
    sh = Holding.objects.select_for_update().get(user=listing.seller, project=project)
    sold_cost = q2(sh.cost_basis * shares / sh.shares) if sh.shares else Decimal("0")
    sh.shares -= shares
    sh.locked_shares -= shares
    sh.cost_basis -= sold_cost
    sh.save()
    if company_buyback:  # the company buys its own parts back: they are cancelled
        from apps.trust.services import record_event

        record_event(project.owner, "buyback", project=project)
        _close_if_no_shareholders(project)
    else:
        bh, _c = Holding.objects.select_for_update().get_or_create(user=buyer, project=project)
        bh.shares += shares
        bh.cost_basis += q["gross"] + q["buyer_fee"]
        bh.save()
    listing.remaining -= shares
    if listing.remaining == 0:
        listing.status = Listing.Status.SOLD
    listing.save(update_fields=["remaining", "status"])
    trade = Trade.objects.create(listing=listing, project=project, buyer=buyer, seller=listing.seller, shares=shares,
                                 price_per_share=listing.price_per_share, gross=q["gross"], buyer_fee=q["buyer_fee"],
                                 seller_fee=q["seller_fee"], reference=ref)
    audit("market.trade", trade, actor=buyer, shares=shares, price=str(listing.price_per_share))
    notify(listing.seller, N_("Parts vendues"),
           N_("%(n)s part(s) de « %(p)s » vendue(s), %(a)s MRU crédités.") % {
               "n": shares, "p": project.title, "a": fmt_amount(q['seller_net'])}, url="/wallet/")
    return trade


def _close_if_no_shareholders(project):
    """The company bought back every part: nothing left to share, the project is finished."""
    from apps.investments.services import complete_project

    if not Holding.objects.filter(project=project, shares__gt=0).exists():
        project.refresh_from_db()
        if not project.is_share_offering:
            complete_project(project)


def expire_listings():
    n = 0
    for listing in Listing.objects.filter(status=Listing.Status.ACTIVE, expires_at__lt=timezone.now()):
        cancel_listing(listing, status=Listing.Status.EXPIRED)
        n += 1
    return n
