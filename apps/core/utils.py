from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from django.contrib.contenttypes.models import ContentType
from django.utils import translation

CENT = Decimal("0.01")


def q2(value) -> Decimal:
    """Quantize a monetary value to 2 decimals (banker-free half-up)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q2_down(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_DOWN)


def pct(amount, rate) -> Decimal:
    return q2(Decimal(amount) * Decimal(rate) / Decimal(100))


def client_ip(request):
    if request is None:
        return None
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def audit(action, target=None, actor=None, request=None, **data):
    from .models import AuditLog

    kw = {"action": action, "actor": actor, "data": data, "ip": client_ip(request)}
    if target is not None:
        kw["content_type"] = ContentType.objects.get_for_model(target.__class__)
        kw["object_id"] = str(target.pk)
        kw["target_repr"] = str(target)[:200]
    return AuditLog.objects.create(**kw)


class Msg:
    """A translatable message rendered later, in whatever language is active
    at that moment (notify() activates the recipient's language).

    Usage: N_("%(n)s part(s) vendue(s)") % {"n": 3}
    """

    def __init__(self, text, params=None):
        self.text, self.params = text, params

    def __mod__(self, params):
        return Msg(self.text, params)

    def __str__(self):
        from django.utils.translation import gettext

        s = gettext(self.text)
        return s % self.params if self.params else s


def N_(text):  # noqa: N802 - gettext-style marker, extracted by scripts/i18n.py
    return Msg(text)


def notify(user, title, body="", url="", sms=False):
    """In-app notification, optionally mirrored by SMS.

    `title` and `body` may be lazy translation strings: they are rendered in
    the recipient's preferred language, not the caller's.
    """
    from apps.sms.service import send_sms

    from .models import Notification

    lang = getattr(user, "preferred_language", None) or "ar"
    with translation.override(lang):
        title_s, body_s = str(title), str(body)
    n = Notification.objects.create(user=user, title=title_s[:200], body=body_s, url=url)
    if sms and user.phone:
        send_sms(user.phone, f"{title_s}. {body_s}".strip()[:300], purpose="notification")
    return n
