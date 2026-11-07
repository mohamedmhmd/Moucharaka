"""Prepare a contract, send the signing code, and on a valid code run the action it authorises.

The money only moves inside `sign()`, in the same database transaction that records the
signature: either the contract is signed and the operation done, or neither."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import get_language, get_language_bidi
from django.utils.translation import gettext as _

from apps.accounts.models import PhoneOTP
from apps.accounts.otp import OTPError, issue_otp, verify_otp
from apps.core.models import PlatformSettings
from apps.core.utils import audit, client_ip

from .models import Contract, Signature, new_contract_reference

SIGN_TTL = timedelta(minutes=30)
SIGN_CODES_PER_HOUR = 30


class ContractError(Exception):
    pass


def codes_shown_on_screen():
    """Development mode: while no WhatsApp/SMS provider is active, the signing code is shown on the page."""
    from apps.sms.models import SMSProvider

    dev_console = settings.DEBUG and settings.SMS_FALLBACK_BACKEND == "console"
    return dev_console or not SMSProvider.objects.filter(is_active=True).exists()


def party(user, role):
    """Identity of a person as printed in a contract (taken from their verified identity file)."""
    kyc = getattr(user, "kyc", None)
    address = ""
    if kyc:
        parts = (kyc.address, kyc.moughataa, kyc.wilaya) if kyc.country == "MR" else (
            kyc.address, kyc.city, kyc.country_name)
        address = ("، " if get_language_bidi() else ", ").join(str(x) for x in parts if x)
    return {
        "user": user, "role": role, "role_label": Signature.Role(role).label, "public_id": user.public_id,
        "name": (kyc.full_name if kyc else "") or user.full_name, "nni": kyc.nni if kyc else "",
        "birth_date": kyc.date_of_birth if kyc else None, "birth_place": kyc.place_of_birth if kyc else "",
        "address": address, "phone": user.phone,
    }


def platform_party():
    s = PlatformSettings.get()
    return {"name": s.legal_name or "Moucharaka", "registration": s.legal_registration, "address": s.legal_address,
            "city": s.legal_city or "Nouakchott", "site": "mou-charaka.com", "email": s.contact_email}


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items() if not hasattr(v, "_meta")}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def send_code(request, contract):
    code = issue_otp(request.user.phone, PhoneOTP.Purpose.SIGN, ip=client_ip(request),
                     per_hour=SIGN_CODES_PER_HOUR, key="sign")
    if codes_shown_on_screen():
        request.session[f"sign_code_{contract.reference}"] = code
    return code


def prepare(request, *, kind, project, action, payload, role, context, viewers=(), parent=None, title=None):
    """Create the contract the signer is about to read, and send them a code."""
    user = request.user
    ref = new_contract_reference()
    title = title or Contract.Kind(kind).label
    platform = platform_party()
    ctx = {"contract_ref": ref, "title": title, "today": timezone.now(), "platform": platform,
           "city": platform["city"], "project": project, "signer": party(user, role), "parent": parent,
           "sep": "، " if get_language_bidi() else ", ", **context}
    body = render_to_string(f"contracts/body/{kind}.html", ctx)
    contract = Contract.objects.create(
        reference=ref, kind=kind, project=project, title=title, language=(get_language() or "ar")[:5], body=body,
        body_hash=Contract.fingerprint(body), terms=_jsonable(context.get("terms", {})), action=action,
        payload={**payload, "role": role}, created_by=user, parent=parent)
    contract.viewers.set({user, *[v for v in viewers if v]})
    try:
        send_code(request, contract)
    except OTPError as e:
        contract.status, contract.error = Contract.Status.CANCELLED, str(e)[:255]
        contract.save(update_fields=["status", "error"])
        raise ContractError(str(e)) from e
    return contract


def sign(request, contract, code):
    """Check the code, run the operation and record the signature, all at once."""
    from .actions import ACTIONS, ActionError

    user = request.user
    if contract.created_by_id != user.pk or contract.status != Contract.Status.PENDING:
        raise ContractError(_("Ce contrat ne peut plus être signé."))
    if timezone.now() - contract.created_at > SIGN_TTL:
        contract.status, contract.error = Contract.Status.CANCELLED, "expired"
        contract.save(update_fields=["status", "error"])
        raise ContractError(_("Ce contrat a expiré. Recommencez l'opération."))
    try:
        otp = verify_otp(user.phone, PhoneOTP.Purpose.SIGN, code)
    except OTPError as e:
        raise ContractError(str(e)) from e
    try:
        with transaction.atomic():
            c = Contract.objects.select_for_update().get(pk=contract.pk)
            if c.status != Contract.Status.PENDING:  # a second click on "Signer"
                raise ActionError(_("Ce contrat est déjà traité."))
            result = ACTIONS[c.action](c, user)
            now = timezone.now()
            me = party(user, c.payload["role"])
            Signature.objects.create(
                contract=c, user=user, role=me["role"], full_name=me["name"], nni=me["nni"], phone=user.phone,
                signed_at=now, ip=client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
                otp_id=getattr(otp, "pk", None))
            if c.parent_id:  # the other party already signed their offer: their signature carries over
                for s in c.parent.signatures.exclude(user=user):
                    Signature.objects.create(
                        contract=c, user=s.user, role=s.role, full_name=s.full_name, nni=s.nni, phone=s.phone,
                        signed_at=s.signed_at, ip=s.ip, user_agent=s.user_agent, method=s.method, otp_id=s.otp_id,
                        from_contract=c.parent)
            c.status, c.signed_at = Contract.Status.SIGNED, now
            c.object_ref = result.get("object_ref", "")[:60]
            c.seal_hash = c.compute_seal()
            c.save(update_fields=["status", "signed_at", "object_ref", "seal_hash"])
            audit("contract.signed", c, actor=user, reference=c.reference, kind=c.kind)
    except ActionError as e:
        Contract.objects.filter(pk=contract.pk).update(status=Contract.Status.CANCELLED, error=str(e)[:255])
        raise ContractError(str(e)) from e
    request.session.pop(f"sign_code_{contract.reference}", None)
    return c, result


def terminate(object_ref, kind=None):
    """The operation was undone (e.g. an investment cancelled within 48 h)."""
    qs = Contract.objects.filter(object_ref=object_ref, status=Contract.Status.SIGNED)
    if kind:
        qs = qs.filter(kind=kind)
    qs.update(status=Contract.Status.TERMINATED, terminated_at=timezone.now())


def funding_signed(project):
    return project.contracts.filter(kind=Contract.Kind.FUNDING, status=Contract.Status.SIGNED).exists()
