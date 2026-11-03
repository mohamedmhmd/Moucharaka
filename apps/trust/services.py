"""Trust score: 0 – 1000, recomputed from observable behaviour.

Five components, each with a ceiling, so no single factor dominates:

    identity            150  KYC approved, account age
    repayment           350  share of installments / distributions paid on time; defaults
    reporting           200  share of financial reports delivered on time
    investor feedback   200  Bayesian average of investor reviews
    outcomes            100  projects completed vs defaulted, campaigns funded

Users without any track record get half of the behavioural components
(neutral prior) and the grade "N" (new) so investors can tell the difference
between "no history" and "good history".
"""
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum

from .models import Review, TrustEvent, TrustScore

EVENT_POINTS = {
    "kyc_verified": 0, "campaign_funded": 10, "campaign_failed": -5,
    "report_on_time": 3, "report_late": -4, "report_missed": -12, "report_flagged": -15,
    "payment_on_time": 6, "payment_late": -10, "installment_overdue": -15, "default": -150,
    "project_completed": 30, "buyback": 8, "update_posted": 1, "manual": 0,
}

GRADE_THRESHOLDS = [(850, "A+"), (750, "A"), (650, "B"), (550, "C"), (450, "D"), (0, "E")]
REVIEW_PRIOR_MEAN, REVIEW_PRIOR_WEIGHT = 3.5, 5


def record_event(user, kind, project=None, note="", points=None, is_public=True, recompute=True):
    ev = TrustEvent.objects.create(user=user, kind=kind, project=project, note=note[:255],
                                   points=EVENT_POINTS.get(kind, 0) if points is None else points,
                                   is_public=is_public)
    if recompute:
        compute_score(user)
    return ev


def _ratio(good, total, prior=0.5):
    return prior if total == 0 else good / total


def compute_score(user):
    from apps.projects.models import FinancialReport, Installment, Project

    ev = TrustEvent.objects.filter(user=user)
    counts = dict(ev.values_list("kind").annotate(n=Count("id")))
    comp = {}

    # Identity
    identity = 0
    kyc = getattr(user, "kyc", None)
    if user.is_approved:
        identity += 100
    from django.utils import timezone

    months = (timezone.now() - user.date_joined).days / 30
    identity += min(50, int(months * 50 / 12))
    comp["identity"] = identity

    # Repayment (installments + timely distributions)
    inst = Installment.objects.filter(project__owner=user)
    paid_on_time = counts.get("payment_on_time", 0)
    late = counts.get("payment_late", 0)
    overdue_now = inst.filter(status__in=["late", "defaulted"]).count()
    total_pay = paid_on_time + late + overdue_now
    defaults = counts.get("default", 0)
    rep = _ratio(paid_on_time, total_pay) * 350 - defaults * 150
    comp["repayment"] = int(max(0, min(350, rep)))

    # Reporting
    on_time = counts.get("report_on_time", 0)
    late_r = counts.get("report_late", 0)
    missed = counts.get("report_missed", 0)
    flagged = counts.get("report_flagged", 0)
    total_r = on_time + late_r + missed
    reporting = _ratio(on_time + 0.4 * late_r, total_r) * 200 - flagged * 20
    comp["reporting"] = int(max(0, min(200, reporting)))

    # Investor feedback (Bayesian average keeps 1 review from dominating)
    agg = Review.objects.filter(owner=user, is_hidden=False).aggregate(
        n=Count("id"), c=Avg("communication"), t=Avg("transparency"), m=Avg("commitments"))
    n = agg["n"] or 0
    if n:
        raw = ((agg["c"] or 0) + (agg["t"] or 0) + (agg["m"] or 0)) / 3
        bayes = (REVIEW_PRIOR_MEAN * REVIEW_PRIOR_WEIGHT + raw * n) / (REVIEW_PRIOR_WEIGHT + n)
    else:
        bayes = REVIEW_PRIOR_MEAN
    comp["feedback"] = int((bayes - 1) / 4 * 200)
    comp["reviews_count"] = n

    # Outcomes
    projects = Project.objects.filter(owner=user)
    completed = projects.filter(status="completed").count()
    defaulted = projects.filter(status="defaulted").count()
    funded = counts.get("campaign_funded", 0)
    outcomes = 50 + completed * 25 + min(funded, 4) * 5 - defaulted * 60 - counts.get("campaign_failed", 0) * 5
    comp["outcomes"] = int(max(0, min(100, outcomes)))

    manual = ev.filter(kind="manual").aggregate(s=Sum("points"))["s"] or 0
    comp["manual"] = manual

    has_track = bool(total_pay or total_r or n or completed or defaulted)
    score = int(max(0, min(1000, sum(v for k, v in comp.items() if k != "reviews_count"))))
    grade = "N" if not has_track else next(g for t, g in GRADE_THRESHOLDS if score >= t)

    reports = FinancialReport.objects.filter(project__owner=user)
    comp["stats"] = {
        "reports_total": reports.count(),
        "reports_on_time": on_time,
        "payments_on_time": paid_on_time,
        "payments_late": late + overdue_now,
        "projects_completed": completed,
        "projects_defaulted": defaulted,
        "distributed_total": str(
            Decimal(projects.aggregate(s=Sum("distributions__net_amount", filter=Q(distributions__status="paid")))["s"] or 0)),
    }
    obj, _c = TrustScore.objects.update_or_create(
        user=user, defaults={"score": score, "grade": grade, "components": comp, "has_track_record": has_track})
    return obj


def get_score(user):
    obj = TrustScore.objects.filter(user=user).first()
    return obj or compute_score(user)


COMPONENT_MAX = {"identity": 150, "repayment": 350, "reporting": 200, "feedback": 200, "outcomes": 100}
