import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.decorators import approved_required
from apps.accounts.models import PhoneOTP
from apps.accounts.otp import OTPError, issue_otp, verify_otp
from apps.core.models import PlatformSettings
from apps.core.utils import N_, client_ip, notify

from .forms import DepositForm, DepositProofForm, WithdrawForm
from .gateways import get_gateway, verify_signature
from .models import DepositRequest, Wallet, WithdrawalRequest
from .services import WalletError, cancel_withdrawal, confirm_deposit, request_withdrawal, withdrawal_fee


@approved_required
def home(request):
    wallet = Wallet.for_user(request.user)
    page = Paginator(wallet.transactions.select_related("project"), 25).get_page(request.GET.get("page"))
    return render(request, "wallet/home.html", {
        "wallet": wallet, "page": page,
        "deposits": request.user.deposits.exclude(status__in=["confirmed", "expired"])[:5],
        "withdrawals": request.user.withdrawals.filter(status="pending"),
    })


@approved_required
def deposit(request):
    s = PlatformSettings.get()
    initial = {"amount": request.GET.get("amount") or None, "method": "bankily"}
    form = DepositForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["amount"] < s.min_deposit:
            form.add_error("amount", _("Minimum %(m)s MRU.") % {"m": f"{s.min_deposit:,.0f}"})
        else:
            dep = DepositRequest.objects.create(user=request.user, amount=form.cleaned_data["amount"],
                                                method=form.cleaned_data["method"], payer_phone=request.user.phone)
            nxt = request.GET.get("next", "")
            if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
                request.session["after_deposit"] = nxt
            gw = get_gateway(dep.method)
            url = gw.initiate(dep)
            return redirect(url) if url else redirect("wallet:deposit_detail", ref=dep.reference)
    return render(request, "wallet/deposit.html", {"form": form, "settings": s})


@approved_required
def deposit_detail(request, ref):
    dep = get_object_or_404(DepositRequest, reference=ref, user=request.user)
    form = DepositProofForm(request.POST or None, request.FILES or None, instance=dep)
    if request.method == "POST" and dep.status == DepositRequest.Status.PENDING and form.is_valid():
        form.instance.status = DepositRequest.Status.PROOF
        form.save()
        from apps.accounts.models import User

        for staff in User.objects.filter(is_staff=True, is_active=True):
            notify(staff, N_("Dépôt à confirmer"), f"{dep.reference} — {dep.amount} MRU", url="/staff/deposits/")
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
            wr = request_withdrawal(request.user, Decimal(pending["amount"]), pending["method"], pending["destination"])
        except WalletError as e:
            messages.error(request, str(e))
            return redirect("wallet:withdraw")
        messages.success(request, _("Demande %(r)s enregistrée. Paiement sous 24 h ouvrées.") % {"r": wr.reference})
        return redirect("wallet:home")
    form = WithdrawForm(request.POST or None, initial={"destination": request.user.phone, "method": "bankily"})
    if request.method == "POST" and form.is_valid():
        amount = form.cleaned_data["amount"]
        fee = withdrawal_fee(amount)
        if amount + fee > wallet.balance:
            form.add_error("amount", _("Solde disponible insuffisant (frais de %(f)s MRU inclus).") % {"f": fee})
        elif amount < s.min_withdrawal:
            form.add_error("amount", _("Minimum %(m)s MRU.") % {"m": f"{s.min_withdrawal:,.0f}"})
        else:
            try:
                code = issue_otp(request.user.phone, PhoneOTP.Purpose.WITHDRAW, ip=client_ip(request))
            except OTPError as e:
                messages.error(request, str(e))
            else:
                if settings.DEBUG and settings.SMS_FALLBACK_BACKEND == "console":
                    messages.info(request, _("Mode développement : votre code est %(code)s") % {"code": code})
                pending = {"amount": str(amount), "fee": str(fee), "method": form.cleaned_data["method"],
                           "destination": form.cleaned_data["destination"]}
                request.session["withdraw_pending"] = pending
                return render(request, "wallet/withdraw_confirm.html", {"pending": pending})
    return render(request, "wallet/withdraw.html", {"form": form, "wallet": wallet, "settings": s})


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
