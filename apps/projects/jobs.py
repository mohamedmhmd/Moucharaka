"""Scheduled maintenance, run once a day by `python manage.py run_daily`
(cron, systemd timer, or the hosting panel's scheduled task)."""
import logging
from datetime import timedelta

from django.utils import timezone

from apps.core.models import PlatformSettings
from apps.core.utils import N_, notify
from apps.trust.models import TrustEvent
from apps.trust.services import compute_score, record_event

from .models import Installment, Project
from .services import pending_periods

logger = logging.getLogger(__name__)
DEFAULT_AFTER_DAYS = 90


def close_expired_campaigns():
    from apps.investments.services import close_campaign

    n = 0
    for p in Project.objects.filter(status=Project.Status.FUNDING, campaign_end__lt=timezone.now()):
        close_campaign(p)
        n += 1
    return n


def check_installments(today=None):
    from apps.investments.services import mark_default

    today = today or timezone.now().date()
    grace = PlatformSettings.get().installment_grace_days
    late = 0
    for inst in Installment.objects.filter(status=Installment.Status.UPCOMING, due_date__lt=today - timedelta(days=grace)):
        inst.status = Installment.Status.LATE
        inst.save(update_fields=["status"])
        record_event(inst.project.owner, "installment_overdue", project=inst.project, note=f"#{inst.number}")
        notify(inst.project.owner, N_("Échéance en retard"),
               N_("L'échéance n°%(n)s de « %(p)s » est impayée.") % {"n": inst.number, "p": inst.project.title},
               url=f"/projects/{inst.project.slug}/manage/", sms=True)
        late += 1
    for inst in Installment.objects.filter(status=Installment.Status.LATE,
                                           due_date__lt=today - timedelta(days=DEFAULT_AFTER_DAYS)):
        inst.status = Installment.Status.DEFAULTED
        inst.save(update_fields=["status"])
        if inst.project.status == Project.Status.ACTIVE:
            mark_default(inst.project, note=f"installment #{inst.number}")
    # Reminders 3 days before the due date
    for inst in Installment.objects.filter(status=Installment.Status.UPCOMING, due_date=today + timedelta(days=3)):
        notify(inst.project.owner, N_("Rappel d'échéance"),
               N_("%(a)s MRU à payer le %(d)s pour « %(p)s ».") % {
                   "a": f"{inst.amount:,.0f}", "d": inst.due_date.strftime("%d/%m"), "p": inst.project.title},
               url=f"/projects/{inst.project.slug}/manage/", sms=True)
    return late


def check_reports(today=None):
    today = today or timezone.now().date()
    missed = 0
    for project in Project.objects.filter(status=Project.Status.ACTIVE).select_related("owner"):
        for start, end, due in pending_periods(project):
            key = f"{start:%Y-%m}"
            if due < today:
                already = TrustEvent.objects.filter(user=project.owner, project=project, kind="report_missed",
                                                    note=key).exists()
                if not already:
                    record_event(project.owner, "report_missed", project=project, note=key, recompute=False)
                    notify(project.owner, N_("Rapport financier en retard"),
                           N_("Le rapport %(m)s de « %(p)s » n'a pas été envoyé.") % {"m": key, "p": project.title},
                           url=f"/projects/{project.slug}/manage/", sms=True)
                    missed += 1
            elif (due - today).days == 3:
                notify(project.owner, N_("Rapport à envoyer"),
                       N_("Envoyez les chiffres de %(m)s avant le %(d)s.") % {"m": key, "d": due.strftime("%d/%m")},
                       url=f"/projects/{project.slug}/manage/", sms=True)
    return missed


def expire_deposits(days=7):
    from apps.wallet.models import DepositRequest

    return DepositRequest.objects.filter(status=DepositRequest.Status.PENDING,
                                         created_at__lt=timezone.now() - timedelta(days=days)).update(
        status=DepositRequest.Status.EXPIRED)


def recompute_scores():
    from apps.accounts.models import User

    n = 0
    for user in User.objects.filter(status=User.Status.APPROVED):
        compute_score(user)
        n += 1
    return n


def run_all():
    from apps.market.services import expire_listings

    result = {
        "campaigns_closed": close_expired_campaigns(),
        "installments_late": check_installments(),
        "reports_missed": check_reports(),
        "listings_expired": expire_listings(),
        "deposits_expired": expire_deposits(),
        "scores": recompute_scores(),
    }
    logger.info("daily jobs: %s", result)
    return result
