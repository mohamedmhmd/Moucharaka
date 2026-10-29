import logging

from django.conf import settings
from django.db.models import F

from .backends import SMSError, get_backend
from .models import SMSMessage, SMSProvider

logger = logging.getLogger(__name__)


def to_e164(phone: str) -> str:
    """Normalise a Mauritanian number (8 digits starting 2, 3 or 4) to +222XXXXXXXX."""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    cc = settings.PHONE_COUNTRY_CODE
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 8:
        digits = cc + digits
    return "+" + digits


def send_sms(phone: str, body: str, purpose: str = "") -> bool:
    """Send through active providers by priority, failing over on error.

    Returns True if one provider accepted the message. Never raises: callers
    (OTP, notifications) must not crash because a gateway is down.
    """
    e164 = to_e164(phone)
    local = e164[-8:]
    providers = [p for p in SMSProvider.objects.filter(is_active=True) if p.serves(local)]
    attempts = providers or [None]
    for provider in attempts:
        backend_name = provider.backend if provider else settings.SMS_FALLBACK_BACKEND
        try:
            backend = get_backend(backend_name, provider.config if provider else {},
                                  provider.sender_id if provider else "")
            msg_id = backend.send(e164, body)
        except SMSError as exc:
            logger.error("SMS via %s failed: %s", provider or backend_name, exc)
            SMSMessage.objects.create(phone=e164, body=_redact(body, purpose), purpose=purpose, provider=provider,
                                      backend=backend_name, status="failed", error=str(exc)[:1000])
            if provider:
                SMSProvider.objects.filter(pk=provider.pk).update(failed_count=F("failed_count") + 1)
            continue
        SMSMessage.objects.create(phone=e164, body=_redact(body, purpose), purpose=purpose, provider=provider,
                                  backend=backend_name, status="sent", provider_message_id=str(msg_id)[:120])
        if provider:
            SMSProvider.objects.filter(pk=provider.pk).update(sent_count=F("sent_count") + 1)
        return True
    return False


def _redact(body, purpose):
    # Never store OTP codes in clear text in the log.
    if purpose == "otp":
        return "".join("•" if c.isdigit() else c for c in body)
    return body
