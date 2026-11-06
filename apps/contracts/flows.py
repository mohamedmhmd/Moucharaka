"""One function per operation: gather the figures the contract states, then prepare it.
Views call these and send the person to the signing page."""
from decimal import Decimal

from apps.core.models import PlatformSettings
from apps.core.utils import pct, q2
from apps.investments.company import outstanding_shares
from apps.investments.models import Holding, Investment
from apps.investments.services import deal_split
from apps.market.services import quote
from apps.projects.models import FeePolicy

from .models import Contract, Signature
from .services import party, prepare

R = Signature.Role


def _common(project):
    policy = FeePolicy.for_project(project)
    return {
        "owner": party(project.owner, R.COMPANY if project.is_company else R.OWNER),
        "months": project.duration_months, "target": project.target_amount,
        "expected_pct": project.projected_annual_return_pct,
        # Before approval the project has no fees of its own yet: the fee grid applies
        "success_pct": policy.success_fee_pct if project.is_editable else project.success_fee_pct,
        "mgmt_pct": policy.management_fee_pct if project.is_editable else project.management_fee_pct,
    }


def start_invest(request, project, shares):
    shares = int(shares)
    amount = q2(shares * project.share_price)
    ctx = _common(project)
    ctx.update(shares=shares, price=project.share_price, amount=amount, campaign_end=project.campaign_end)
    if project.is_company:
        held = outstanding_shares(project)
        ctx.update(after_pct=round(shares * 100 / (held + shares), 2) if held + shares else 100,
                   issued=project.total_shares)
        kind = Contract.Kind.SHARE_PURCHASE
    else:
        kind = Contract.Kind.DEAL_INVESTMENT
    ctx["terms"] = {"shares": shares, "price": project.share_price, "amount": amount}
    ctx["parties"] = [party(request.user, R.INVESTOR), ctx["owner"]]
    return prepare(request, kind=kind, project=project, action="invest", role=R.INVESTOR,
                   payload={"project": project.pk, "shares": shares}, context=ctx, viewers=[project.owner])


def start_funding(request, project):
    investments = list(project.investments.filter(status__in=[Investment.Status.HELD, Investment.Status.SETTLED])
                       .select_related("investor").order_by("-amount"))
    raised = sum((i.amount for i in investments), Decimal("0"))
    ctx = _common(project)
    fee = pct(raised, project.success_fee_pct)
    ctx.update(investments=investments, raised=raised, fee=fee, net=raised - fee, investors_count=len(investments))
    ctx["terms"] = {"raised": raised, "fee": fee, "net": raised - fee, "investors": len(investments)}
    ctx["parties"] = [party(request.user, R.OWNER)]
    # the annex lists every investor and amount: owner and staff only
    return prepare(request, kind=Contract.Kind.FUNDING, project=project, action="accept_funding", role=R.OWNER,
                   payload={"project": project.pk}, context=ctx)


def start_share_issue(request, project, shares, price, reason="", new=False):
    shares, price = int(shares), q2(price)
    ctx = _common(project)
    ctx.update(shares=shares, price=price, total=q2(shares * price), reason=reason, new=new,
               existing=project.total_shares if new else 0)
    ctx["terms"] = {"shares": shares, "price": price, "new_issue": new}
    ctx["parties"] = [party(request.user, R.COMPANY)]
    if new:
        return prepare(request, kind=Contract.Kind.SHARE_ISSUE, project=project, action="request_issue",
                       role=R.COMPANY, payload={"project": project.pk, "shares": shares, "price": str(price),
                                                "reason": reason}, context=ctx)
    return prepare(request, kind=Contract.Kind.SHARE_ISSUE, project=project, action="submit_project",
                   role=R.COMPANY, payload={"project": project.pk}, context=ctx)


def start_listing(request, project, shares, price, allow_partial, note=""):
    s = PlatformSettings.get()
    shares, price = int(shares), q2(price)
    ctx = {"shares": shares, "price": price, "total": q2(shares * price), "allow_partial": allow_partial,
           "seller_fee_pct": s.trade_fee_seller_pct, "note": note,
           "parties": [party(request.user, R.SELLER)],
           "terms": {"shares": shares, "price": price, "allow_partial": allow_partial}}
    return prepare(request, kind=Contract.Kind.SALE_OFFER, project=project, action="create_listing", role=R.SELLER,
                   payload={"project": project.pk, "shares": shares, "price": str(price),
                            "allow_partial": bool(allow_partial), "note": note}, context=ctx)


def start_buy(request, listing, shares):
    project = listing.project
    shares = int(shares)
    q = quote(listing, shares)
    company_buyback = request.user.pk == project.owner_id and project.is_company
    role = R.COMPANY if company_buyback else R.BUYER
    parent = (Contract.objects.filter(kind=Contract.Kind.SALE_OFFER, object_ref=f"listing:{listing.pk}",
                                      status=Contract.Status.SIGNED).first())
    s = PlatformSettings.get()
    ctx = {"shares": shares, "price": listing.price_per_share, "q": q, "company_buyback": company_buyback,
           "buyer_fee_pct": s.trade_fee_buyer_pct, "seller_fee_pct": s.trade_fee_seller_pct,
           "listing_date": listing.created_at,
           "parties": [party(listing.seller, R.SELLER), party(request.user, role)],
           "terms": {"shares": shares, "price": listing.price_per_share, **q}}
    return prepare(request, kind=Contract.Kind.SHARE_TRANSFER, project=project, action="buy_listing", role=role,
                   payload={"listing": listing.pk, "shares": shares}, context=ctx, parent=parent,
                   viewers=[listing.seller])


def start_buyback_offer(request, project, holder, shares, price, message="", offer=None):
    """A new offer from the company, or a counter-proposal from either side."""
    shares, price = int(shares), q2(price)
    by_company = request.user.pk == project.owner_id
    role = R.COMPANY if by_company else R.SHAREHOLDER
    s = PlatformSettings.get()
    gross = q2(shares * price)
    seller_fee = pct(gross, s.trade_fee_seller_pct)
    ctx = {"shares": shares, "price": price, "total": gross, "seller_fee": seller_fee, "seller_net": gross - seller_fee,
           "seller_fee_pct": s.trade_fee_seller_pct, "by_company": by_company, "message": message,
           "counter": offer is not None, "held": Holding.objects.filter(user=holder, project=project).first(),
           "parties": [party(project.owner, R.COMPANY), party(holder, R.SHAREHOLDER)],
           "terms": {"shares": shares, "price": price, "total": gross}}
    if offer is None:
        action, payload = "propose_buyback", {"project": project.pk, "holder": holder.pk}
    else:
        action, payload = "counter_buyback", {"project": project.pk, "offer": offer.pk}
    payload.update(shares=shares, price=str(price), message=message)
    return prepare(request, kind=Contract.Kind.BUYBACK_OFFER, project=project, action=action, role=role,
                   payload=payload, context=ctx, viewers=[project.owner, holder])


def start_buyback_accept(request, offer):
    project = offer.project
    by_company = request.user.pk == project.owner_id
    role = R.COMPANY if by_company else R.SHAREHOLDER
    parent = (Contract.objects.filter(kind=Contract.Kind.BUYBACK_OFFER, object_ref=f"offer:{offer.pk}",
                                      status=Contract.Status.SIGNED).exclude(created_by=request.user)
              .order_by("-signed_at").first())
    s = PlatformSettings.get()
    gross = q2(offer.shares * offer.price)
    seller_fee = pct(gross, s.trade_fee_seller_pct)
    ctx = {"shares": offer.shares, "price": offer.price, "total": gross, "seller_fee": seller_fee,
           "seller_net": gross - seller_fee, "seller_fee_pct": s.trade_fee_seller_pct, "by_company": by_company,
           "parties": [party(project.owner, R.COMPANY), party(offer.holder, R.SHAREHOLDER)],
           "terms": {"shares": offer.shares, "price": offer.price, "total": gross}}
    return prepare(request, kind=Contract.Kind.BUYBACK, project=project, action="accept_buyback", role=role,
                   payload={"project": project.pk, "offer": offer.pk}, context=ctx, parent=parent,
                   viewers=[project.owner, offer.holder])


def start_settlement(request, project, amount, note=""):
    split = deal_split(project, amount)
    ctx = _common(project)
    ctx.update(split=split, note=note, parties=[party(request.user, R.OWNER)],
               terms={k: split[k] for k in ("amount", "capital", "gain", "loss", "fee", "net")})
    return prepare(request, kind=Contract.Kind.SETTLEMENT, project=project, action="settle", role=R.OWNER,
                   payload={"project": project.pk, "amount": str(q2(amount)), "note": note}, context=ctx)

