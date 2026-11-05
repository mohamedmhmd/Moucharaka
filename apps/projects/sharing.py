"""Sharing a project: short link by ID, private preview, QR code, printable
poster, interest before launch, and search by name / ID / owner."""
import re
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.core.utils import N_, notify

from .models import Project, ProjectInterest

REF_RE = re.compile(r"^\s*(?:MP)?[-\s]?([0-9A-F]{6})\s*$", re.I)


def can_view(request, project):
    """Public projects, their owner and staff, or anyone holding the private preview key."""
    u = request.user
    if project.is_public or (u.is_authenticated and (u.is_staff or u.pk == project.owner_id)):
        return True
    key = request.GET.get("k") or request.session.get(f"preview_{project.pk}")
    return bool(key) and key == project.preview_token and project.status not in ("rejected", "cancelled")


def share_url(request, project, private=False):
    return request.build_absolute_uri(project.get_share_path(private=private))


def share_context(request, project):
    u = request.user
    is_manager = u.is_authenticated and (u.is_staff or u.pk == project.owner_id)
    private = is_manager and not project.is_public
    url = share_url(request, project, private=private)
    terms = ""
    if project.is_mourabaha and project.margin_pct is not None:
        terms = _("marge fixe de %(m)s %%") % {"m": f"{project.margin_pct:g}"}
    elif project.is_moucharaka and project.projected_annual_return_pct is not None:
        terms = _("rendement potentiel ~%(r)s %%") % {"r": f"{project.projected_annual_return_pct:g}"}
    # Optional details are left out when the owner has not filled them in
    head = f"{project.title} — {project.tagline}" if project.tagline else project.title
    if project.is_deal:
        details = [_("objectif %(t)s MRU") % {"t": f"{project.target_amount or 0:,.0f}".replace(",", " ")}]
    else:
        details = [_("Parts dès %(p)s MRU") % {"p": f"{project.share_price:,.0f}".replace(",", " ")}]
    if terms:
        details.append(terms)
    text = _("%(head)s. %(details)s. Réf. %(ref)s : %(url)s") % {
        "head": head, "details": ", ".join(str(d) for d in details), "ref": project.reference, "url": url}
    return {"share_url": url, "share_text": text, "share_private": private,
            "whatsapp_url": "https://wa.me/?text=" + quote(text)}


def short_link(request, ref):
    """/s/MP-3FA9C1/ → project page. Keeps the preview key for drafts."""
    m = REF_RE.match(ref)
    if not m:
        raise Http404
    project = get_object_or_404(Project, reference="MP-" + m.group(1).upper())
    key = request.GET.get("k")
    if key and key == project.preview_token:
        request.session[f"preview_{project.pk}"] = key
    if not can_view(request, project):
        raise Http404
    Project.objects.filter(pk=project.pk).update(shares_count=F("shares_count") + 1)
    return redirect(project.get_absolute_url())


@cache_control(max_age=3600)
def qr_svg(request, slug):
    project = get_object_or_404(Project, slug=slug)
    if not can_view(request, project):
        raise Http404
    u = request.user
    private = u.is_authenticated and (u.is_staff or u.pk == project.owner_id) and not project.is_public
    img = qrcode.make(share_url(request, project, private=private), image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=10, border=2)
    return HttpResponse(img.to_string(encoding="unicode"), content_type="image/svg+xml")


def poster(request, slug):
    """Printable A4 poster for the shop window: title, terms, QR code, short link."""
    project = get_object_or_404(Project.objects.select_related("moughataa", "wilaya"), slug=slug)
    if not can_view(request, project):
        raise Http404
    ctx = {"project": project, **share_context(request, project)}
    if hasattr(project, "boutique"):
        ctx["boutique"] = project.boutique
    return render(request, "projects/poster.html", ctx)


@require_POST
@login_required
def register_interest(request, slug):
    project = get_object_or_404(Project, slug=slug)
    if not can_view(request, project) or project.owner_id == request.user.pk:
        raise Http404
    if project.status not in ("draft", "submitted", "changes", "funding"):
        messages.error(request, _("Ce projet n'accepte plus d'intentions."))
        return redirect(project.get_absolute_url())
    if "remove" in request.POST:
        ProjectInterest.objects.filter(project=project, user=request.user).delete()
        messages.success(request, _("Intention retirée."))
        return redirect(project.get_absolute_url() + "#share")
    try:
        amount = int(request.POST.get("amount") or 0) or None
    except ValueError:
        amount = None
    obj, created = ProjectInterest.objects.update_or_create(
        project=project, user=request.user,
        defaults={"amount": amount, "note": (request.POST.get("note") or "")[:200]})
    if created:
        notify(project.owner, N_("Nouvelle intention d'investissement"),
               N_("%(n)s souhaite investir dans « %(p)s ».") % {"n": request.user.display_name, "p": project.title},
               url=f"/projects/{project.slug}/manage/#interests")
    messages.success(request, _("C'est noté. Nous vous préviendrons sur WhatsApp dès l'ouverture de la collecte."))
    return redirect(project.get_absolute_url() + "#share")


def notify_interested(project):
    """Called when a campaign opens."""
    from django.utils import timezone

    for it in project.interests.filter(notified_at__isnull=True).select_related("user"):
        notify(it.user, N_("La collecte est ouverte"),
               N_("« %(p)s », que vous suivez, accepte maintenant les investissements.") % {"p": project.title},
               url=project.get_absolute_url(), whatsapp=True)
        it.notified_at = timezone.now()
        it.save(update_fields=["notified_at"])


# ---------------------------------------------------------------- search

def search_projects(q, user=None):
    qs = Project.objects.filter(status__in=Project.PUBLIC_STATUSES)
    if user is not None and user.is_authenticated:
        qs = Project.objects.filter(Q(status__in=Project.PUBLIC_STATUSES) | Q(owner=user))
    words = [w for w in q.split() if w]
    for w in words:
        qs = qs.filter(
            Q(title__icontains=w) | Q(tagline__icontains=w) | Q(reference__icontains=w)
            | Q(boutique__shop_name__icontains=w) | Q(neighborhood__icontains=w)
            | Q(owner__full_name__icontains=w) | Q(owner__kyc__full_name__icontains=w)
            | Q(owner__public_id__iexact=w) | Q(sector__name_fr__icontains=w) | Q(sector__name_ar__icontains=w)
            | Q(moughataa__name_fr__icontains=w) | Q(moughataa__name_ar__icontains=w)
            | Q(wilaya__name_fr__icontains=w) | Q(wilaya__name_ar__icontains=w))
    return qs.select_related("sector", "wilaya", "moughataa", "owner").distinct().order_by("-campaign_start", "-created_at")


def search_members(q):
    words = [w for w in q.split() if len(w) >= 2]
    if not words:
        return User.objects.none()
    qs = User.objects.filter(is_active=True, projects__status__in=Project.PUBLIC_STATUSES)
    for w in words:
        qs = qs.filter(Q(full_name__icontains=w) | Q(kyc__full_name__icontains=w) | Q(public_id__iexact=w))
    return qs.annotate(n_projects=Count("projects", distinct=True)).select_related("trust").distinct()[:12]


def search(request):
    q = (request.GET.get("q") or "").strip()[:80]
    ctx = {"q": q, "projects": [], "members": []}
    if q:
        m = REF_RE.match(q)
        if m:
            project = Project.objects.filter(reference="MP-" + m.group(1).upper()).first()
            if project and can_view(request, project):
                return redirect(project.get_absolute_url())
        ctx["projects"] = list(search_projects(q, request.user)[:30])
        ctx["members"] = list(search_members(q))
    return render(request, "projects/search.html", ctx)
