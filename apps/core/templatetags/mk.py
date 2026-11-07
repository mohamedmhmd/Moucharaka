from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.translation import gettext as _

from apps.core.utils import fmt_amount

register = template.Library()

STATUS_TONE = {
    "draft": "muted", "submitted": "info", "changes": "warn", "rejected": "bad", "funding": "go",
    "funded": "good", "active": "good", "completed": "muted", "failed": "bad", "defaulted": "bad",
    "cancelled": "muted", "pending": "info", "proof": "info", "confirmed": "good", "paid": "good",
    "held": "info", "settled": "good", "refunded": "muted", "upcoming": "muted", "late": "warn",
    "approved": "good", "new": "warn", "suspended": "bad", "sold": "muted", "expired": "muted",
    "verified": "good", "flagged": "warn", "resubmit": "warn", "validated": "good", "accepted": "good", "refused": "bad",
}


@register.filter
def money(value, decimals=0):
    """1234567.5 → '1 234 568' (thin no-break space as thousands separator). Empty → '—'."""
    if value is None or value == "":
        return "—"
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return fmt_amount(d, decimals)


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


# Small line icons for the main money actions (stroke follows the button's text colour)
ICONS = {
    "deposit": '<path d="M12 3v12m0 0-4-4m4 4 4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "withdraw": '<path d="M12 15V3m0 0-4 4m4-4 4 4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "shares": '<path d="M21 12A9 9 0 1 1 12 3v9z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15z"/>',
    "contracts": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    "manage": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
}


@register.simple_tag
def icon(name):
    from django.utils.safestring import mark_safe

    path = ICONS.get(name, "")
    return mark_safe(f'<svg class="ico" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
                     f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{path}</svg>')
