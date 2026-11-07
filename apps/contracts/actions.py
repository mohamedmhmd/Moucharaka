"""What each contract does once it is signed. Each action runs the existing service and
returns {"object_ref", "url", "message"}. A refusal from the service cancels the contract."""
from decimal import Decimal

from django.urls import reverse
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.core.utils import N_, notify
from apps.investments import company as C
from apps.investments.models import BuybackOffer, Investment
from apps.investments.services import InvestmentError, invest, submit_settlement
from apps.market.models import Listing
from apps.market.services import MarketError, buy, create_listing
from apps.projects.models import Project
from apps.projects.services import ProjectError, submit_project
from apps.wallet.services import WalletError
from apps.core.utils import fmt_amount


class ActionError(Exception):
    pass


def _project(c):
    return Project.objects.get(pk=c.payload["project"])


def _money(x):
    return fmt_amount(x)


def do_invest(c, user):
    project = _project(c)
    inv = invest(user, project, int(c.payload["shares"]), True)
    if project.is_company and inv.status == Investment.Status.SETTLED:
        msg = _("Contrat signé. Bienvenue parmi les actionnaires : %(n)s part(s) de plus.") % {"n": inv.shares}
    elif project.is_deal:
        msg = _("Contrat signé. %(a)s MRU investis ; vous pouvez annuler pendant 48 h.") % {"a": _money(inv.amount)}
    else:
        msg = _("Contrat signé. %(n)s part(s) réservée(s).") % {"n": inv.shares}
    return {"object_ref": inv.reference, "url": project.get_absolute_url(), "message": msg}


def do_accept_funding(c, user):
    project = _project(c)
    if project.owner_id != user.pk or project.status != Project.Status.FUNDED:
        raise ActionError(_("Ce contrat ne peut être signé que lorsque la collecte est réussie."))
    for staff in User.objects.filter(is_staff=True, is_active=True):
        notify(staff, N_("Contrat de financement signé"), N_("« %(p)s » : les fonds peuvent être libérés.") % {
            "p": project.title}, url=f"/staff/projects/{project.pk}/")
    return {"object_ref": project.reference, "url": reverse("projects:manage", args=[project.slug]),
            "message": _("Contrat signé. Notre équipe libère les fonds dans votre portefeuille.")}


def do_submit_project(c, user):
    project = _project(c)
    submit_project(project, user)
    return {"object_ref": project.reference, "url": reverse("core:dashboard"),
            "message": _("Contrat signé et projet envoyé ! Notre équipe l'étudie, en général sous 5 jours ouvrés.")}


def do_request_issue(c, user):
    p = c.payload
    issue = C.request_issue(_project(c), user, p["shares"], Decimal(p["price"]), p.get("reason", ""))
    return {"object_ref": f"issue:{issue.pk}", "url": reverse("projects:manage", args=[issue.project.slug]) + "#issue",
            "message": _("Contrat signé. Notre équipe vérifie la demande, puis les nouvelles parts seront mises en vente.")}


def do_create_listing(c, user):
    p = c.payload
    listing = create_listing(user, _project(c), int(p["shares"]), Decimal(p["price"]), bool(p["allow_partial"]),
                             p.get("note", ""))
    return {"object_ref": f"listing:{listing.pk}", "url": reverse("market:mine"),
            "message": _("Offre signée et publiée sur le marché.")}


def do_buy_listing(c, user):
    listing = Listing.objects.get(pk=c.payload["listing"])
    trade = buy(user, listing, int(c.payload["shares"]))
    return {"object_ref": f"trade:{trade.pk}", "url": reverse("core:portfolio"),
            "message": _("Contrat signé : %(n)s part(s) de « %(p)s » achetée(s).") % {
                "n": trade.shares, "p": listing.project.title}}


def do_propose_buyback(c, user):
    p = c.payload
    holder = User.objects.get(pk=p["holder"])
    offer = C.propose_buyback(_project(c), user, holder, p["shares"], Decimal(p["price"]), p.get("message", ""))
    return {"object_ref": f"offer:{offer.pk}", "url": reverse("projects:manage", args=[offer.project.slug]) + "#buyback",
            "message": _("Offre signée et envoyée. Le montant est réservé sur votre portefeuille jusqu'à la réponse.")}


def _offer_url(offer, user):
    if offer.project.owner_id == user.pk:
        return reverse("projects:manage", args=[offer.project.slug]) + "#buyback"
    return reverse("core:portfolio") + "#offers"


def do_counter_buyback(c, user):
    p = c.payload
    offer = BuybackOffer.objects.get(pk=p["offer"])
    C.answer_buyback(offer, user, "counter", p["shares"], Decimal(p["price"]), p.get("message", ""))
    return {"object_ref": f"offer:{offer.pk}", "url": _offer_url(offer, user),
            "message": _("Proposition signée et envoyée.")}


def do_accept_buyback(c, user):
    offer = BuybackOffer.objects.get(pk=c.payload["offer"])
    C.answer_buyback(offer, user, "accept")
    return {"object_ref": f"offer:{offer.pk}", "url": _offer_url(offer, user), "message": _("Contrat signé : rachat conclu.")}


def do_settle(c, user):
    p = c.payload
    st = submit_settlement(_project(c), user, Decimal(p["amount"]), p.get("note", ""))
    return {"object_ref": st.reference, "url": reverse("projects:manage", args=[st.project.slug]) + "#settle",
            "message": _("Acte signé. Notre équipe vérifie le partage puis verse à chaque investisseur sa part.")}


def _guard(fn):
    def run(c, user):
        try:
            return fn(c, user)
        except (InvestmentError, MarketError, ProjectError, WalletError) as e:
            raise ActionError(str(e)) from e
    return run


ACTIONS = {name: _guard(fn) for name, fn in {
    "invest": do_invest, "accept_funding": do_accept_funding, "submit_project": do_submit_project,
    "request_issue": do_request_issue, "create_listing": do_create_listing, "buy_listing": do_buy_listing,
    "propose_buyback": do_propose_buyback, "counter_buyback": do_counter_buyback,
    "accept_buyback": do_accept_buyback, "settle": do_settle,
}.items()}
