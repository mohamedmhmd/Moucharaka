from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounts.otp import OTPError

from .models import Contract
from .services import ContractError, codes_shown_on_screen, send_code, sign


def _back(contract):
    if contract.project_id:
        if contract.created_by_id == contract.project.owner_id:
            return redirect("projects:manage", slug=contract.project.slug)
        return redirect(contract.project.get_absolute_url())
    return redirect("core:dashboard")


@login_required
def sign_view(request, ref):
    contract = get_object_or_404(Contract, reference=ref, created_by=request.user)
    if contract.status == Contract.Status.SIGNED:
        return redirect(contract)
    if contract.status != Contract.Status.PENDING:
        messages.error(request, _("Ce contrat n'a pas été signé. Recommencez l'opération si vous le souhaitez."))
        return _back(contract)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "cancel":
            contract.status, contract.error = Contract.Status.CANCELLED, "cancelled by signer"
            contract.save(update_fields=["status", "error"])
            request.session.pop(f"sign_code_{contract.reference}", None)
            messages.info(request, _("Opération abandonnée : rien n'a été signé ni payé."))
            return _back(contract)
        if action == "resend":
            try:
                send_code(request, contract)
                messages.success(request, _("Un nouveau code vous a été envoyé."))
            except OTPError as e:
                messages.error(request, str(e))
            return redirect("contracts:sign", ref=ref)
        if not request.POST.get("accept"):
            messages.error(request, _("Cochez la case pour confirmer que vous avez lu le contrat."))
        else:
            try:
                signed, result = sign(request, contract, request.POST.get("code", ""))
            except ContractError as e:
                messages.error(request, str(e))
                contract.refresh_from_db()
                if contract.status != Contract.Status.PENDING:
                    return _back(contract)
            else:
                messages.success(request, result["message"])
                return redirect(result["url"])
    return render(request, "contracts/sign.html", {
        "contract": contract, "role_label": dict(contract.signatures.model.Role.choices).get(contract.payload.get("role")),
        "dev_code": request.session.get(f"sign_code_{contract.reference}") if codes_shown_on_screen() else None})


@login_required
def detail(request, ref):
    contract = get_object_or_404(Contract.objects.select_related("project", "parent"), reference=ref)
    if not contract.visible_to(request.user) or contract.status == Contract.Status.CANCELLED and not request.user.is_staff:
        raise Http404
    if contract.status == Contract.Status.PENDING and contract.created_by_id == request.user.pk:
        return redirect("contracts:sign", ref=ref)
    return render(request, "contracts/detail.html", {"contract": contract, "signatures": contract.signatures.all(),
                                                     "seal_ok": contract.seal_hash == contract.compute_seal()
                                                     if contract.seal_hash else None,
                                                     "text_ok": contract.body_hash == Contract.fingerprint(contract.body)})


@login_required
def mine(request):
    contracts = (request.user.contracts.filter(status__in=[Contract.Status.SIGNED, Contract.Status.TERMINATED])
                 .select_related("project").distinct())
    return render(request, "contracts/list.html", {"contracts": contracts})
