import calendar
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import PlatformSettings
from apps.core.utils import N_, audit, notify, pct, q2
from apps.projects.models import Installment, Project
from apps.trust.services import record_event
from apps.wallet.models import Transaction, Wallet, new_reference
from apps.wallet.services import WalletError, collect_fee, post

from .models import Distribution, Holding, Investment, Payout

ZERO = Decimal("0")
COOLING_OFF_HOURS = 48


class InvestmentError(Exception):
    pass


def add_months(d, months):
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def fmt(amount):
    return f"{amount:,.0f}".replace(",", " ")


# ------------------------------------------------------------------ subscription (escrow)

def max_shares_for(user, project):
    cap_pct = PlatformSettings.get().max_ticket_pct
    cap = int(project.total_shares * cap_pct / 100) or 1
    already = Investment.objects.filter(investor=user, project=project, status__in=["held", "settled"]).aggregate(
        s=Sum("shares"))["s"] or 0
    return max(min(cap - already, project.shares_available), 0)


@transaction.atomic
def invest(user, project, shares, risk_acknowledged=False):
    project = Project.objects.select_for_update().get(pk=project.pk)
    shares = int(shares)
    if not user.is_approved:
        raise InvestmentError(_("Votre compte doit être vérifié pour investir."))
    if project.status != Project.Status.FUNDING or (project.campaign_end and project.campaign_end < timezone.now()):
        raise InvestmentError(_("La collecte de ce projet n'est pas ouverte."))
    if project.owner_id == user.pk:
        raise InvestmentError(_("Vous ne pouvez pas investir dans votre propre projet."))
    if not risk_acknowledged:
        raise InvestmentError(_("Vous devez confirmer avoir compris les risques."))
    if shares < project.min_shares:
        raise InvestmentError(_("Minimum %(n)s part(s).") % {"n": project.min_shares})
    limit = max_shares_for(user, project)
    if shares > limit:
        raise InvestmentError(_("Vous pouvez souscrire au maximum %(n)s part(s) dans ce projet.") % {"n": limit})
    amount = q2(shares * project.share_price)
    ref = new_reference("INV")
    try:
        post(Wallet.for_user(user), Transaction.Kind.INVEST_HOLD, -amount, held_delta=amount,
             description=project.title, project=project, reference=ref)
    except WalletError as e:
        raise InvestmentError(str(e)) from e
    inv = Investment.objects.create(investor=user, project=project, shares=shares, amount=amount, reference=ref,
                                    risk_acknowledged=True)
    _refresh_counters(project)
    audit("investment.created", inv, actor=user, shares=shares, amount=str(amount))
    notify(project.owner, N_("Nouvel investissement"),
           N_("%(n)s part(s) souscrite(s) dans « %(p)s ».") % {"n": shares, "p": project.title},
           url=project.get_absolute_url())
    if project.shares_available == 0:
        mark_funded(project)
    return inv


def _refresh_counters(project):
    agg = Investment.objects.filter(project=project, status__in=["held", "settled"]).aggregate(
        s=Sum("shares"), a=Sum("amount"))
    project.shares_sold = agg["s"] or 0
    project.raised_amount = agg["a"] or ZERO
    project.investors_count = Investment.objects.filter(project=project, status__in=["held", "settled"]).values(
        "investor").distinct().count()
    project.save(update_fields=["shares_sold", "raised_amount", "investors_count", "updated_at"])


def can_cancel(inv):
    return (inv.status == Investment.Status.HELD and inv.project.status == Project.Status.FUNDING
            and timezone.now() - inv.created_at < timedelta(hours=COOLING_OFF_HOURS))


@transaction.atomic
def cancel_investment(inv, user):
    inv = Investment.objects.select_for_update().select_related("project").get(pk=inv.pk)
    if inv.investor_id != user.pk or not can_cancel(inv):
        raise InvestmentError(_("Le délai de rétractation de 48 h est dépassé."))
    post(Wallet.for_user(user), Transaction.Kind.INVEST_REFUND, inv.amount, held_delta=-inv.amount,
         project=inv.project, reference=inv.reference, description=_("Rétractation"))
    inv.status = Investment.Status.CANCELLED
    inv.save(update_fields=["status"])
    _refresh_counters(Project.objects.select_for_update().get(pk=inv.project_id))
    audit("investment.cancelled", inv, actor=user)
    return inv


def mark_funded(project):
    from apps.accounts.models import User

    project.status = Project.Status.FUNDED
    project.funded_at = timezone.now()
    project.save(update_fields=["status", "funded_at", "updated_at"])
    record_event(project.owner, "campaign_funded", project=project)
    notify(project.owner, N_("Objectif atteint !"),
           N_("« %(p)s » est financé. Notre équipe prépare le contrat et le versement des fonds.") % {"p": project.title},
           url=project.get_absolute_url(), sms=True)
    for staff in User.objects.filter(is_staff=True, is_active=True):
        notify(staff, N_("Projet financé : fonds à libérer"), project.title, url=f"/staff/projects/{project.pk}/")
    for inv in project.investments.filter(status="held").select_related("investor"):
        notify(inv.investor, N_("Projet financé"),
               N_("« %(p)s » a atteint son objectif.") % {"p": project.title}, url=project.get_absolute_url())


@transaction.atomic
def close_campaign(project):
    """Called when the deadline passes: funded if the threshold is met,
    otherwise every investor is refunded."""
    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.status != Project.Status.FUNDING or (project.campaign_end and project.campaign_end > timezone.now()):
        return project
    threshold = project.target_amount * project.min_funding_pct / 100
    if project.raised_amount > 0 and project.raised_amount >= threshold:
        mark_funded(project)
    else:
        refund_campaign(project)
    return project


@transaction.atomic
def refund_campaign(project, reason=""):
    for inv in project.investments.select_for_update().filter(status=Investment.Status.HELD):
        post(Wallet.for_user(inv.investor), Transaction.Kind.INVEST_REFUND, inv.amount, held_delta=-inv.amount,
             project=project, reference=inv.reference, description=project.title)
        inv.status = Investment.Status.REFUNDED
        inv.save(update_fields=["status"])
        notify(inv.investor, N_("Collecte non aboutie : vous êtes remboursé"),
               N_("%(a)s MRU sont de nouveau disponibles.") % {"a": fmt(inv.amount)}, url="/wallet/", sms=True)
    project.status = Project.Status.FAILED if not reason else Project.Status.CANCELLED
    project.closed_at = timezone.now()
    project.save(update_fields=["status", "closed_at", "updated_at"])
    if not reason:
        record_event(project.owner, "campaign_failed", project=project)
    audit("project.refunded", project, reason=reason)


@transaction.atomic
def release_funds(project, by=None):
    """Settle escrow: investors receive parts, owner receives the money net
    of the success fee, the repayment schedule is generated."""
    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.status != Project.Status.FUNDED:
        raise InvestmentError(_("Seul un projet financé peut recevoir les fonds."))
    total = ZERO
    for inv in project.investments.select_for_update().filter(status=Investment.Status.HELD).select_related("investor"):
        post(Wallet.for_user(inv.investor), Transaction.Kind.INVEST_SETTLE, 0, held_delta=-inv.amount,
             project=project, reference=inv.reference, description=project.title)
        h, _c = Holding.objects.select_for_update().get_or_create(user=inv.investor, project=project)
        h.shares += inv.shares
        h.cost_basis += inv.amount
        h.save()
        inv.status = Investment.Status.SETTLED
        inv.settled_at = timezone.now()
        inv.save(update_fields=["status", "settled_at"])
        total += inv.amount
    fee = pct(total, project.success_fee_pct)
    owner_wallet = Wallet.for_user(project.owner)
    ref = new_reference("FND")
    post(owner_wallet, Transaction.Kind.FUNDING, total, project=project, reference=ref, description=project.title)
    if fee:
        post(owner_wallet, Transaction.Kind.SUCCESS_FEE, -fee, project=project, reference=ref)
        collect_fee(Transaction.Kind.SUCCESS_FEE, fee, description=project.title, project=project, reference=ref)
    project.raised_amount = total
    project.status = Project.Status.ACTIVE
    project.released_at = timezone.now()
    project.save()
    if project.is_mourabaha:
        generate_installments(project)
    audit("project.released", project, actor=by, total=str(total), fee=str(fee))
    notify(project.owner, N_("Fonds versés"),
           N_("%(a)s MRU (après commission de %(f)s MRU) sont disponibles dans votre portefeuille.") % {
               "a": fmt(total - fee), "f": fmt(fee)}, url="/wallet/", sms=True)
    return project


def generate_installments(project):
    project.installments.all().delete()
    if project.repayment_mode == Project.Repayment.MONTHLY:
        n, step = max(project.duration_months, 1), 1
    elif project.repayment_mode == Project.Repayment.QUARTERLY:
        n, step = max(project.duration_months // 3, 1), 3
    else:
        n, step = 1, project.duration_months
    principal_total = project.raised_amount
    margin_total = q2(principal_total * (project.margin_pct or ZERO) / 100)
    p_each = (principal_total / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    m_each = (margin_total / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    start = (project.released_at or timezone.now()).date()
    for i in range(1, n + 1):
        last = i == n
        Installment.objects.create(
            project=project, number=i, due_date=add_months(start, step * i),
            principal=principal_total - p_each * (n - 1) if last else p_each,
            margin=margin_total - m_each * (n - 1) if last else m_each)


# ------------------------------------------------------------------ distributions

def _distribute(project, kind, gross, fee_base, out_kind, in_kind, *, due_date=None, report=None,
                installment=None, note=""):
    gross, fee_base = q2(gross), q2(fee_base)
    holdings = list(Holding.objects.select_for_update().filter(project=project, shares__gt=0)
                    .select_related("user").order_by("-shares", "id"))
    outstanding = sum(h.shares for h in holdings)
    if outstanding == 0:
        raise InvestmentError(_("Aucune part en circulation."))
    fee = pct(fee_base, project.management_fee_pct)
    net = gross - fee
    ref = new_reference("DIS")
    try:
        post(Wallet.for_user(project.owner), out_kind, -gross, project=project, reference=ref, description=note)
    except WalletError as e:
        raise InvestmentError(str(e)) from e
    collect_fee(Transaction.Kind.MANAGEMENT_FEE, fee, description=project.title, project=project, reference=ref)
    today = timezone.now().date()
    grace = PlatformSettings.get().installment_grace_days
    dist = Distribution.objects.create(
        project=project, kind=kind, report=report, installment=installment, gross_amount=gross, fee_base=fee_base,
        platform_fee=fee, net_amount=net, shares_outstanding=outstanding,
        per_share=(net / outstanding).quantize(Decimal("0.0001"), rounding=ROUND_DOWN),
        due_date=due_date, on_time=(due_date is None or today <= due_date + timedelta(days=grace)),
        note=note[:255], reference=ref)
    paid = ZERO
    for h in holdings:
        h._payout = (net * h.shares / outstanding).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        paid += h._payout
    holdings[0]._payout += net - paid  # rounding cents go to the largest holder
    for h in holdings:
        if h._payout <= 0:
            continue
        post(Wallet.for_user(h.user), in_kind, h._payout, project=project, reference=ref,
             description=project.title)
        Payout.objects.create(distribution=dist, user=h.user, shares=h.shares, amount=h._payout)
        h.received_total += h._payout
        h.save(update_fields=["received_total", "updated_at"])
        notify(h.user, N_("Vous avez reçu un versement"),
               N_("%(a)s MRU de « %(p)s ».") % {"a": fmt(h._payout), "p": project.title}, url="/portfolio/")
    record_event(project.owner, "payment_on_time" if dist.on_time else "payment_late", project=project,
                 note=dist.get_kind_display())
    audit("distribution.paid", dist, actor=project.owner, gross=str(gross), fee=str(fee))
    return dist


@transaction.atomic
def pay_profit_distribution(report):
    project = Project.objects.select_for_update().get(pk=report.project_id)
    if not project.is_moucharaka or project.status != Project.Status.ACTIVE:
        raise InvestmentError(_("Ce projet ne distribue pas de bénéfices."))
    if report.distributions.exists():
        raise InvestmentError(_("Ce rapport a déjà donné lieu à une distribution."))
    amount = report.investors_share
    if amount <= 0:
        raise InvestmentError(_("Pas de bénéfice à distribuer pour cette période."))
    return _distribute(project, Distribution.Kind.PROFIT, amount, amount, Transaction.Kind.DISTRIBUTION_OUT,
                       Transaction.Kind.DISTRIBUTION_IN, due_date=report.due_date + timedelta(days=15), report=report,
                       note=f"{report.period_start:%m/%Y}")


@transaction.atomic
def pay_installment(installment):
    inst = Installment.objects.select_for_update().get(pk=installment.pk)
    project = Project.objects.select_for_update().get(pk=inst.project_id)
    if inst.status == Installment.Status.PAID:
        raise InvestmentError(_("Échéance déjà payée."))
    if project.status not in (Project.Status.ACTIVE, Project.Status.DEFAULTED):
        raise InvestmentError(_("Ce projet n'accepte pas de paiement."))
    dist = _distribute(project, Distribution.Kind.INSTALLMENT, inst.amount, inst.margin,
                       Transaction.Kind.INSTALLMENT_OUT, Transaction.Kind.INSTALLMENT_IN, due_date=inst.due_date,
                       installment=inst, note=_("Échéance %(n)s") % {"n": inst.number})
    inst.status = Installment.Status.PAID
    inst.paid_at = timezone.now()
    inst.save(update_fields=["status", "paid_at"])
    if not project.installments.exclude(status=Installment.Status.PAID).exists():
        complete_project(project)
    return dist


def allocate_pro_rata(holdings, total):
    """Largest-remainder allocation of `total` integer units across holdings."""
    outstanding = sum(h.shares for h in holdings)
    raw = [(h, Decimal(total) * h.shares / outstanding) for h in holdings]
    alloc = {h.pk: int(x) for h, x in raw}
    left = total - sum(alloc.values())
    for h, x in sorted(raw, key=lambda t: t[1] - int(t[1]), reverse=True)[:left]:
        alloc[h.pk] += 1
    return alloc


@transaction.atomic
def buyback(project, shares_to_retire, price_per_share):
    """Owner buys back parts from every holder pro rata (Moucharaka
    moutanaqisa). Bought parts are cancelled; when none remain the project
    is completed."""
    from apps.market.services import cancel_project_listings

    project = Project.objects.select_for_update().get(pk=project.pk)
    if not project.is_moucharaka or project.status != Project.Status.ACTIVE:
        raise InvestmentError(_("Rachat impossible pour ce projet."))
    shares_to_retire, price = int(shares_to_retire), q2(price_per_share)
    if price < project.share_price * Decimal("0.5"):
        raise InvestmentError(_("Le prix de rachat ne peut pas être inférieur à 50 % de la valeur nominale sans accord de l'équipe."))
    cancel_project_listings(project, reason=_("Rachat de parts par le porteur"))
    holdings = list(Holding.objects.select_for_update().filter(project=project, shares__gt=0).select_related("user"))
    outstanding = sum(h.shares for h in holdings)
    if not 0 < shares_to_retire <= outstanding:
        raise InvestmentError(_("Nombre de parts invalide (max. %(n)s).") % {"n": outstanding})
    alloc = allocate_pro_rata(holdings, shares_to_retire)
    gross = q2(price * shares_to_retire)
    gain = max(price - project.share_price, ZERO) * shares_to_retire
    fee = pct(gain, project.management_fee_pct)
    ref = new_reference("BUY")
    try:
        post(Wallet.for_user(project.owner), Transaction.Kind.BUYBACK_OUT, -gross, project=project, reference=ref)
    except WalletError as e:
        raise InvestmentError(str(e)) from e
    collect_fee(Transaction.Kind.MANAGEMENT_FEE, fee, description=project.title, project=project, reference=ref)
    net = gross - fee
    dist = Distribution.objects.create(
        project=project, kind=Distribution.Kind.BUYBACK, gross_amount=gross, fee_base=q2(gain), platform_fee=fee,
        net_amount=net, shares_outstanding=outstanding, shares_retired=shares_to_retire,
        per_share=(net / shares_to_retire).quantize(Decimal("0.0001"), rounding=ROUND_DOWN), reference=ref,
        note=_("Rachat à %(p)s MRU / part") % {"p": fmt(price)})
    paid = ZERO
    for h in holdings:
        n = alloc[h.pk]
        if not n:
            continue
        amount = (net * n / shares_to_retire).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        paid += amount
        h._n, h._amount = n, amount
    payees = [h for h in holdings if alloc[h.pk]]
    payees[0]._amount += net - paid
    for h in payees:
        post(Wallet.for_user(h.user), Transaction.Kind.BUYBACK_IN, h._amount, project=project, reference=ref,
             description=project.title)
        Payout.objects.create(distribution=dist, user=h.user, shares=h._n, amount=h._amount)
        h.cost_basis = q2(h.cost_basis * (h.shares - h._n) / h.shares) if h.shares else ZERO
        h.shares -= h._n
        h.received_total += h._amount
        h.save()
        notify(h.user, N_("Rachat de parts"),
               N_("%(n)s part(s) de « %(p)s » rachetée(s) : %(a)s MRU reçus.") % {
                   "n": h._n, "p": project.title, "a": fmt(h._amount)}, url="/portfolio/")
    record_event(project.owner, "buyback", project=project)
    if shares_to_retire == outstanding:
        complete_project(project)
    audit("project.buyback", project, actor=project.owner, shares=shares_to_retire, price=str(price))
    return dist


def complete_project(project):
    from apps.market.services import cancel_project_listings

    cancel_project_listings(project, reason=_("Projet terminé"))
    project.status = Project.Status.COMPLETED
    project.closed_at = timezone.now()
    project.save(update_fields=["status", "closed_at", "updated_at"])
    record_event(project.owner, "project_completed", project=project)
    for h in project.holdings.filter(shares__gt=0).select_related("user"):
        notify(h.user, N_("Projet terminé"), project.title, url=project.get_absolute_url())


def mark_default(project, by=None, note=""):
    from apps.market.services import cancel_project_listings

    cancel_project_listings(project, reason=_("Projet en défaut"))
    project.status = Project.Status.DEFAULTED
    project.trading_enabled = False
    project.save(update_fields=["status", "trading_enabled", "updated_at"])
    record_event(project.owner, "default", project=project, note=note)
    audit("project.defaulted", project, actor=by, note=note)
    for h in project.holdings.filter(shares__gt=0).select_related("user"):
        notify(h.user, N_("Projet en défaut de paiement"),
               N_("Notre équipe engage le recouvrement et les garanties de « %(p)s ».") % {"p": project.title},
               url=project.get_absolute_url(), sms=True)
