import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext as _

from apps.sms.service import send_otp

from .models import PhoneOTP


class OTPError(Exception):
    pass


def _throttle(key, limit, window=3600):
    count = cache.get(key, 0)
    if count >= limit:
        return False
    cache.set(key, count + 1, window)
    return True


def issue_otp(phone, purpose, ip=None, per_hour=None, key="otp"):
    """Create and send a one-time code. Returns the code (for dev display only).
    `per_hour` and `key` give a purpose its own limit (contract signatures can be many in an hour)."""
    if not _throttle(f"{key}:phone:{phone}", per_hour or settings.OTP_MAX_PER_HOUR):
        raise OTPError(_("Trop de codes demandés pour ce numéro. Réessayez dans une heure."))
    if ip and not _throttle(f"{key}:ip:{ip}", (per_hour or settings.OTP_MAX_PER_HOUR) * 4):
        raise OTPError(_("Trop de demandes depuis cette connexion. Réessayez plus tard."))
    # Invalidate previous codes for the same purpose
    PhoneOTP.objects.filter(phone=phone, purpose=purpose, consumed_at__isnull=True).update(consumed_at=timezone.now())
    code = "".join(secrets.choice("0123456789") for _i in range(settings.OTP_LENGTH))
    PhoneOTP.objects.create(
        phone=phone, purpose=purpose, code_hash=PhoneOTP.hash_code(phone, purpose, code),
        expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS), ip=ip)
    minutes = settings.OTP_TTL_SECONDS // 60
    body = _("Moucharaka : votre code est %(code)s. Valable %(min)s min. Ne le partagez avec personne.") % {
        "code": code, "min": minutes}
    lang = (get_language() or "fr")[:2]
    if not send_otp(phone, code, body, lang=lang):
        raise OTPError(_("Le code n'a pas pu être envoyé sur WhatsApp. Vérifiez que ce numéro utilise WhatsApp, "
                         "puis réessayez."))
    return code


def verify_otp(phone, purpose, code):
    otp = PhoneOTP.objects.filter(phone=phone, purpose=purpose, consumed_at__isnull=True).first()
    if otp is None or not otp.is_valid:
        raise OTPError(_("Code expiré. Demandez un nouveau code."))
    code = "".join(c for c in str(code) if c.isdigit())
    if PhoneOTP.hash_code(phone, purpose, code) != otp.code_hash:
        PhoneOTP.objects.filter(pk=otp.pk).update(attempts=F("attempts") + 1)
        remaining = settings.OTP_MAX_ATTEMPTS - otp.attempts - 1
        if remaining <= 0:
            raise OTPError(_("Trop d'essais. Demandez un nouveau code."))
        raise OTPError(_("Code incorrect. Il vous reste %(n)s essai(s).") % {"n": remaining})
    otp.consumed_at = timezone.now()
    otp.save(update_fields=["consumed_at"])
    return otp  # truthy; contracts keep its id as proof of the signature
