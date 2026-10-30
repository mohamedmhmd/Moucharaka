"""Deliver codes and notifications over WhatsApp (and SMS as optional fallback).

Order of channels comes from settings:
    OTP_CHANNELS          default ["whatsapp", "sms"]
    NOTIFICATION_CHANNELS default ["whatsapp"]
Inside a channel, active providers that serve the number are tried by priority.
If no provider is configured at all, MESSAGING_FALLBACK_BACKEND (console in
development) is used so the platform keeps working locally.
"""
import logging

from django.conf import settings
from django.db.models import F

from .backends import MessagingError, get_backend
from .models import SMSMessage, SMSProvider

logger = logging.getLogger(__name__)


def to_e164(phone: str) -> str:
    """+22222123456 for any input format; local numbers default to Mauritania."""
    from apps.accounts.phones import normalize_phone

    e164 = normalize_phone(phone)
    return e164 if e164.startswith("+") else "+" + e164


def _redact(text, purpose):
    # Never store codes in clear text in the log.
    if purpose == "otp":
        return "".join("•" if c.isdigit() else c for c in text)
    return text


def _deliver(phone, purpose, channels, call, log_text):
    """`call(backend)` performs the send. Returns the channel used, or None."""
    e164 = to_e164(phone)
    active = list(SMSProvider.objects.filter(is_active=True))
    if not active:
        name = settings.MESSAGING_FALLBACK_BACKEND
        channel = channels[0] if channels else "whatsapp"
        try:
            msg_id = call(get_backend(name, {}, "", channel))
        except MessagingError as exc:
            logger.error("fallback %s failed: %s", name, exc)
            return None
        SMSMessage.objects.create(phone=e164, channel=channel, body=_redact(log_text, purpose), purpose=purpose,
                                  backend=name, status="sent", provider_message_id=str(msg_id)[:120])
        return channel
    for channel in channels:
        for provider in [p for p in active if p.channel == channel and p.serves(e164)]:
            try:
                backend = get_backend(provider.backend, provider.config, provider.sender_id, provider.channel)
                msg_id = call(backend)
            except MessagingError as exc:
                logger.error("%s via %s failed: %s", channel, provider, exc)
                SMSMessage.objects.create(phone=e164, channel=channel, body=_redact(log_text, purpose), purpose=purpose,
                                          provider=provider, backend=provider.backend, status="failed",
                                          error=str(exc)[:1000])
                SMSProvider.objects.filter(pk=provider.pk).update(failed_count=F("failed_count") + 1)
                continue
            SMSMessage.objects.create(phone=e164, channel=channel, body=_redact(log_text, purpose), purpose=purpose,
                                      provider=provider, backend=provider.backend, status="sent",
                                      provider_message_id=str(msg_id)[:120])
            SMSProvider.objects.filter(pk=provider.pk).update(sent_count=F("sent_count") + 1)
            return channel
    return None


def send_otp(phone, code, text, lang="fr"):
    """Send a one-time code. Returns the channel used ("whatsapp", "sms") or None."""
    e164 = to_e164(phone)
    return _deliver(phone, "otp", settings.OTP_CHANNELS, lambda b: b.send_otp(e164, code, lang, text), text)


def send_notification(phone, title, body, lang="fr"):
    e164 = to_e164(phone)
    return _deliver(phone, "notification", settings.NOTIFICATION_CHANNELS,
                    lambda b: b.send_notification(e164, title, body, lang), f"{title}. {body}")


def send_text(phone, text, purpose="", lang="fr", channels=None):
    e164 = to_e164(phone)
    return _deliver(phone, purpose, channels or settings.NOTIFICATION_CHANNELS,
                    lambda b: b.send_text(e164, text, lang), text)


def send_sms(phone, body, purpose=""):
    """Backwards-compatible helper: free text on any configured channel."""
    return bool(send_text(phone, body, purpose=purpose, channels=["whatsapp", "sms"]))
