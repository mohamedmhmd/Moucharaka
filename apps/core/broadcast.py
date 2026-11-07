"""Send one message from the team to a group of members: in-app notification for all, plus WhatsApp."""
import time

from django.db import transaction

from apps.accounts.models import User

from .models import Broadcast, Notification

WHATSAPP_SECONDS_PER_REQUEST = 40  # the page answers well before the server's 60 s limit


def audience_users(audience):
    members = User.objects.filter(is_active=True, is_staff=False, is_superuser=False)
    if audience == Broadcast.Audience.KYC_TODO:
        return members.filter(status=User.Status.NEW)
    if audience == Broadcast.Audience.KYC_FIX:
        return members.filter(kyc__status="resubmit")
    if audience == Broadcast.Audience.APPROVED:
        return members.filter(status=User.Status.APPROVED)
    return members


@transaction.atomic
def create_broadcast(*, audience, title_ar, body_ar, title_fr, body_fr, url="", whatsapp=True, by=None):
    users = list(audience_users(audience).only("id", "preferred_language", "whatsapp_notifications"))
    b = Broadcast.objects.create(audience=audience, title_ar=title_ar, body_ar=body_ar, title_fr=title_fr,
                                 body_fr=body_fr, url=url, whatsapp=whatsapp, created_by=by, recipients=len(users))
    notes = []
    for u in users:
        title, body = b.text_for(u.preferred_language)
        notes.append(Notification(user=u, title=title[:200], body=body, url=url))
    Notification.objects.bulk_create(notes, batch_size=500)
    if whatsapp:
        b.whatsapp_pending = [u.pk for u in users if u.whatsapp_notifications]
        b.save(update_fields=["whatsapp_pending"])
    return b


def send_whatsapp_batch(broadcast, seconds=WHATSAPP_SECONDS_PER_REQUEST):
    """Send WhatsApp copies until the time budget is used; returns how many are still waiting."""
    from apps.sms.service import send_notification

    started = time.monotonic()
    pending = list(broadcast.whatsapp_pending)
    users = {u.pk: u for u in User.objects.filter(pk__in=pending, is_active=True)}
    while pending and time.monotonic() - started < seconds:
        user = users.get(pending.pop(0))
        if user is None:
            continue
        title, body = broadcast.text_for(user.preferred_language)
        if send_notification(user.phone, title, body, lang=(user.preferred_language or "ar")[:2]):
            broadcast.whatsapp_sent += 1
        else:
            broadcast.whatsapp_failed += 1
    broadcast.whatsapp_pending = pending
    broadcast.save(update_fields=["whatsapp_pending", "whatsapp_sent", "whatsapp_failed"])
    return len(pending)
