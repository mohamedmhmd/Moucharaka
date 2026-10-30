"""All money movements go through `post()`, which locks the wallet row, checks
that neither the available nor the held balance becomes negative, updates it
and writes an immutable ledger line. Callers wrap several posts in
`transaction.atomic()` so a multi-leg operation is all-or-nothing."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import PlatformSettings
from apps.core.utils import N_, audit, notify, pct, q2

from .models import DepositRequest, Transaction, Wallet, WithdrawalRequest, new_reference

ZERO = Decimal("0")


class WalletError(Exception):
    pass


def post(wallet, kind, amount=ZERO, held_delta=ZERO, description="", project=None, reference=None):
    amount, held_delta = q2(amount), q2(held_delta)
    with transaction.atomic():
        w = Wallet.objects.select_for_update().get(pk=wallet.pk)
        new_balance, new_held = w.balance + amount, w.held + held_delta
        if new_balance < 0:
            raise WalletError(_("Solde insuffisant : il manque %(m)s MRU.") % {"m": f"{-new_balance:,.0f}".replace(",", " ")})
        if new_held < 0:
            raise WalletError(_("Montant bloqué insuffisant."))
        w.balance, w.held = new_balance, new_held
        w.save(update_fields=["balance", "held", "updated_at"])
        wallet.balance, wallet.held = new_balance, new_held
        return Transaction.objects.create(
            wallet=w, kind=kind, amount=amount, held_delta=held_delta, balance_after=new_balance,
            held_after=new_held, reference=reference or new_reference(), description=str(description)[:255],
            project=project)


def collect_fee(kind, amount, description="", project=None, reference=None):
    if q2(amount) > 0:
        post(Wallet.platform(), kind, amount, description=description, project=project, reference=reference)


# ------------------------------------------------------------------ deposits

@transaction.atomic
def confirm_deposit(deposit: DepositRequest, by=None, external_ref=None, payload=None):
    deposit = DepositRequest.objects.select_for_update().get(pk=deposit.pk)
    if deposit.status == DepositRequest.Status.CONFIRMED:
        return deposit
    if deposit.status in (DepositRequest.Status.REJECTED, DepositRequest.Status.EXPIRED):
        raise WalletError(_("Ce dépôt n'est plus confirmable."))
    if external_ref:
        deposit.external_ref = external_ref
    if payload:
        deposit.gateway_payload = payload
    deposit.status = DepositRequest.Status.CONFIRMED
    deposit.confirmed_by = by
    deposit.confirmed_at = timezone.now()
    deposit.save()
    acc = deposit.payment_account
    if acc is not None and acc.verified_at is None:
        acc.verified_at = timezone.now()
        acc.save(update_fields=["verified_at"])
    post(Wallet.for_user(deposit.user), Transaction.Kind.DEPOSIT, deposit.amount,
         description=f"{deposit.get_method_display()} {deposit.external_ref}".strip(), reference=deposit.reference)
    audit("deposit.confirmed", deposit, actor=by, amount=str(deposit.amount))
    notify(deposit.user, N_("Dépôt confirmé"),
           N_("%(a)s MRU ont été ajoutés à votre portefeuille.") % {"a": f"{deposit.amount:,.0f}".replace(",", " ")},
           url="/wallet/", whatsapp=True)
    return deposit


def reject_deposit(deposit, by, reason):
    deposit.status = DepositRequest.Status.REJECTED
    deposit.staff_note = reason[:255]
    deposit.confirmed_by = by
    deposit.confirmed_at = timezone.now()
    deposit.save()
    audit("deposit.rejected", deposit, actor=by, reason=reason)
    notify(deposit.user, N_("Dépôt refusé"), reason, url="/wallet/")


# ------------------------------------------------------------------ withdrawals

def withdrawal_fee(amount):
    s = PlatformSettings.get()
    return q2(s.withdrawal_fee_flat + pct(amount, s.withdrawal_fee_pct))


@transaction.atomic
def request_withdrawal(user, amount, account):
    """Withdraw to one of the user's saved payment accounts."""
    s = PlatformSettings.get()
    amount = q2(amount)
    if account.user_id != user.pk or not account.is_active:
        raise WalletError(_("Compte de réception invalide."))
    if not account.can_receive_withdrawal:
        raise WalletError(_("Ce compte vient d'être ajouté : il pourra recevoir un retrait à partir du %(d)s.") % {
            "d": account.withdrawable_from.strftime("%d/%m/%Y %H:%M")})
    if amount < s.min_withdrawal:
        raise WalletError(_("Le retrait minimum est de %(m)s MRU.") % {"m": f"{s.min_withdrawal:,.0f}"})
    fee = withdrawal_fee(amount)
    destination = account.number
    wr = WithdrawalRequest.objects.create(user=user, amount=amount, fee=fee, method=account.method,
                                          destination=destination, payment_account=account)
    post(Wallet.for_user(user), Transaction.Kind.WITHDRAWAL_HOLD, -(amount + fee), held_delta=amount + fee,
         description=destination, reference=wr.reference)
    audit("withdrawal.requested", wr, actor=user, amount=str(amount))
    return wr


@transaction.atomic
def mark_withdrawal_paid(wr, by, external_ref=""):
    wr = WithdrawalRequest.objects.select_for_update().get(pk=wr.pk)
    if wr.status != WithdrawalRequest.Status.PENDING:
        raise WalletError(_("Ce retrait a déjà été traité."))
    wallet = Wallet.for_user(wr.user)
    post(wallet, Transaction.Kind.WITHDRAWAL, 0, held_delta=-wr.amount, description=external_ref, reference=wr.reference)
    if wr.fee:
        post(wallet, Transaction.Kind.WITHDRAWAL_FEE, 0, held_delta=-wr.fee, reference=wr.reference)
        collect_fee(Transaction.Kind.WITHDRAWAL_FEE, wr.fee, description=wr.reference, reference=wr.reference)
    wr.status = WithdrawalRequest.Status.PAID
    wr.external_ref = external_ref
    wr.processed_by = by
    wr.processed_at = timezone.now()
    wr.save()
    audit("withdrawal.paid", wr, actor=by)
    notify(wr.user, N_("Retrait envoyé"),
           N_("%(a)s MRU envoyés vers %(d)s.") % {"a": f"{wr.amount:,.0f}".replace(",", " "), "d": wr.destination},
           url="/wallet/", whatsapp=True)
    return wr


@transaction.atomic
def cancel_withdrawal(wr, by=None, reason="", rejected=False):
    wr = WithdrawalRequest.objects.select_for_update().get(pk=wr.pk)
    if wr.status != WithdrawalRequest.Status.PENDING:
        raise WalletError(_("Ce retrait a déjà été traité."))
    post(Wallet.for_user(wr.user), Transaction.Kind.WITHDRAWAL_RELEASE, wr.total, held_delta=-wr.total,
         reference=wr.reference)
    wr.status = WithdrawalRequest.Status.REJECTED if rejected else WithdrawalRequest.Status.CANCELLED
    wr.staff_note = reason[:255]
    wr.processed_by = by
    wr.processed_at = timezone.now()
    wr.save()
    audit("withdrawal.cancelled", wr, actor=by, reason=reason)
    if rejected:
        notify(wr.user, N_("Retrait refusé"), reason, url="/wallet/")
    return wr


def adjust(user, amount, by=None, reason=""):
    """Manual correction by staff (also used by demo seed data). Audited."""
    tx = post(Wallet.for_user(user), Transaction.Kind.ADJUSTMENT, amount, description=reason)
    audit("wallet.adjusted", tx.wallet, actor=by, amount=str(amount), reason=reason)
    return tx


# ------------------------------------------------------------------ payment accounts

@transaction.atomic
def save_payment_account(user, form, request=None):
    from .models import PaymentAccount

    created = form.instance.pk is None
    acc = form.save(commit=False)
    acc.user = user
    if not user.payment_accounts.filter(is_active=True).exclude(pk=acc.pk).exists():
        acc.is_default = True
    if acc.is_default:
        PaymentAccount.objects.filter(user=user).exclude(pk=acc.pk).update(is_default=False)
    acc.save()
    if created:
        audit("payment_account.added", acc, actor=user, request=request, method=acc.method)
        notify(user, N_("Nouveau compte de paiement ajouté"),
               N_("%(m)s %(n)s a été ajouté à votre portefeuille. Si ce n'est pas vous, contactez le support "
                  "immédiatement.") % {"m": acc.get_method_display(), "n": acc.display_number},
               url="/wallet/accounts/", whatsapp=True)
    return acc


def remove_payment_account(acc, request=None):
    if acc.withdrawals.filter(status="pending").exists():
        raise WalletError(_("Un retrait en cours utilise ce compte. Attendez qu'il soit traité."))
    acc.is_active = False
    was_default = acc.is_default
    acc.is_default = False
    acc.save(update_fields=["is_active", "is_default"])
    if was_default:
        nxt = acc.user.payment_accounts.filter(is_active=True).first()
        if nxt:
            nxt.is_default = True
            nxt.save(update_fields=["is_default"])
    audit("payment_account.removed", acc, actor=acc.user, request=request)
