"""Back-office for the compliance & operations team (staff users).

Django admin stays available for everything; these screens cover the daily
queues with the right information side by side."""
from django import forms
from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import staff_required
from apps.accounts.models import KYCProfile, User
from apps.accounts.services import approve_kyc, reject_kyc
from apps.investments.models import DealSettlement, ShareIssue
from apps.investments.services import (InvestmentError, deal_split, mark_default, refund_campaign, reject_settlement,
                                       release_funds, validate_settlement)
from apps.projects.models import FinancialReport, Installment, Project
from apps.projects.services import (ProjectError, approve_project, checklist, missing_terms, reject_project,
                                    request_changes, verify_report)
from apps.trust.services import get_score
from apps.wallet.models import DepositRequest, Transaction, Wallet, WithdrawalRequest
from apps.wallet.services import WalletError, cancel_withdrawal, confirm_deposit, mark_withdrawal_paid, reject_deposit


class KYCDecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approve", gettext_lazy("Approuver")),
                                          ("resubmit", gettext_lazy("Demander des corrections")),
                                          ("reject", gettext_lazy("Refuser définitivement"))],
                                 widget=forms.RadioSelect)
    risk_level = forms.ChoiceField(choices=KYCProfile.RISK, initial="low", label=gettext_lazy("Niveau de risque"))
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False,
                              label=gettext_lazy("Message à l'utilisateur / notes"))

    def clean(self):
        d = super().clean()
        if d.get("decision") in ("resubmit", "reject") and not d.get("message"):
            self.add_error("message", _("Expliquez ce qui doit être corrigé."))
        return d


class ProjectDecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approve", gettext_lazy("Publier la collecte")),
                                          ("changes", gettext_lazy("Demander des corrections")),
                                          ("reject", gettext_lazy("Refuser"))], widget=forms.RadioSelect)
    risk_grade = forms.ChoiceField(choices=Project.RISK_GRADES, required=False, label=gettext_lazy("Note de risque"))
    public_notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False,
                                   label=gettext_lazy("Avis public de l'équipe (affiché aux investisseurs)"))
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False,
                              label=gettext_lazy("Message au porteur"))


@staff_required
def dashboard(request):
    platform = Wallet.platform()
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    revenue = [{"kind": Transaction.Kind(r["kind"]).label, "total": r["total"]}
               for r in Transaction.objects.filter(wallet=platform, created_at__gte=month_start)
               .values("kind").annotate(total=Sum("amount")).order_by("-total")]
    ctx = {
        "kyc_pending": KYCProfile.objects.filter(status="submitted").count(),
        "projects_pending": Project.objects.filter(status="submitted").count(),
        "funded_pending": Project.objects.filter(status="funded").count(),
        "deposits_pending": DepositRequest.objects.filter(status__in=["proof"]).count(),
        "withdrawals_pending": WithdrawalRequest.objects.filter(status="pending").count(),
        "reports_pending": FinancialReport.objects.filter(status="submitted").count(),
        "settlements_pending": DealSettlement.objects.filter(status="pending").count(),
        "issues_pending": ShareIssue.objects.filter(status="pending").count(),
        "last_backup": _last_backup(),
        "late_installments": Installment.objects.filter(status__in=["late", "defaulted"]).select_related("project")[:20],
        "platform": platform, "revenue": revenue,
        "revenue_total": sum((r["total"] for r in revenue), 0),
        "escrow": Wallet.objects.filter(kind="user").aggregate(s=Sum("held"))["s"] or 0,
        "user_balances": Wallet.objects.filter(kind="user").aggregate(s=Sum("balance"))["s"] or 0,
        "users": User.objects.count(), "approved_users": User.objects.filter(status="approved").count(),
    }
    return render(request, "staff/dashboard.html", ctx)


@staff_required
def kyc_list(request):
    status = request.GET.get("status", "submitted")
    return render(request, "staff/kyc_list.html", {
        "items": KYCProfile.objects.filter(status=status).select_related("user", "wilaya").order_by("submitted_at"),
        "status": status, "statuses": KYCProfile.Status.choices})


@staff_required
def kyc_review(request, pk):
    profile = get_object_or_404(KYCProfile.objects.select_related("user", "wilaya", "moughataa"), pk=pk)
    form = KYCDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if d["decision"] == "approve":
            approve_kyc(profile, request.user, d["risk_level"], d["message"], request=request)
            messages.success(request, _("Dossier approuvé, l'utilisateur est prévenu sur WhatsApp."))
        else:
            reject_kyc(profile, request.user, d["message"], allow_resubmit=d["decision"] == "resubmit", request=request)
            messages.success(request, _("Décision enregistrée et envoyée à l'utilisateur."))
        nxt = KYCProfile.objects.filter(status="submitted").order_by("submitted_at").first()
        return redirect("staff:kyc_review", pk=nxt.pk) if nxt else redirect("staff:kyc_list")
    docs = [(f, KYCProfile._meta.get_field(f).verbose_name, getattr(profile, f))
            for f in ("id_front", "id_back")]
    return render(request, "staff/kyc_review.html", {
        "kyc": profile, "form": form, "flags": profile.automated_checks(), "docs": docs})


@staff_required
def project_list(request):
    status = request.GET.get("status", "submitted")
    return render(request, "staff/project_list.html", {
        "items": Project.objects.filter(status=status).select_related("owner", "wilaya").order_by("submitted_at"),
        "status": status, "statuses": Project.Status.choices})


@staff_required
def project_review(request, pk):
    project = get_object_or_404(Project.objects.select_related("owner", "sector", "wilaya", "moughataa"), pk=pk)
    form = ProjectDecisionForm(request.POST or None, initial={"risk_grade": project.risk_grade or "C",
                                                               "public_notes": project.review_notes})
    if request.method == "POST" and "decision" in request.POST and form.is_valid():
        d = form.cleaned_data
        try:
            if d["decision"] == "approve":
                if not d["risk_grade"]:
                    raise ProjectError(_("Attribuez une note de risque."))
                approve_project(project, request.user, d["risk_grade"], d["public_notes"])
                messages.success(request, _("Collecte publiée."))
            elif d["decision"] == "changes":
                request_changes(project, request.user, d["message"] or _("Merci de compléter votre dossier."))
                messages.success(request, _("Corrections demandées."))
            else:
                reject_project(project, request.user, d["message"] or _("Projet non retenu."))
                messages.success(request, _("Projet refusé."))
        except ProjectError as e:
            messages.error(request, str(e))
        return redirect("staff:project_review", pk=pk)
    ctx = {"project": project, "form": form, "checklist": checklist(project), "missing_terms": missing_terms(project),
           "owner_score": get_score(project.owner),
           "owner_kyc": getattr(project.owner, "kyc", None), "documents": project.documents.all(),
           "other_projects": Project.objects.filter(owner=project.owner).exclude(pk=pk),
           "pending_settlement": project.settlements.filter(status="pending").first(),
           "contracts": project.contracts.exclude(status="pending").select_related("created_by")[:50],
           "funding_contract": project.contracts.filter(kind="funding", status="signed").first()}
    if hasattr(project, "boutique"):
        ctx["indicators"] = project.boutique.indicators()
        ctx["scenarios"] = project.boutique.scenarios()
    return render(request, "staff/project_review.html", ctx)


@require_POST
@staff_required
def project_action(request, pk, action):
    project = get_object_or_404(Project, pk=pk)
    try:
        if action == "release":
            from apps.contracts.services import funding_signed

            if not funding_signed(project):
                messages.error(request, _("Le porteur doit d'abord signer le contrat de financement."))
                return redirect("staff:project_review", pk=pk)
            release_funds(project, by=request.user)
            messages.success(request, _("Fonds libérés vers le porteur."))
        elif action == "refund":
            refund_campaign(project, reason=request.POST.get("reason") or "staff")
            messages.success(request, _("Collecte annulée, investisseurs remboursés."))
        elif action == "default":
            mark_default(project, by=request.user, note=request.POST.get("reason", ""))
            messages.success(request, _("Projet passé en défaut."))
        elif action == "toggle_trading":
            project.trading_enabled = not project.trading_enabled
            project.save(update_fields=["trading_enabled"])
    except (InvestmentError, ProjectError) as e:
        messages.error(request, str(e))
    return redirect("staff:project_review", pk=pk)


@staff_required
def deposits(request):
    if request.method == "POST":
        dep = get_object_or_404(DepositRequest, pk=request.POST.get("id"))
        try:
            if request.POST.get("action") == "confirm":
                confirm_deposit(dep, by=request.user)
                messages.success(request, _("Dépôt %(r)s confirmé.") % {"r": dep.reference})
            else:
                reject_deposit(dep, request.user, request.POST.get("reason") or _("Paiement introuvable."))
        except WalletError as e:
            messages.error(request, str(e))
        return redirect("staff:deposits")
    return render(request, "staff/deposits.html", {
        "items": DepositRequest.objects.filter(status__in=["proof", "pending"]).select_related("user").order_by("-status", "created_at")})


@staff_required
def withdrawals(request):
    if request.method == "POST":
        wr = get_object_or_404(WithdrawalRequest, pk=request.POST.get("id"))
        try:
            if request.POST.get("action") == "paid":
                mark_withdrawal_paid(wr, request.user, request.POST.get("external_ref", ""))
                messages.success(request, _("Retrait %(r)s marqué payé.") % {"r": wr.reference})
            else:
                cancel_withdrawal(wr, by=request.user, reason=request.POST.get("reason") or "", rejected=True)
        except WalletError as e:
            messages.error(request, str(e))
        return redirect("staff:withdrawals")
    return render(request, "staff/withdrawals.html", {
        "items": WithdrawalRequest.objects.filter(status="pending").select_related("user").order_by("created_at")})


@staff_required
def reports(request):
    if request.method == "POST":
        r = get_object_or_404(FinancialReport, pk=request.POST.get("id"))
        verify_report(r, request.user, ok=request.POST.get("action") == "verify", comment=request.POST.get("comment", ""))
        return redirect("staff:reports")
    return render(request, "staff/reports.html", {
        "items": FinancialReport.objects.filter(status="submitted").select_related("project").order_by("submitted_at")})


@staff_required
def settlements(request):
    """One-off operations: the owner sent back one total; check the sharing, then pay everyone."""
    if request.method == "POST":
        st = get_object_or_404(DealSettlement, pk=request.POST.get("id"))
        try:
            if request.POST.get("action") == "validate":
                validate_settlement(st, by=request.user)
                messages.success(request, _("Remboursement validé : chaque investisseur a reçu sa part."))
            else:
                reason = request.POST.get("reason", "").strip()
                if not reason:
                    messages.error(request, _("Indiquez le motif du refus."))
                    return redirect("staff:settlements")
                reject_settlement(st, request.user, reason)
                messages.success(request, _("Remboursement refusé : le montant est rendu au porteur."))
        except InvestmentError as e:
            messages.error(request, str(e))
        return redirect("staff:settlements")
    items = list(DealSettlement.objects.filter(status="pending").select_related("project__owner").order_by("created_at"))
    for st in items:
        st.split = deal_split(st.project, st.amount)
    done = DealSettlement.objects.exclude(status="pending").select_related("project", "decided_by")[:30]
    return render(request, "staff/settlements.html", {"items": items, "done": done})


def _last_backup():
    """Latest backup and whether it is too old (no successful backup for 36 h)."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.models import BackupRun

    last = BackupRun.objects.first()
    last_ok = BackupRun.objects.filter(status="ok").first()
    stale = not last_ok or last_ok.created_at < timezone.now() - timedelta(hours=36)
    return {"run": last, "ok": last_ok, "stale": stale}


@staff_required
def issues(request):
    """Companies asking to put new parts on sale on the same project page."""
    from apps.investments import company as C

    if request.method == "POST":
        issue = get_object_or_404(ShareIssue, pk=request.POST.get("id"))
        try:
            if request.POST.get("action") == "approve":
                C.approve_issue(issue, request.user)
                messages.success(request, _("Émission validée : les nouvelles parts sont en vente."))
            else:
                reason = request.POST.get("reason", "").strip()
                if not reason:
                    messages.error(request, _("Indiquez le motif du refus."))
                    return redirect("staff:issues")
                C.reject_issue(issue, request.user, reason)
                messages.success(request, _("Émission refusée."))
        except InvestmentError as e:
            messages.error(request, str(e))
        return redirect("staff:issues")
    items = list(ShareIssue.objects.filter(status="pending").select_related("project__owner").order_by("created_at"))
    for it in items:
        it.outstanding = C.outstanding_shares(it.project)
        it.after = it.outstanding + it.shares
    done = ShareIssue.objects.exclude(status="pending").select_related("project", "decided_by")[:30]
    return render(request, "staff/issues.html", {"items": items, "done": done})


KYC_REMINDER = {
    "title_ar": "وثّق هويتك",
    "body_ar": "حسابك في مشاركة شبه جاهز. وثّق هويتك في دقيقتين لتتمكن من الاستثمار وسحب أموالك.",
    "title_fr": "Vérifiez votre identité",
    "body_fr": "Votre compte Moucharaka est presque prêt. Vérifiez votre identité en 2 minutes pour pouvoir "
               "investir et retirer votre argent.",
    "url": "/accounts/identity/",
}


class BroadcastForm(forms.ModelForm):
    class Meta:
        from apps.core.models import Broadcast

        model = Broadcast
        fields = ["audience", "title_ar", "body_ar", "title_fr", "body_fr", "url", "whatsapp", "include_opted_out"]
        widgets = {"body_ar": forms.Textarea(attrs={"rows": 3, "dir": "rtl"}),
                   "body_fr": forms.Textarea(attrs={"rows": 3, "dir": "ltr"}),
                   "title_ar": forms.TextInput(attrs={"dir": "rtl"}), "title_fr": forms.TextInput(attrs={"dir": "ltr"}),
                   "url": forms.TextInput(attrs={"dir": "ltr", "placeholder": "/accounts/identity/"})}

    def clean(self):
        d = super().clean()
        if not d.get("whatsapp"):
            d["include_opted_out"] = False
        return d

    def clean_url(self):
        url = self.cleaned_data["url"].strip()
        if url and (not url.startswith("/") or url.startswith("//")):
            raise forms.ValidationError(_("Un lien du site, qui commence par / (ex. /accounts/identity/)."))
        return url


@staff_required
def broadcasts(request):
    """Send a message to a group of members: in-app for everyone, WhatsApp copy for those who accept it."""
    from apps.core.broadcast import audience_users, create_broadcast, send_whatsapp_batch
    from apps.core.models import Broadcast

    if request.method == "POST" and request.POST.get("continue"):
        b = get_object_or_404(Broadcast, pk=request.POST["continue"])
        left = send_whatsapp_batch(b)
        messages.success(request, _("WhatsApp : %(s)s envoyés, %(f)s échecs, %(l)s restants.")
                         % {"s": b.whatsapp_sent, "f": b.whatsapp_failed, "l": left})
        return redirect("staff:broadcasts")
    form = BroadcastForm(request.POST or None, initial={"audience": Broadcast.Audience.KYC_TODO, **KYC_REMINDER})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        b = create_broadcast(by=request.user, **d)
        if not b.recipients:
            messages.warning(request, _("Aucun membre dans ce groupe : rien n'a été envoyé."))
            return redirect("staff:broadcasts")
        left = send_whatsapp_batch(b) if b.whatsapp else 0
        msg = _("Notification envoyée à %(n)s membre(s).") % {"n": b.recipients}
        if b.whatsapp:
            msg += " " + _("WhatsApp : %(s)s envoyés, %(f)s échecs, %(l)s restants.") % {
                "s": b.whatsapp_sent, "f": b.whatsapp_failed, "l": left}
        messages.success(request, msg)
        return redirect("staff:broadcasts")
    counts = {a: audience_users(a).count() for a, _label in Broadcast.Audience.choices}
    return render(request, "staff/broadcasts.html", {
        "form": form, "counts": counts, "audiences": Broadcast.Audience.choices,
        "history": Broadcast.objects.select_related("created_by")[:20]})
