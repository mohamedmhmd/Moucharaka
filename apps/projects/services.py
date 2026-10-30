from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import PlatformSettings
from apps.core.utils import N_, audit, notify
from apps.trust.services import record_event
from apps.wallet.models import Transaction, Wallet
from apps.wallet.services import WalletError, collect_fee, post

from .models import FeePolicy, FinancialReport, Kind, Project, Question


class ProjectError(Exception):
    pass


def checklist(project):
    """List of (label, done) the owner sees before submitting."""
    items = []

    def add(label, ok):
        items.append({"label": label, "done": bool(ok)})

    add(_("Présentation d'au moins 300 caractères"), len(project.description or "") >= 300)
    add(_("Photo principale"), project.cover)
    uses = project.uses_of_funds.aggregate(s=Sum("amount"))["s"] or Decimal("0")
    add(_("Utilisation des fonds détaillée (total = montant recherché)"),
        project.target_amount and abs(uses - project.target_amount) <= project.target_amount * Decimal("0.05"))
    add(_("Au moins un justificatif"), project.documents.exists())
    if project.is_moucharaka:
        add(_("Part des bénéfices, rendement estimé et sortie définis"),
            project.investor_profit_share_pct and project.projected_annual_return_pct is not None and project.exit_mode)
    else:
        add(_("Marge, échéancier et garanties définis"), project.margin_pct and project.repayment_mode and project.guarantee)
    if project.kind == Kind.BOUTIQUE:
        b = getattr(project, "boutique", None)
        add(_("Fiche boutique complète"), b)
        add(_("Ventes des 6 derniers mois au moins"), project.boutique_months.count() >= 6)
        add(_("Au moins 3 produits phares"), project.boutique_products.count() >= 3)
        add(_("Au moins 3 photos de la boutique"), project.images.count() >= 3)
    elif project.kind == Kind.COMPANY:
        add(_("Plan d'entreprise complet"), getattr(project, "company", None))
        add(_("Équipe présentée"), project.team.exists())
        add(_("Prévisions sur 3 ans"), project.projections.count() >= 3)
        add(_("Au moins 2 étapes clés"), project.milestones.count() >= 2)
    else:
        add(_("Description de l'opération"), getattr(project, "deal", None))
    required = [q for q in Question.objects.filter(active=True, required=True) if q.applies(project.kind)]
    answered = set(project.answers.exclude(value__isnull=True).exclude(value="").values_list("question_id", flat=True))
    add(_("Questions obligatoires du questionnaire (%(a)s / %(t)s)") % {
        "a": len([q for q in required if q.pk in answered]), "t": len(required)},
        all(q.pk in answered for q in required))
    return items


@transaction.atomic
def submit_project(project, user):
    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.owner_id != user.pk or not project.is_editable:
        raise ProjectError(_("Ce projet ne peut pas être soumis."))
    missing = [i["label"] for i in checklist(project) if not i["done"]]
    if missing:
        raise ProjectError(_("Il manque : %(m)s") % {"m": "; ".join(str(m) for m in missing)})
    policy = FeePolicy.for_project(project)
    if not policy.is_enabled:
        raise ProjectError(_("Ce type de financement n'est pas ouvert pour le moment."))
    if not policy.min_target <= project.target_amount <= policy.max_target:
        raise ProjectError(_("Le montant doit être compris entre %(a)s et %(b)s MRU.") % {
            "a": f"{policy.min_target:,.0f}", "b": f"{policy.max_target:,.0f}"})
    fee = policy.review_fee if project.review_fee_paid == 0 else Decimal("0")
    if fee:
        try:
            post(Wallet.for_user(user), Transaction.Kind.REVIEW_FEE, -fee, project=project,
                 description=project.reference)
        except WalletError as e:
            raise ProjectError(_("Les frais d'étude (%(f)s MRU) doivent être disponibles dans votre portefeuille. %(e)s") % {
                "f": f"{fee:,.0f}", "e": e}) from e
        collect_fee(Transaction.Kind.REVIEW_FEE, fee, description=project.reference, project=project)
        project.review_fee_paid = fee
    project.status = Project.Status.SUBMITTED
    project.submitted_at = timezone.now()
    project.save()
    audit("project.submitted", project, actor=user)
    from apps.accounts.models import User

    for staff in User.objects.filter(is_staff=True, is_active=True):
        notify(staff, N_("Projet à étudier"), project.title, url=f"/staff/projects/{project.pk}/")
    return project


@transaction.atomic
def approve_project(project, reviewer, risk_grade, public_notes=""):
    if project.status != Project.Status.SUBMITTED:
        raise ProjectError(_("Ce projet n'est pas en cours d'étude."))
    policy = FeePolicy.for_project(project)
    s = PlatformSettings.get()
    project.success_fee_pct = policy.success_fee_pct
    project.management_fee_pct = policy.management_fee_pct
    project.risk_grade = risk_grade
    project.review_notes = public_notes
    project.reviewed_by = reviewer
    project.status = Project.Status.FUNDING
    project.campaign_start = timezone.now()
    project.campaign_end = timezone.now() + timedelta(days=min(project.campaign_days, s.max_campaign_days))
    project.changes_requested = ""
    project.save()
    audit("project.approved", project, actor=reviewer, grade=risk_grade)
    from .sharing import notify_interested

    notify_interested(project)
    notify(project.owner, N_("Votre projet est en ligne"),
           N_("La collecte de « %(p)s » est ouverte jusqu'au %(d)s.") % {
               "p": project.title, "d": project.campaign_end.strftime("%d/%m/%Y")},
           url=project.get_absolute_url(), whatsapp=True)
    return project


def request_changes(project, reviewer, message):
    project.status = Project.Status.CHANGES
    project.changes_requested = message
    project.reviewed_by = reviewer
    project.save()
    audit("project.changes_requested", project, actor=reviewer)
    notify(project.owner, N_("Corrections demandées sur votre projet"), message,
           url=f"/projects/{project.slug}/edit/", whatsapp=True)


def reject_project(project, reviewer, message):
    project.status = Project.Status.REJECTED
    project.changes_requested = message
    project.reviewed_by = reviewer
    project.save()
    audit("project.rejected", project, actor=reviewer)
    notify(project.owner, N_("Projet refusé"), message, url="/dashboard/", whatsapp=True)


# ------------------------------------------------------------------ reporting

def report_periods(project, today=None):
    """Closed reporting periods since funds were released: (start, end, due)."""
    if not project.released_at:
        return []
    today = today or timezone.now().date()
    step = 3 if project.report_frequency == Project.Frequency.QUARTERLY else 1
    grace = PlatformSettings.get().report_grace_days
    rel = project.released_at.date()
    start = date(rel.year, rel.month, 1)
    periods = []
    while True:
        m = start.month - 1 + step
        nxt = date(start.year + m // 12, m % 12 + 1, 1)
        end = nxt - timedelta(days=1)
        if end >= today:
            break
        periods.append((start, end, end + timedelta(days=grace)))
        start = nxt
    return periods


def pending_periods(project):
    done = set(project.reports.values_list("period_start", flat=True))
    return [p for p in report_periods(project) if p[0] not in done]


@transaction.atomic
def submit_report(project, user, period_start, data, attachment=None):
    if project.owner_id != user.pk or project.status not in (Project.Status.ACTIVE, Project.Status.DEFAULTED):
        raise ProjectError(_("Rapport impossible pour ce projet."))
    period = next((p for p in report_periods(project) if p[0] == period_start), None)
    if period is None:
        raise ProjectError(_("Période invalide."))
    if project.reports.filter(period_start=period_start).exists():
        raise ProjectError(_("Ce rapport a déjà été envoyé."))
    report = FinancialReport(project=project, period_start=period[0], period_end=period[1], due_date=period[2], **data)
    if attachment:
        report.attachment = attachment
    report.save()
    on_time = timezone.now().date() <= period[2]
    # A "missed" event may already exist; a late report recovers part of it.
    record_event(user, "report_on_time" if on_time else "report_late", project=project,
                 note=f"{period[0]:%Y-%m}")
    audit("report.submitted", report, actor=user)
    for h in project.holdings.filter(shares__gt=0).select_related("user"):
        notify(h.user, N_("Nouveau rapport financier"),
               N_("« %(p)s » a publié ses chiffres de %(m)s.") % {"p": project.title, "m": f"{period[0]:%m/%Y}"},
               url=project.get_absolute_url() + "#reports")
    return report


def verify_report(report, by, ok=True, comment=""):
    report.status = FinancialReport.Status.VERIFIED if ok else FinancialReport.Status.FLAGGED
    report.staff_comment = comment
    report.verified_by = by
    report.save()
    if not ok:
        record_event(report.project.owner, "report_flagged", project=report.project, note=comment)
        notify(report.project.owner, N_("Rapport à clarifier"), comment,
               url=f"/projects/{report.project.slug}/manage/", whatsapp=True)
    audit("report.verified" if ok else "report.flagged", report, actor=by)
