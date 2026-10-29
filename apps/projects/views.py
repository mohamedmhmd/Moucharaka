import json
import mimetypes
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.decorators import approved_required
from apps.core.models import PlatformSettings
from apps.core.utils import N_, notify
from apps.investments.models import Holding, Investment
from apps.investments.services import (InvestmentError, buyback, cancel_investment, invest,
                                       max_shares_for, pay_installment, pay_profit_distribution)
from apps.market.models import Listing, Trade
from apps.trust.forms import ReviewForm
from apps.trust.models import Review
from apps.trust.services import get_score, record_event
from apps.wallet.models import Transaction, Wallet
from apps.wallet.services import WalletError, collect_fee, post

from . import forms as F_
from .models import (FeePolicy, FinancialReport, Installment, Kind, Project, ProjectDocument, ProjectImage,
                     ProjectQuestion)
from .services import ProjectError, checklist, pending_periods, submit_project, submit_report

# ------------------------------------------------------------------ public pages


def explore(request):
    form = F_.FilterForm(request.GET or None)
    qs = Project.objects.select_related("sector", "wilaya", "moughataa", "owner").filter(
        status__in=["funding", "funded", "active"])
    if form.is_valid():
        d = form.cleaned_data
        status = d.get("status")
        if status == "all":
            qs = Project.objects.select_related("sector", "wilaya", "moughataa", "owner").filter(
                status__in=Project.PUBLIC_STATUSES)
        elif status:
            qs = qs.model.objects.select_related("sector", "wilaya", "moughataa", "owner").filter(status=status)
        if d.get("q"):
            qs = qs.filter(Q(title__icontains=d["q"]) | Q(tagline__icontains=d["q"]) |
                           Q(boutique__shop_name__icontains=d["q"]) | Q(neighborhood__icontains=d["q"]))
        if d.get("kind"):
            qs = qs.filter(kind=d["kind"])
        if d.get("model"):
            qs = qs.filter(financing_model=d["model"])
        if d.get("wilaya"):
            qs = qs.filter(wilaya=d["wilaya"])
        if d.get("sector"):
            qs = qs.filter(sector=d["sector"])
        sort = d.get("sort") or "new"
    else:
        sort = "new"
    order = {
        "new": ["-campaign_start", "-created_at"],
        "ending": ["campaign_end"],
        "progress": ["-raised_amount"],
        "return": ["-projected_annual_return_pct", "-margin_pct"],
    }[sort]
    qs = qs.order_by(F("featured_until").desc(nulls_last=True), *order)
    page = Paginator(qs, 12).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "projects/explore.html", {"form": form, "page": page, "querystring": params.urlencode()})


def _can_view(request, project):
    u = request.user
    return project.is_public or (u.is_authenticated and (u.is_staff or u.pk == project.owner_id))


def detail(request, slug):
    project = get_object_or_404(Project.objects.select_related("owner", "sector", "wilaya", "moughataa"), slug=slug)
    if not _can_view(request, project):
        raise Http404
    seen = request.session.setdefault("seen_projects", [])
    if project.pk not in seen and project.is_public:
        Project.objects.filter(pk=project.pk).update(views_count=F("views_count") + 1)
        seen.append(project.pk)
        request.session.modified = True
    u = request.user
    ctx = {"project": project, "owner_score": get_score(project.owner)}
    ctx["is_owner"] = u.is_authenticated and u.pk == project.owner_id
    ctx["can_see_docs"] = u.is_authenticated and (u.is_staff or u.is_approved or ctx["is_owner"])
    ctx["documents"] = project.documents.all() if ctx["is_owner"] or (u.is_authenticated and u.is_staff) else \
        project.documents.filter(visible_to_investors=True)
    ctx["uses"] = project.uses_of_funds.all()
    ctx["uses_total"] = sum((x.amount for x in ctx["uses"]), Decimal("0"))
    # Questionnaire answers, grouped by section, public only
    sections = {}
    for a in project.answers.select_related("question__section").filter(question__is_public=True,
                                                                          question__active=True).order_by(
            "question__section__order", "question__order"):
        if a.value not in (None, "", []):
            sections.setdefault(a.question.section, []).append(a)
    ctx["answer_sections"] = list(sections.items())
    # Kind-specific model
    if project.kind == Kind.BOUTIQUE and hasattr(project, "boutique"):
        b = project.boutique
        months = list(project.boutique_months.all())
        ctx.update(boutique=b, scenarios=b.scenarios(), indicators=b.indicators(),
                   products=project.boutique_products.all(), months=months)
        ctx["sim"] = json.dumps({
            "revenue": float(b.declared_monthly_revenue), "margin": float(b.gross_margin_pct),
            "fixed": float(b.fixed_costs), "uplift": float(b.expected_revenue_uplift_pct),
            "share": float(project.investor_profit_share_pct or 0), "capital": float(project.target_amount),
            "sharePrice": float(project.share_price), "model": project.financing_model,
            "marginPct": float(project.margin_pct or 0), "months": project.duration_months,
        })
    elif project.kind == Kind.COMPANY and hasattr(project, "company"):
        ctx.update(company=project.company, team=project.team.all(), projections=project.projections.all(),
                   milestones=project.milestones.all())
    elif hasattr(project, "deal"):
        ctx.update(deal=project.deal, milestones=project.milestones.all())
    # Chart: declared history then actual reports
    reports = list(project.reports.order_by("period_start"))
    chart = {"labels": [], "declared": [], "actual": [], "profit": []}
    for m in ctx.get("months", []):
        chart["labels"].append(m.month.strftime("%m/%y"))
        chart["declared"].append(float(m.revenue))
        chart["actual"].append(None)
        chart["profit"].append(None)
    for r in reports:
        chart["labels"].append(r.period_start.strftime("%m/%y"))
        chart["declared"].append(None)
        chart["actual"].append(float(r.revenue))
        chart["profit"].append(float(r.net_profit))
    ctx["chart"] = json.dumps(chart)
    ctx["reports"] = reports[::-1]
    ctx["distributions"] = project.distributions.all()
    ctx["installments"] = project.installments.all()
    ctx["updates"] = project.updates.all()[:10]
    ctx["questions"] = project.questions.exclude(answer="").select_related("asker")[:20]
    ctx["listings"] = Listing.objects.filter(project=project, status="active").select_related("seller")[:10]
    trades = list(Trade.objects.filter(project=project).order_by("created_at").values_list("created_at", "price_per_share"))
    ctx["price_history"] = json.dumps({"labels": [t[0].strftime("%d/%m/%y") for t in trades],
                                       "prices": [float(t[1]) for t in trades], "nominal": float(project.share_price)})
    ctx["images"] = project.images.all()
    if u.is_authenticated:
        ctx["holding"] = Holding.objects.filter(user=u, project=project).first()
        ctx["my_investments"] = Investment.objects.filter(investor=u, project=project).exclude(status="cancelled")
        ctx["is_favorite"] = project.favorited_by.filter(user=u).exists()
        if project.status == Project.Status.FUNDING and u.is_approved and not ctx["is_owner"]:
            ctx["invest_form"] = F_.InvestForm(initial={"shares": project.min_shares})
            ctx["max_shares"] = max_shares_for(u, project)
            ctx["wallet"] = Wallet.for_user(u)
        invested = Investment.objects.filter(investor=u, project=project, status="settled").exists() or \
            Holding.objects.filter(user=u, project=project, shares__gt=0).exists()
        if invested and project.status in ("active", "completed", "defaulted") and \
                not Review.objects.filter(project=project, reviewer=u).exists():
            ctx["review_form"] = ReviewForm()
        ctx["question_form"] = F_.QuestionForm() if u.is_approved and not ctx["is_owner"] else None
    ctx["reviews"] = Review.objects.filter(project=project, is_hidden=False).select_related("reviewer")
    ctx["settings"] = PlatformSettings.get()
    return render(request, "projects/detail.html", ctx)


@require_POST
@approved_required
def invest_view(request, slug):
    project = get_object_or_404(Project, slug=slug)
    form = F_.InvestForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Indiquez le nombre de parts et confirmez avoir compris les risques."))
        return redirect(project.get_absolute_url() + "#invest")
    amount = form.cleaned_data["shares"] * project.share_price
    wallet = Wallet.for_user(request.user)
    if wallet.balance < amount:
        messages.warning(request, _("Il vous manque %(m)s MRU. Alimentez votre portefeuille puis revenez investir.") % {
            "m": f"{amount - wallet.balance:,.0f}".replace(",", " ")})
        return redirect(reverse("wallet:deposit") + f"?amount={int(amount - wallet.balance)}&next={project.get_absolute_url()}")
    try:
        inv = invest(request.user, project, form.cleaned_data["shares"], form.cleaned_data["risk"])
    except InvestmentError as e:
        messages.error(request, str(e))
        return redirect(project.get_absolute_url() + "#invest")
    messages.success(request, _("Merci ! %(n)s part(s) réservée(s). Vos fonds restent bloqués jusqu'à la fin de la collecte; vous pouvez annuler pendant 48 h.") % {"n": inv.shares})
    return redirect("core:portfolio")


@require_POST
@approved_required
def cancel_investment_view(request, pk):
    inv = get_object_or_404(Investment, pk=pk, investor=request.user)
    try:
        cancel_investment(inv, request.user)
        messages.success(request, _("Souscription annulée, fonds débloqués."))
    except InvestmentError as e:
        messages.error(request, str(e))
    return redirect("core:portfolio")


@require_POST
@approved_required
def toggle_favorite(request, slug):
    project = get_object_or_404(Project, slug=slug)
    fav = project.favorited_by.filter(user=request.user).first()
    if fav:
        fav.delete()
    else:
        project.favorited_by.create(user=request.user)
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"favorite": not fav})
    return redirect(project.get_absolute_url())


@require_POST
@approved_required
def ask_question(request, slug):
    project = get_object_or_404(Project, slug=slug)
    form = F_.QuestionForm(request.POST)
    if form.is_valid() and request.user.pk != project.owner_id:
        q = form.save(commit=False)
        q.project, q.asker = project, request.user
        q.save()
        notify(project.owner, N_("Nouvelle question d'un investisseur"), q.question[:120],
               url=reverse("projects:manage", args=[slug]) + "#questions")
        messages.success(request, _("Question envoyée au porteur. La réponse sera publique."))
    return redirect(project.get_absolute_url() + "#qa")


@require_POST
@approved_required
def review_view(request, slug):
    from apps.trust.services import compute_score

    project = get_object_or_404(Project, slug=slug)
    allowed = Holding.objects.filter(user=request.user, project=project, shares__gt=0).exists() or \
        Investment.objects.filter(investor=request.user, project=project, status="settled").exists()
    if not allowed or Review.objects.filter(project=project, reviewer=request.user).exists():
        raise Http404
    form = ReviewForm(request.POST)
    if form.is_valid():
        r = form.save(commit=False)
        r.project, r.reviewer, r.owner = project, request.user, project.owner
        r.save()
        compute_score(project.owner)
        messages.success(request, _("Merci pour votre avis : il compte dans le score du porteur."))
    else:
        messages.error(request, _("Notez les trois critères de 1 à 5."))
    return redirect(project.get_absolute_url() + "#reviews")


def _serve_private(f, download_name=None):
    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    resp = FileResponse(f.open("rb"), content_type=ctype)
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


def document(request, pk):
    doc = get_object_or_404(ProjectDocument.objects.select_related("project"), pk=pk)
    u = request.user
    if not u.is_authenticated:
        raise Http404
    ok = u.is_staff or u.pk == doc.project.owner_id or (u.is_approved and doc.visible_to_investors and doc.project.is_public)
    if not ok:
        raise Http404
    return _serve_private(doc.file)


def report_attachment(request, pk):
    r = get_object_or_404(FinancialReport.objects.select_related("project"), pk=pk)
    u = request.user
    if not u.is_authenticated:
        raise Http404
    holder = Holding.objects.filter(user=u, project=r.project, shares__gt=0).exists()
    if not (u.is_staff or u.pk == r.project.owner_id or holder) or not r.attachment:
        raise Http404
    return _serve_private(r.attachment)


# ------------------------------------------------------------------ creation wizard

STEPS = {
    Kind.BOUTIQUE: ["basics", "terms", "details", "figures", "funds", "questions", "media", "submit"],
    Kind.COMPANY: ["basics", "terms", "details", "figures", "funds", "questions", "media", "submit"],
    Kind.DEAL: ["basics", "terms", "details", "figures", "funds", "questions", "media", "submit"],
}
STEP_LABELS = {
    "basics": _("Présentation"), "terms": _("Conditions"), "details": _("Fiche détaillée"),
    "figures": _("Chiffres"), "funds": _("Utilisation des fonds"), "questions": _("Questionnaire"),
    "media": _("Photos et justificatifs"), "submit": _("Vérifier et envoyer"),
}
FIGURE_LABELS = {Kind.BOUTIQUE: _("Ventes et produits"), Kind.COMPANY: _("Équipe et prévisions"),
                 Kind.DEAL: _("Étapes de l'opération")}


@approved_required
def new_project(request):
    form = F_.StartForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.session["new_project"] = form.cleaned_data
        return redirect("projects:new_basics")
    policies = {(p.kind, p.financing_model): p for p in FeePolicy.objects.all()}
    return render(request, "projects/new_start.html", {"form": form, "policies": policies})


@approved_required
def new_basics(request):
    start = request.session.get("new_project")
    if not start:
        return redirect("projects:new")
    form = F_.BasicsForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.owner = request.user
        p.kind, p.financing_model = start["kind"], start["financing_model"]
        p.target_amount = Decimal("0")
        if p.is_mourabaha:
            p.repayment_mode = Project.Repayment.MONTHLY
        else:
            p.exit_mode = Project.Exit.DIMINISHING
        p.save()
        request.session.pop("new_project", None)
        messages.success(request, _("Brouillon créé. Vous pouvez le compléter à votre rythme."))
        return redirect("projects:edit", slug=p.slug, step="terms")
    return render(request, "projects/wizard.html", {
        "step": "basics", "steps": _steps_nav(None, start["kind"]), "form": form, "start": start,
        "kind_label": dict(Kind.choices)[start["kind"]]})


def _steps_nav(project, kind):
    out = []
    for s in STEPS[kind]:
        label = FIGURE_LABELS[kind] if s == "figures" else STEP_LABELS[s]
        out.append({"key": s, "label": label})
    return out


def _owned_editable(request, slug):
    p = get_object_or_404(Project, slug=slug, owner=request.user)
    if not p.is_editable:
        messages.warning(request, _("Ce projet n'est plus modifiable."))
        target = redirect("core:dashboard") if p.status == Project.Status.SUBMITTED else redirect("projects:manage", slug=slug)
        return None, target
    return p, None


@approved_required
def edit_project(request, slug, step):
    project, resp = _owned_editable(request, slug)
    if resp:
        return resp
    if step not in STEPS[project.kind]:
        raise Http404
    steps = STEPS[project.kind]
    next_step = steps[min(steps.index(step) + 1, len(steps) - 1)]
    ctx = {"project": project, "step": step, "steps": _steps_nav(project, project.kind)}
    post, files = (request.POST, request.FILES) if request.method == "POST" else (None, None)

    def done():
        messages.success(request, _("Enregistré."))
        if "stay" in request.POST:
            return redirect("projects:edit", slug=slug, step=step)
        return redirect("projects:edit", slug=slug, step=next_step)

    if step == "basics":
        form = F_.BasicsForm(post, files, instance=project)
        if post is not None and form.is_valid():
            form.save()
            return done()
        ctx["form"] = form
    elif step == "terms":
        form = F_.TermsForm(post, instance=project)
        if post is not None and form.is_valid():
            form.save()
            return done()
        ctx["form"] = form
        ctx["policy"] = FeePolicy.for_project(project)
    elif step == "details":
        FormCls = {Kind.BOUTIQUE: F_.BoutiqueForm, Kind.COMPANY: F_.CompanyForm, Kind.DEAL: F_.DealForm}[project.kind]
        attr = {Kind.BOUTIQUE: "boutique", Kind.COMPANY: "company", Kind.DEAL: "deal"}[project.kind]
        instance = getattr(project, attr, None)
        form = FormCls(post, instance=instance)
        if post is not None and form.is_valid():
            obj = form.save(commit=False)
            obj.project = project
            obj.save()
            return done()
        ctx["form"] = form
        ctx["map_center"] = project.moughataa
    elif step == "figures":
        if project.kind == Kind.BOUTIQUE:
            formsets = {
                "months": F_.MonthFormSet(post, instance=project, prefix="months"),
                "products": F_.ProductFormSet(post, instance=project, prefix="products"),
            }
            if not project.boutique_months.exists() and post is None:
                today = timezone.now().date().replace(day=1)
                initial = []
                for i in range(12, 0, -1):
                    m = today.month - i
                    y = today.year + (m - 1) // 12
                    m = (m - 1) % 12 + 1
                    initial.append({"month": today.replace(year=y, month=m)})
                MonthFS = F_.inlineformset_factory(
                    Project, F_.BoutiqueMonth, form=F_.MonthFormSet.form, extra=12, can_delete=True)
                formsets["months"] = MonthFS(instance=project, prefix="months", initial=initial)
        elif project.kind == Kind.COMPANY:
            formsets = {
                "team": F_.TeamFormSet(post, instance=project, prefix="team"),
                "projections": F_.ProjectionFormSet(post, instance=project, prefix="proj"),
                "milestones": F_.MilestoneFormSet(post, instance=project, prefix="ms"),
            }
        else:
            formsets = {"milestones": F_.MilestoneFormSet(post, instance=project, prefix="ms")}
        if post is not None:
            if all(fs.is_valid() for fs in formsets.values()):
                for fs in formsets.values():
                    fs.save()
                return done()
        ctx["formsets"] = formsets
    elif step == "funds":
        fs = F_.UseOfFundsFormSet(post, instance=project, prefix="uof")
        if post is not None and fs.is_valid():
            fs.save()
            return done()
        ctx["formset"] = fs
        ctx["uses_total"] = project.uses_of_funds.aggregate(s=Sum("amount"))["s"] or 0
    elif step == "questions":
        form = F_.QuestionnaireForm(project, post)
        if post is not None and form.is_valid():
            form.save()
            return done()
        ctx["form"] = form
    elif step == "media":
        doc_form = F_.DocumentForm(post if post and "doc" in post else None, files if post and "doc" in post else None)
        if post is not None:
            if "doc" in post:
                if doc_form.is_valid():
                    d = doc_form.save(commit=False)
                    d.project = project
                    d.save()
                    messages.success(request, _("Justificatif ajouté."))
                    return redirect("projects:edit", slug=slug, step="media")
            elif "photos" in post:
                imgs = files.getlist("images")
                start = project.images.count()
                for i, f in enumerate(imgs[:12]):
                    if f.content_type and f.content_type.startswith("image/") and f.size <= 8 * 1024 * 1024:
                        ProjectImage.objects.create(project=project, image=f, order=start + i)
                messages.success(request, _("%(n)s photo(s) ajoutée(s).") % {"n": len(imgs[:12])})
                return redirect("projects:edit", slug=slug, step="media")
            elif "delete_image" in post:
                project.images.filter(pk=post.get("delete_image")).delete()
                return redirect("projects:edit", slug=slug, step="media")
            elif "delete_doc" in post:
                project.documents.filter(pk=post.get("delete_doc")).delete()
                return redirect("projects:edit", slug=slug, step="media")
            else:
                return redirect("projects:edit", slug=slug, step=next_step)
        ctx.update(doc_form=doc_form, images=project.images.all(), documents=project.documents.all())
    elif step == "submit":
        if post is not None:
            try:
                submit_project(project, request.user)
            except ProjectError as e:
                messages.error(request, str(e))
                return redirect("projects:edit", slug=slug, step="submit")
            messages.success(request, _("Projet envoyé ! Notre équipe l'étudie, en général sous 5 jours ouvrés."))
            return redirect("core:dashboard")
        ctx["checklist"] = checklist(project)
        ctx["ready"] = all(i["done"] for i in ctx["checklist"])
        ctx["policy"] = FeePolicy.for_project(project)
        ctx["wallet"] = Wallet.for_user(request.user)
    return render(request, "projects/wizard.html", ctx)


@require_POST
@approved_required
def delete_draft(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user, status=Project.Status.DRAFT)
    project.delete()
    messages.success(request, _("Brouillon supprimé."))
    return redirect("core:dashboard")


# ------------------------------------------------------------------ owner workspace


@approved_required
def manage(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    if project.is_editable:
        return redirect("projects:edit", slug=slug, step="basics")
    holdings = project.holdings.filter(shares__gt=0).select_related("user").order_by("-shares")
    pending = pending_periods(project) if project.status in ("active", "defaulted") else []
    ctx = {
        "project": project, "holdings": holdings, "pending_periods": pending,
        "report_form": F_.ReportForm(), "update_form": F_.UpdateForm(), "buyback_form": F_.BuybackForm(),
        "reports": project.reports.all(), "installments": project.installments.all(),
        "open_questions": project.questions.filter(answer=""),
        "investments": project.investments.select_related("investor").exclude(status="cancelled"),
        "wallet": Wallet.for_user(request.user), "settings": PlatformSettings.get(),
        "outstanding": holdings.aggregate(s=Sum("shares"))["s"] or 0,
        "score": get_score(request.user),
    }
    return render(request, "projects/manage.html", ctx)


def _owner_project(request, slug):
    return get_object_or_404(Project, slug=slug, owner=request.user)


@require_POST
@approved_required
def submit_report_view(request, slug):
    project = _owner_project(request, slug)
    form = F_.ReportForm(request.POST, request.FILES)
    try:
        period_start = timezone.datetime.strptime(request.POST.get("period_start", ""), "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, _("Période invalide."))
        return redirect("projects:manage", slug=slug)
    if form.is_valid():
        data = {k: v for k, v in form.cleaned_data.items() if k != "attachment"}
        try:
            submit_report(project, request.user, period_start, data, form.cleaned_data.get("attachment"))
            messages.success(request, _("Rapport publié."))
        except ProjectError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, _("Rapport incomplet : vérifiez les montants."))
    return redirect(reverse("projects:manage", args=[slug]) + "#reports")


@require_POST
@approved_required
def pay_distribution_view(request, slug, report_id):
    project = _owner_project(request, slug)
    report = get_object_or_404(FinancialReport, pk=report_id, project=project)
    try:
        d = pay_profit_distribution(report)
        messages.success(request, _("%(a)s MRU distribués aux investisseurs.") % {"a": f"{d.net_amount:,.0f}"})
    except InvestmentError as e:
        messages.error(request, str(e))
    return redirect(reverse("projects:manage", args=[slug]) + "#reports")


@require_POST
@approved_required
def pay_installment_view(request, slug, inst_id):
    project = _owner_project(request, slug)
    inst = get_object_or_404(Installment, pk=inst_id, project=project)
    try:
        pay_installment(inst)
        messages.success(request, _("Échéance payée. Merci !"))
    except InvestmentError as e:
        messages.error(request, str(e))
    return redirect(reverse("projects:manage", args=[slug]) + "#installments")


@require_POST
@approved_required
def buyback_view(request, slug):
    project = _owner_project(request, slug)
    form = F_.BuybackForm(request.POST)
    if form.is_valid():
        try:
            buyback(project, form.cleaned_data["shares"], form.cleaned_data["price"])
            messages.success(request, _("Rachat effectué."))
        except InvestmentError as e:
            messages.error(request, str(e))
    return redirect(reverse("projects:manage", args=[slug]) + "#buyback")


@require_POST
@approved_required
def post_update(request, slug):
    project = _owner_project(request, slug)
    form = F_.UpdateForm(request.POST, request.FILES)
    if form.is_valid():
        upd = form.save(commit=False)
        upd.project = project
        upd.save()
        record_event(request.user, "update_posted", project=project)
        for h in project.holdings.filter(shares__gt=0).select_related("user"):
            notify(h.user, N_("Nouvelles de « %(p)s »") % {"p": project.title}, upd.title, url=project.get_absolute_url())
        for inv in project.investments.filter(status="held").select_related("investor"):
            notify(inv.investor, N_("Nouvelles de « %(p)s »") % {"p": project.title}, upd.title, url=project.get_absolute_url())
        messages.success(request, _("Message publié."))
    return redirect(reverse("projects:manage", args=[slug]) + "#updates")


@require_POST
@approved_required
def answer_question(request, slug, qid):
    project = _owner_project(request, slug)
    q = get_object_or_404(ProjectQuestion, pk=qid, project=project)
    text = request.POST.get("answer", "").strip()
    if text:
        q.answer, q.answered_at = text[:2000], timezone.now()
        q.save()
        notify(q.asker, N_("Le porteur a répondu à votre question"), text[:120], url=project.get_absolute_url() + "#qa")
    return redirect(reverse("projects:manage", args=[slug]) + "#questions")


@require_POST
@approved_required
def feature_project(request, slug):
    project = _owner_project(request, slug)
    fee = PlatformSettings.get().featured_fee
    if project.status != Project.Status.FUNDING:
        messages.error(request, _("Seule une collecte en cours peut être mise en avant."))
        return redirect("projects:manage", slug=slug)
    try:
        post(Wallet.for_user(request.user), Transaction.Kind.FEATURED_FEE, -fee, project=project)
    except WalletError as e:
        messages.error(request, str(e))
        return redirect("projects:manage", slug=slug)
    collect_fee(Transaction.Kind.FEATURED_FEE, fee, project=project, description=project.title)
    base = max(project.featured_until or timezone.now(), timezone.now())
    project.featured_until = base + timedelta(days=7)
    project.save(update_fields=["featured_until"])
    messages.success(request, _("Projet mis en avant pendant 7 jours."))
    return redirect("projects:manage", slug=slug)

