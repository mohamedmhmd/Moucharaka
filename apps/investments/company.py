"""Companies (existing or being created): a simple share model.

- The owner puts N parts on sale at a fixed price. Whoever buys becomes a
  shareholder at once and for good; the money goes straight to the owner
  (minus the success fee). Unsold parts stay on sale until bought or until the
  owner stops the sale.
- Dividends: the owner chooses an amount, each shareholder receives it in
  proportion to their parts.
- Buyback: the owner offers a shareholder to buy N parts at a price; each side
  can accept, refuse or answer with other numbers. The owner can also buy parts
  listed on the market. Bought-back parts are cancelled.
"""
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import PlatformSettings
from apps.core.utils import N_, audit, notify, pct, q2
from apps.projects.models import Project
from apps.trust.services import record_event
from apps.wallet.models import Transaction, Wallet, new_reference
from apps.wallet.services import WalletError, collect_fee, post

from .models import BuybackOffer, Distribution, Holding, Investment, Payout, ShareIssue
from .services import InvestmentError, _distribute, _refresh_counters, complete_project, fmt, max_shares_for

ZERO = Decimal("0")


def outstanding_shares(project):
    return sum(Holding.objects.filter(project=project, shares__gt=0).values_list("shares", flat=True))


# ------------------------------------------------------------------ buying parts on sale


@transaction.atomic
def buy_issued_shares(user, project, shares, risk_acknowledged=False):
    project = Project.objects.select_for_update().get(pk=project.pk)
    shares = int(shares)
    if not user.is_approved:
        raise InvestmentError(_("Votre compte doit être vérifié pour investir."))
    if not project.is_share_offering:
        raise InvestmentError(_("Il n'y a plus de parts en vente pour cette entreprise."))
    if project.owner_id == user.pk:
        raise InvestmentError(_("Vous ne pouvez pas investir dans votre propre projet."))
    if not risk_acknowledged:
        raise InvestmentError(_("Vous devez confirmer avoir compris les risques."))
    if shares < 1:
        raise InvestmentError(_("Minimum %(n)s part(s).") % {"n": 1})
    limit = max_shares_for(user, project)
    if shares > limit:
        raise InvestmentError(_("Vous pouvez souscrire au maximum %(n)s part(s) dans ce projet.") % {"n": limit})
    amount = q2(shares * project.share_price)
    fee = pct(amount, project.success_fee_pct)
    ref = new_reference("ACT")
    try:
        post(Wallet.for_user(user), Transaction.Kind.SHARE_PURCHASE, -amount, project=project, reference=ref,
             description=project.title)
    except WalletError as e:
        raise InvestmentError(str(e)) from e
    owner_wallet = Wallet.for_user(project.owner)
    post(owner_wallet, Transaction.Kind.SHARE_ISSUE, amount, project=project, reference=ref, description=project.title)
    if fee:
        post(owner_wallet, Transaction.Kind.SUCCESS_FEE, -fee, project=project, reference=ref)
        collect_fee(Transaction.Kind.SUCCESS_FEE, fee, description=project.title, project=project, reference=ref)
    inv = Investment.objects.create(investor=user, project=project, shares=shares, amount=amount, reference=ref,
                                    risk_acknowledged=True, status=Investment.Status.SETTLED,
                                    settled_at=timezone.now())
    h, _c = Holding.objects.select_for_update().get_or_create(user=user, project=project)
    h.shares += shares
    h.cost_basis += amount
    h.save()
    _refresh_counters(project)
    audit("shares.bought", inv, actor=user, shares=shares, amount=str(amount))
    notify(project.owner, N_("Nouvel actionnaire"),
           N_("%(n)s part(s) achetée(s) dans « %(p)s » : %(a)s MRU dans votre portefeuille.") % {
               "n": shares, "p": project.title, "a": fmt(amount - fee)}, url="/wallet/")
    if project.shares_available == 0:
        project.offering_open = False
        project.save(update_fields=["offering_open", "updated_at"])
        record_event(project.owner, "campaign_funded", project=project)
        notify(project.owner, N_("Toutes vos parts sont vendues"), project.title,
               url=project.get_absolute_url(), whatsapp=True)
    return inv


@transaction.atomic
def close_offering(project, user):
    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.owner_id != user.pk or not project.is_company:
        raise InvestmentError(_("Action impossible pour ce projet."))
    project.offering_open = False
    # Unsold parts are cancelled: they never existed for anyone
    project.shares_issued = project.shares_sold
    project.target_amount = project.raised_amount
    project.save(update_fields=["offering_open", "shares_issued", "target_amount", "updated_at"])
    audit("shares.offering_closed", project, actor=user)
    if outstanding_shares(project) == 0 and project.shares_sold:
        complete_project(project)
    return project


# ------------------------------------------------------------------ new parts (same project page, same shareholders)


@transaction.atomic
def request_issue(project, user, shares, price, reason=""):
    from apps.accounts.models import User

    project = Project.objects.select_for_update().get(pk=project.pk)
    shares, price = int(shares), q2(price)
    if project.owner_id != user.pk or not project.is_company or project.status != Project.Status.ACTIVE:
        raise InvestmentError(_("Impossible d'émettre des parts pour ce projet."))
    if project.is_share_offering:
        raise InvestmentError(_("Des parts sont encore en vente : attendez qu'elles soient vendues ou arrêtez la vente."))
    if project.share_issues.filter(status=ShareIssue.Status.PENDING).exists():
        raise InvestmentError(_("Une demande d'émission est déjà en attente de validation."))
    if shares < 1 or price < 1 or price != int(price):
        raise InvestmentError(_("Indiquez un nombre de parts et un prix entier."))
    issue = ShareIssue.objects.create(project=project, shares=shares, price=price, reason=reason.strip()[:2000])
    audit("shares.issue_requested", issue, actor=user, shares=shares, price=str(price))
    from apps.core.staff_tasks import notify_staff

    notify_staff(N_("Émission de parts à valider"),
                 N_("« %(p)s » : %(n)s nouvelles parts à %(x)s MRU.") % {"p": project.title, "n": shares, "x": fmt(price)},
                 url="/staff/issues/", task=f"issue:{issue.pk}")
    return issue


@transaction.atomic
def cancel_issue(issue, user):
    issue = ShareIssue.objects.select_for_update().select_related("project").get(pk=issue.pk)
    if issue.project.owner_id != user.pk or issue.status != ShareIssue.Status.PENDING:
        raise InvestmentError(_("Cette demande ne peut plus être annulée."))
    issue.status, issue.decided_at = ShareIssue.Status.CANCELLED, timezone.now()
    issue.save(update_fields=["status", "decided_at"])
    return issue


@transaction.atomic
def reject_issue(issue, by, reason):
    issue = ShareIssue.objects.select_for_update().select_related("project__owner").get(pk=issue.pk)
    if issue.status != ShareIssue.Status.PENDING:
        raise InvestmentError(_("Cette demande a déjà été traitée."))
    issue.status, issue.staff_reason, issue.decided_by, issue.decided_at = (
        ShareIssue.Status.REJECTED, reason[:255], by, timezone.now())
    issue.save()
    notify(issue.project.owner, N_("Émission de parts refusée"), reason,
           url=f"/projects/{issue.project.slug}/manage/#issue", whatsapp=True)
    audit("shares.issue_rejected", issue, actor=by, reason=reason)
    return issue


@transaction.atomic
def approve_issue(issue, by):
    """New parts go on sale on the same project page at the new price."""
    from apps.projects.sharing import notify_interested

    issue = ShareIssue.objects.select_for_update().get(pk=issue.pk)
    if issue.status != ShareIssue.Status.PENDING:
        raise InvestmentError(_("Cette demande a déjà été traitée."))
    project = Project.objects.select_for_update().get(pk=issue.project_id)
    if project.status != Project.Status.ACTIVE or project.is_share_offering:
        raise InvestmentError(_("Le projet n'est pas en état de vendre de nouvelles parts."))
    before = outstanding_shares(project)
    project.shares_issued = project.shares_sold + issue.shares
    project.share_price = issue.price
    project.target_amount = project.raised_amount + issue.total
    project.offering_open = True
    project.save(update_fields=["shares_issued", "share_price", "target_amount", "offering_open", "updated_at"])
    issue.status, issue.decided_by, issue.decided_at = ShareIssue.Status.APPROVED, by, timezone.now()
    issue.save()
    after = before + issue.shares
    for h in Holding.objects.filter(project=project, shares__gt=0).select_related("user"):
        notify(h.user, N_("Nouvelles parts émises"),
               N_("« %(p)s » met en vente %(n)s nouvelles parts à %(x)s MRU. Vos %(m)s parts représentent %(a)s %% "
                  "aujourd'hui et %(b)s %% quand toutes les nouvelles parts seront vendues. Vous pouvez en acheter.") % {
                   "p": project.title, "n": issue.shares, "x": fmt(issue.price), "m": h.shares,
                   "a": f"{h.shares * 100 / before:.1f}" if before else "0", "b": f"{h.shares * 100 / after:.1f}"},
               url=project.get_absolute_url(), whatsapp=True)
    notify(project.owner, N_("Nouvelles parts en vente"),
           N_("%(n)s nouvelles parts de « %(p)s » sont en vente à %(x)s MRU.") % {
               "n": issue.shares, "p": project.title, "x": fmt(issue.price)},
           url=project.get_absolute_url(), whatsapp=True)
    notify_interested(project)
    audit("shares.issue_approved", issue, actor=by)
    return issue


# ------------------------------------------------------------------ dividends


def dividend_preview(project, amount):
    amount = q2(amount or 0)
    n = outstanding_shares(project)
    fee = pct(amount, project.management_fee_pct)
    net = amount - fee
    per_share = (net / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if n else ZERO
    return {"amount": amount, "fee": fee, "net": net, "shares": n, "per_share": per_share}


@transaction.atomic
def pay_dividend(project, user, amount, note=""):
    project = Project.objects.select_for_update().get(pk=project.pk)
    amount = q2(amount)
    if project.owner_id != user.pk or not project.is_company or project.status != Project.Status.ACTIVE:
        raise InvestmentError(_("Ce projet ne peut pas verser de dividende."))
    if amount <= 0:
        raise InvestmentError(_("Indiquez le montant du dividende."))
    dist = _distribute(project, Distribution.Kind.DIVIDEND, amount, amount, Transaction.Kind.DIVIDEND_OUT,
                       Transaction.Kind.DIVIDEND_IN, note=note.strip())
    return dist


# ------------------------------------------------------------------ buyback offers


def _hold(project, amount, ref):
    try:
        post(Wallet.for_user(project.owner), Transaction.Kind.BUYBACK_HOLD, -amount, held_delta=amount,
             project=project, reference=ref, description=project.title)
    except WalletError as e:
        raise InvestmentError(str(e)) from e


def _release(offer):
    if offer.held_amount:
        post(Wallet.for_user(offer.project.owner), Transaction.Kind.BUYBACK_RELEASE, offer.held_amount,
             held_delta=-offer.held_amount, project=offer.project, reference=offer.reference,
             description=offer.project.title)
        offer.held_amount = ZERO


def _check_terms(project, holder, shares, price):
    shares, price = int(shares), q2(price)
    if shares <= 0 or price <= 0:
        raise InvestmentError(_("Indiquez un nombre de parts et un prix."))
    h = Holding.objects.filter(user=holder, project=project).first()
    owned = h.free_shares if h else 0
    if shares > owned:
        raise InvestmentError(_("Cet actionnaire n'a que %(n)s part(s) disponibles.") % {"n": owned})
    return shares, price


@transaction.atomic
def propose_buyback(project, owner, holder, shares, price, message=""):
    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.owner_id != owner.pk or not project.is_company or project.status != Project.Status.ACTIVE:
        raise InvestmentError(_("Rachat impossible pour ce projet."))
    if BuybackOffer.objects.filter(project=project, holder=holder, status=BuybackOffer.Status.PENDING).exists():
        raise InvestmentError(_("Une offre est déjà en discussion avec cet actionnaire."))
    shares, price = _check_terms(project, holder, shares, price)
    ref = new_reference("RAC")
    total = q2(shares * price)
    _hold(project, total, ref)
    offer = BuybackOffer.objects.create(project=project, holder=holder, shares=shares, price=price,
                                        message=message[:255], held_amount=total, reference=ref,
                                        waiting_on=BuybackOffer.HOLDER)
    audit("buyback.proposed", offer, actor=owner, shares=shares, price=str(price))
    notify(holder, N_("Offre de rachat de vos parts"),
           N_("« %(p)s » propose de racheter %(n)s part(s) à %(x)s MRU l'une.") % {
               "p": project.title, "n": shares, "x": fmt(price)}, url="/portfolio/#offers", whatsapp=True)
    return offer


def _side(offer, user):
    if user.pk == offer.project.owner_id:
        return BuybackOffer.OWNER
    if user.pk == offer.holder_id:
        return BuybackOffer.HOLDER
    raise InvestmentError(_("Cette offre ne vous concerne pas."))


@transaction.atomic
def answer_buyback(offer, user, action, shares=None, price=None, message=""):
    """action: accept | counter (with shares and price) | refuse (also withdraws your own offer)."""
    offer = BuybackOffer.objects.select_for_update().select_related("project__owner", "holder").get(pk=offer.pk)
    if offer.status != BuybackOffer.Status.PENDING:
        raise InvestmentError(_("Cette offre est déjà close."))
    side = _side(offer, user)
    project = offer.project
    if action == "refuse":
        _release(offer)
        offer.status = BuybackOffer.Status.REFUSED if side == offer.waiting_on else BuybackOffer.Status.CANCELLED
        offer.save()
        other = offer.holder if side == BuybackOffer.OWNER else project.owner
        url = "/portfolio/#offers" if side == BuybackOffer.OWNER else f"/projects/{project.slug}/manage/#buyback"
        notify(other, N_("Offre de rachat close"), project.title, url=url)
        audit("buyback.closed", offer, actor=user, status=offer.status)
        return offer
    if side != offer.waiting_on:
        raise InvestmentError(_("C'est à l'autre partie de répondre."))
    if action == "accept":
        return _execute(offer, user)
    if action != "counter":
        raise InvestmentError(_("Action inconnue."))
    shares, price = _check_terms(project, offer.holder, shares, price)
    _release(offer)
    offer.shares, offer.price, offer.message = shares, price, (message or "")[:255]
    offer.rounds += 1
    if side == BuybackOffer.OWNER:  # the owner answers: their money is set aside again
        _hold(project, q2(shares * price), offer.reference)
        offer.held_amount = q2(shares * price)
        offer.waiting_on = BuybackOffer.HOLDER
        notify(offer.holder, N_("Nouvelle offre de rachat"),
               N_("« %(p)s » propose %(n)s part(s) à %(x)s MRU l'une.") % {
                   "p": project.title, "n": shares, "x": fmt(price)}, url="/portfolio/#offers", whatsapp=True)
    else:
        offer.waiting_on = BuybackOffer.OWNER
        notify(project.owner, N_("Contre-proposition d'un actionnaire"),
               N_("%(u)s propose %(n)s part(s) à %(x)s MRU l'une.") % {
                   "u": offer.holder.display_name, "n": shares, "x": fmt(price)},
               url=f"/projects/{project.slug}/manage/#buyback", whatsapp=True)
    offer.save()
    audit("buyback.countered", offer, actor=user, shares=shares, price=str(price))
    return offer


def _retire(project, seller, shares, gross, seller_fee, ref, note):
    """Cancel `shares` parts of `seller` bought by the company; record it in their payouts."""
    h = Holding.objects.select_for_update().get(user=seller, project=project)
    h.cost_basis = q2(h.cost_basis * (h.shares - shares) / h.shares) if h.shares else ZERO
    h.shares -= shares
    h.received_total += gross - seller_fee
    h.save()
    dist = Distribution.objects.create(
        project=project, kind=Distribution.Kind.BUYBACK, gross_amount=gross, platform_fee=seller_fee,
        net_amount=gross - seller_fee, shares_outstanding=shares, shares_retired=shares, reference=ref, note=note,
        per_share=((gross - seller_fee) / shares).quantize(Decimal("0.0001"), rounding=ROUND_DOWN))
    Payout.objects.create(distribution=dist, user=seller, shares=shares, amount=gross - seller_fee)
    record_event(project.owner, "buyback", project=project)
    if outstanding_shares(project) == 0 and not project.is_share_offering:
        complete_project(project)
    return dist


def _execute(offer, user):
    project = Project.objects.select_for_update().get(pk=offer.project_id)
    h = Holding.objects.select_for_update().filter(user=offer.holder, project=project).first()
    if not h or h.free_shares < offer.shares:
        raise InvestmentError(_("L'actionnaire n'a plus assez de parts disponibles."))
    gross = q2(offer.shares * offer.price)
    seller_fee = pct(gross, PlatformSettings.get().trade_fee_seller_pct)
    owner_wallet = Wallet.for_user(project.owner)
    try:
        if offer.held_amount:  # money already set aside
            post(owner_wallet, Transaction.Kind.BUYBACK_OUT, 0, held_delta=-offer.held_amount, project=project,
                 reference=offer.reference, description=project.title)
        else:
            post(owner_wallet, Transaction.Kind.BUYBACK_OUT, -gross, project=project, reference=offer.reference,
                 description=project.title)
    except WalletError as e:
        raise InvestmentError(str(e)) from e
    holder_wallet = Wallet.for_user(offer.holder)
    post(holder_wallet, Transaction.Kind.BUYBACK_IN, gross, project=project, reference=offer.reference,
         description=project.title)
    if seller_fee:
        post(holder_wallet, Transaction.Kind.TRADE_FEE, -seller_fee, project=project, reference=offer.reference)
        collect_fee(Transaction.Kind.TRADE_FEE, seller_fee, description=project.title, project=project,
                    reference=offer.reference)
    offer.held_amount = ZERO
    offer.distribution = _retire(project, offer.holder, offer.shares, gross, seller_fee, offer.reference,
                                 _("Rachat de %(n)s part(s) à %(x)s MRU") % {"n": offer.shares, "x": fmt(offer.price)})
    offer.status = BuybackOffer.Status.ACCEPTED
    offer.save()
    for who, url in ((offer.holder, "/portfolio/"), (project.owner, f"/projects/{project.slug}/manage/#buyback")):
        notify(who, N_("Rachat conclu"),
               N_("%(n)s part(s) de « %(p)s » rachetée(s) à %(x)s MRU l'une.") % {
                   "n": offer.shares, "p": project.title, "x": fmt(offer.price)}, url=url, whatsapp=True)
    audit("buyback.accepted", offer, actor=user)
    return offer
