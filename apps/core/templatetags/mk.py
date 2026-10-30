from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.translation import gettext as _

register = template.Library()

STATUS_TONE = {
    "draft": "muted", "submitted": "info", "changes": "warn", "rejected": "bad", "funding": "go",
    "funded": "good", "active": "good", "completed": "muted", "failed": "bad", "defaulted": "bad",
    "cancelled": "muted", "pending": "info", "proof": "info", "confirmed": "good", "paid": "good",
    "held": "info", "settled": "good", "refunded": "muted", "upcoming": "muted", "late": "warn",
    "approved": "good", "new": "warn", "suspended": "bad", "sold": "muted", "expired": "muted",
    "verified": "good", "flagged": "warn", "resubmit": "warn",
}


@register.filter
def money(value, decimals=0):
    """1234567.5 → '1 234 568' (thin no-break space as thousands separator)."""
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    s = f"{d:,.{int(decimals)}f}".replace(",", " ")
    return s


@register.filter
def signed_money(value):
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "+" if d > 0 else ("−" if d < 0 else "")
    return f"{sign}{money(abs(d))}"


@register.simple_tag
def badge(status, label):
    return format_html('<span class="badge tone-{}">{}</span>', STATUS_TONE.get(status, "muted"), label)


@register.filter
def pct_of(value, total):
    try:
        total = Decimal(total)
        return int(Decimal(value) * 100 / total) if total else 0
    except (InvalidOperation, TypeError, ValueError):
        return 0


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def mul(a, b):
    try:
        return Decimal(a) * Decimal(b)
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.filter
def grade_tone(grade):
    return {"A+": "good", "A": "good", "B": "good", "C": "warn", "D": "warn", "E": "bad"}.get(grade, "muted")


@register.simple_tag
def grade_label(grade):
    return _("Nouveau") if grade == "N" else grade


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        q[k] = v
    return q.urlencode()


@register.filter
def phone(value):
    """+22222123456 → +222 22 12 34 56"""
    from apps.accounts.phones import display_phone

    return display_phone(value)
