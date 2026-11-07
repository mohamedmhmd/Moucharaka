import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.decorators import approved_required
from apps.accounts.models import PhoneOTP
from apps.accounts.otp import OTPError, issue_otp, verify_otp
from apps.core.models import PlatformSettings
from apps.core.utils import fmt_amount, N_, client_ip, notify

from .forms import DepositForm, DepositProofForm, PaymentAccountForm, WithdrawForm
from .gateways import get_gateway, verify_signature
from .models import DepositRequest, PaymentAccount, Wallet, WithdrawalRequest
from .services import (WalletError, cancel_withdrawal, confirm_deposit, remove_payment_account, request_withdrawal,
                       save_payment_account, withdrawal_fee,
                       withdrawal_fee_rules)


@approved_required
def home(request):
    wallet = Wallet.for_user(request.user)
    page = Paginator(wallet.transactions.select_related("project"), 25).get_page(request.GET.get("page"))
    return render(request, "wallet/home.html", {
        "wallet": wallet, "page": page,
        "deposits": request.user.deposits.exclude(status__in=["confirmed", "expired"])[:5],
        "withdrawals": request.user.withdrawals.filter(status="pending"),
        "accounts": request.user.payment_accounts.filter(is_active=True),
    })


@approved_required
def accounts(request):
    return render(request, "wallet/accounts.html", {
        "accounts": request.user.payment_accounts.filter(is_active=True),
        "hold_hours": settings.NEW_PAYMENT_ACCOUNT_HOLD_HOURS})


@approved_required
def account_add(request, pk=None):
    instance = get_object_or_404(PaymentAccount, pk=pk, user=request.user, is_active=True) if pk else None
    form = PaymentAccountForm(request.POST or None, instance=instance, user=request.user)
    if instance:  # number and type can't change: remove and add a new account instead
        form.fields["method"].disabled = True
        form.fields["number"].disabled = True
    if request.method == "POST" and form.is_valid():
        save_payment_account(request.user, form, request=request)
        messages.success(request, _("Compte enregistré."))
        nxt = request.GET.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            return redirect(nxt)
        return redirect("wallet:accounts")
    return render(request, "wallet/account_form.html", {"form": form, "instance": instance,
                                                        "hold_hours": settings.NEW_PAYMENT_ACCOUNT_HOLD_HOURS})


@require_POST
@approved_required
def account_default(request, pk):
    acc = get_object_or_404(PaymentAccount, pk=pk, user=request.user, is_active=True)
    PaymentAccount.objects.filter(user=request.user).update(is_default=False)
    acc.is_default = True
    acc.save(update_fields=["is_default"])
    return redirect("wallet:accounts")


@require_POST
@approved_required
def account_remove(request, pk):
    acc = get_object_or_404(PaymentAccount, pk=pk, user=request.user, is_active=True)
    try:
        remove_payment_account(acc, request=request)
        messages.success(request, _("Compte retiré."))
    except WalletError as e:
        messages.error(request, str(e))
    return redirect("wallet:accounts")


@approved_required
def deposit(request):
    s = PlatformSettings.get()
    initial = {"amount": request.GET.get("amount") or None}
    form = DepositForm(request.POST or None, initial=initial, user=request.user)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["amount"] < s.min_deposit:
            form.add_error("amount", _("Minimum %(m)s MRU.") % {"m": fmt_amount(s.min_deposit)})
        else:
            acc = None if form.cleaned_data.get("cash") else form.cleaned_data["account"]
            dep = DepositRequest.objects.create(
                user=request.user, amount=form.cleaned_data["amount"], method=acc.method if acc else "cash",
                payment_account=acc, payer_phone=acc.number if acc else request.user.phone)
            nxt = request.GET.get("next", "")
            if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
                request.session["after_deposit"] = nxt
            gw = get_gateway(dep.method)
            url = gw.initiate(dep)
            return redirect(url) if url else redirect("wallet:deposit_detail", ref=dep.reference)
    return render(request, "wallet/deposit.html", {
        "form": form, "settings": s, "has_accounts": request.user.payment_accounts.filter(is_active=True).exists()})


@approved_required
def deposit_detail(request, ref):
    dep = get_object_or_404(DepositRequest, reference=ref, user=request.user)
    form = DepositProofForm(request.POST or None, request.FILES or None, instance=dep)
    if request.method == "POST" and dep.status == DepositRequest.Status.PENDING and form.is_valid():
        form.instance.status = DepositRequest.Status.PROOF
        form.save()
        from apps.core.staff_tasks import notify_staff
        from apps.core.utils import fmt_amount

        notify_staff(N_("Dépôt à confirmer"), f"{dep.reference} — {fmt_amount(dep.amount)} MRU", url="/staff/deposits/",
                     task=f"deposit:{dep.pk}")
        messages.success(request, _("Merci. Votre dépôt sera confirmé après vérification (généralement en moins d'une heure en journée)."))
        nxt = request.session.pop("after_deposit", None)
        return redirect(nxt or "wallet:home")
    return render(request, "wallet/deposit_detail.html", {
        "deposit": dep, "form": form, "steps": get_gateway(dep.method).instructions(dep)})


@approved_required
def withdraw(request):
    wallet = Wallet.for_user(request.user)
    s = PlatformSettings.get()
    pending = request.session.get("withdraw_pending")
    if request.method == "POST" and "code" in request.POST and pending:
        try:
            verify_otp(request.user.phone, PhoneOTP.Purpose.WITHDRAW, request.POST["code"])
        except OTPError as e:
            messages.error(request, str(e))
            return render(request, "wallet/withdraw_confirm.html", {"pending": pending})
        request.session.pop("withdraw_pending", None)
        try:
            acc = PaymentAccount.objects.get(pk=pending["account"], user=request.user, is_active=True)
            wr = request_withdrawal(request.user, Decimal(pending["amount"]), acc)
        except (WalletError, PaymentAccount.DoesNotExist) as e:
            messages.error(request, str(e))
            return redirect("wallet:withdraw")
        messages.success(request, _("Demande %(r)s enregistrée. Paiement sous 24 h ouvrées.") % {"r": wr.reference})
        return redirect("wallet:home")
    if not request.user.payment_accounts.filter(is_active=True).exists():
        messages.info(request, _("Ajoutez d'abord le compte Bankily, Masrvi, Sedad ou bancaire qui recevra l'argent."))
        return redirect(reverse("wallet:account_add") + "?next=" + reverse("wallet:withdraw"))
    form = WithdrawForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        amount = form.cleaned_data["amount"]
        fee = withdrawal_fee(amount, form.cleaned_data["account"].method)
        if amount + fee > wallet.balance:
            form.add_error("amount", _("Solde disponible insuffisant (frais de %(f)s MRU inclus).") % {"f": fee})
        elif amount < s.min_withdrawal:
            form.add_error("amount", _("Minimum %(m)s MRU.") % {"m": fmt_amount(s.min_withdrawal)})
        else:
            try:
                code = issue_otp(request.user.phone, PhoneOTP.Purpose.WITHDRAW, ip=client_ip(request))
            except OTPError as e:
                messages.error(request, str(e))
            else:
                if settings.OTP_SHOW_ON_SCREEN or (settings.DEBUG and settings.SMS_FALLBACK_BACKEND == "console"):
                    messages.info(request, _("Mode développement : votre code est %(code)s") % {"code": code})
                acc = form.cleaned_data["account"]
                pending = {"amount": str(amount), "fee": str(fee), "account": acc.pk,
                           "method": acc.get_method_display(), "destination": acc.display_number,
                           "holder": acc.holder_name}
                request.session["withdraw_pending"] = pending
                return render(request, "wallet/withdraw_confirm.html", {"pending": pending})
    rules, general = withdrawal_fee_rules()
    fee_data = {
        "rules": {m: [[float(a), float(f), float(p)] for a, f, p in rs] for m, rs in rules.items()},
        "general": [float(general[0]), float(general[1])],
        "accounts": {str(a.pk): a.method for a in request.user.payment_accounts.filter(is_active=True)},
    }
    return render(request, "wallet/withdraw.html", {"form": form, "wallet": wallet, "settings": s,
                                                    "fee_data": fee_data})


@require_POST
@approved_required
def withdraw_cancel(request, ref):
    wr = get_object_or_404(WithdrawalRequest, reference=ref, user=request.user)
    try:
        cancel_withdrawal(wr, by=request.user)
        messages.success(request, _("Retrait annulé, fonds débloqués."))
    except WalletError as e:
        messages.error(request, str(e))
    return redirect("wallet:home")


def receipt(request, ref):
    dep = get_object_or_404(DepositRequest, reference=ref)
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.pk == dep.user_id) or not dep.receipt:
        raise Http404
    from apps.projects.views import _serve_private

    return _serve_private(dep.receipt)


@csrf_exempt
@require_POST
def webhook(request, method):
    """Payment provider callback. Body: {"reference": "DEP-…", "amount": 1000,
    "transaction_id": "…", "status": "success"}; header X-Signature =
    hex HMAC-SHA256(body, PAYMENT_WEBHOOK_SECRET)."""
    if not verify_signature(request.body, request.headers.get("X-Signature", "")):
        return HttpResponseForbidden("bad signature")
    try:
        data = json.loads(request.body)
        dep = DepositRequest.objects.get(reference=data["reference"], method=method)
        amount = Decimal(str(data["amount"]))
    except (ValueError, KeyError, DepositRequest.DoesNotExist):
        return HttpResponseBadRequest("invalid payload")
    if data.get("status") != "success":
        return JsonResponse({"ok": True, "ignored": True})
    if amount != dep.amount:
        dep.staff_note = f"webhook amount mismatch: {amount}"
        dep.status = DepositRequest.Status.PROOF
        dep.gateway_payload = data
        dep.save()
        return JsonResponse({"ok": False, "error": "amount mismatch"}, status=409)
    try:
        confirm_deposit(dep, external_ref=str(data.get("transaction_id", ""))[:80], payload=data)
    except WalletError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=409)
    return JsonResponse({"ok": True})
