from django.db import transaction
from django.utils import timezone

from apps.core.utils import N_, audit, notify

from .models import KYCProfile, User


@transaction.atomic
def approve_kyc(profile: KYCProfile, reviewer, risk_level="low", notes="", request=None):
    profile.status = KYCProfile.Status.APPROVED
    profile.risk_level = risk_level
    profile.review_notes = notes
    profile.rejection_reason = ""
    profile.reviewed_at = timezone.now()
    profile.reviewed_by = reviewer
    profile.save()
    user = profile.user
    user.status = User.Status.APPROVED
    user.approved_at = timezone.now()
    user.full_name = profile.full_name
    user.save(update_fields=["status", "approved_at", "full_name"])
    from apps.trust.services import record_event
    from apps.wallet.models import Wallet

    Wallet.for_user(user)
    record_event(user, "kyc_verified")
    audit("kyc.approved", profile, actor=reviewer, request=request, risk=risk_level)
    notify(user, N_("Votre compte est validé"),
           N_("Vous pouvez maintenant investir et proposer des projets sur Moucharaka."), url="/dashboard/", whatsapp=True, important=True)


@transaction.atomic
def reject_kyc(profile: KYCProfile, reviewer, reason, allow_resubmit=True, request=None):
    profile.status = KYCProfile.Status.RESUBMIT if allow_resubmit else KYCProfile.Status.REJECTED
    profile.rejection_reason = reason
    profile.reviewed_at = timezone.now()
    profile.reviewed_by = reviewer
    profile.save()
    user = profile.user
    user.status = User.Status.NEW if allow_resubmit else User.Status.REJECTED
    user.save(update_fields=["status"])
    audit("kyc.rejected", profile, actor=reviewer, request=request, reason=reason, resubmit=allow_resubmit)
    if allow_resubmit:
        notify(user, N_("Votre dossier d'identité doit être corrigé"), reason, url="/accounts/identity/", whatsapp=True, important=True)
    else:
        notify(user, N_("Votre dossier d'identité a été refusé"), reason, url="/accounts/identity/status/", whatsapp=True,
               important=True)
