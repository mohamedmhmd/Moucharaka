"""Object builders shared by the test-suite and the `seed_demo` command."""
import io
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.accounts.models import KYCProfile, User
from apps.accounts.services import approve_kyc
from apps.core.models import Moughataa, Wilaya
from apps.projects.models import (BoutiqueMonth, BoutiqueProduct, BoutiqueProfile, CompanyPlan, DealPlan, FeePolicy,
                                  Milestone,
                                  Project, ProjectAnswer, ProjectDocument, ProjectImage, ProjectionYear, Question,
                                  Sector, TeamMember, UseOfFunds)
from apps.wallet.services import adjust

_counter = {"phone": 22000000, "nni": 1000000000}


def image_file(name="photo.jpg", color=(40, 60, 140), size=(640, 420), text=None):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    for i in range(0, size[0], 40):
        d.line([(i, 0), (i + size[1] // 2, size[1])], fill=tuple(min(c + 25, 255) for c in color), width=8)
    if text:
        d.text((24, size[1] - 40), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return ContentFile(buf.getvalue(), name=name)


def pdf_file(name="doc.pdf"):
    return ContentFile(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF", name=name)


def next_phone(prefix="2"):
    _counter["phone"] += 1
    return prefix + str(_counter["phone"])[-7:]


def make_user(full_name="Test User", approved=True, phone=None, staff=False, balance=0, password="Moucharaka#2026",
              lang="fr", wilaya_code="NKO"):
    user = User.objects.create_user(phone or next_phone(), password, full_name=full_name, preferred_language=lang,
                                    is_staff=staff, phone_verified_at=timezone.now())
    if approved:
        _counter["nni"] += 1
        w = Wilaya.objects.get(code=wilaya_code)
        m = Moughataa.objects.filter(wilaya=w).first()
        kyc = KYCProfile(
            user=user, full_name=full_name, nni=str(_counter["nni"]), id_type="cni",
            date_of_birth=date(1988, 6, 15), place_of_birth="Nouakchott", gender="m", wilaya=w, moughataa=m,
            address="Ilot K", profession="Commerçant", monthly_income="20-50k", source_of_funds="business",
            experience="informal", status=KYCProfile.Status.SUBMITTED, submitted_at=timezone.now())
        kyc.id_front.save("front.jpg", image_file("front.jpg"), save=False)
        kyc.save()
        user.status = User.Status.PENDING
        user.save(update_fields=["status"])
        approve_kyc(kyc, None)
        user.refresh_from_db()
    if balance:
        adjust(user, Decimal(balance), reason="seed")
    return user


def answer_required(project):
    for q in Question.objects.filter(active=True):
        if not q.applies(project.kind):
            continue
        if q.type == "bool":
            v = True
        elif q.type in ("number", "money"):
            v = "3" if q.type == "number" else "0"
        elif q.type == "choice":
            v = q.choices[0]["value"] if q.choices else ""
        elif q.type == "multi":
            v = [q.choices[0]["value"]] if q.choices else []
        else:
            v = DEMO_ANSWERS.get(q.code, "Réponse détaillée fournie par le porteur lors de l'étude du dossier.")
        ProjectAnswer.objects.update_or_create(project=project, question=q, defaults={"value": v})


DEMO_ANSWERS = {
    "main_customers": "Les familles des ilots voisins, deux écoles privées et les ouvriers du chantier de la route.",
    "differentiation": "Ouvert de 7h à minuit, prix affichés, livraison WhatsApp et crédit encadré pour les habitués.",
    "stress_plan": "Réduire les commandes de produits lents, vendre le surplus aux boutiques voisines et décaler mon salaire.",
    "main_risks": "Hausse des prix du riz importé, vol, concurrence d'un nouveau supermarché. Parades : stock tampon, caméra, fidélité.",
    "boutique_why_location": "Carrefour très passant entre deux écoles et la mosquée du quartier, sans boutique concurrente sur 300 m.",
    "boutique_credit_policy": "Crédit limité à 3 000 MRU par famille, remboursé en fin de mois, noté dans le carnet.",
    "owner_previous_business": "J'ai tenu la boutique de mon oncle à Arafat pendant 4 ans avant d'ouvrir la mienne.",
}


def make_project(owner, kind="boutique", model="moucharaka", target=600_000, title=None, status=None, **extra):
    # Tests and demo data may use a project type that is paused for new applications (e.g. boutiques).
    FeePolicy.objects.filter(kind=kind, financing_model=model).update(is_enabled=True)
    wilaya = Wilaya.objects.get(code=extra.pop("wilaya_code", "NKS"))
    moughataa = Moughataa.objects.filter(wilaya=wilaya).first()
    sector = Sector.objects.get(slug={"boutique": "commerce", "deal": "livestock", "company": "food"}[kind])
    p = Project(
        owner=owner, kind=kind, financing_model=model, title=title or f"Projet {kind}", sector=sector,
        tagline=extra.pop("tagline", "Développer une activité rentable et transparente pour la communauté."),
        description=extra.pop("description", "Présentation complète du projet. " * 20),
        wilaya=wilaya, moughataa=moughataa, neighborhood=extra.pop("neighborhood", "Carrefour"),
        target_amount=Decimal(target), share_price=Decimal(extra.pop("share_price", 1000)),
        duration_months=extra.pop("duration_months", 24), campaign_days=30,
        owner_contribution=Decimal(extra.pop("owner_contribution", 100_000)))
    if model == "moucharaka":
        p.investor_profit_share_pct = Decimal(extra.pop("profit_share", 40))
        p.projected_annual_return_pct = Decimal(extra.pop("projected", 18))
        p.exit_mode = extra.pop("exit_mode", Project.Exit.DIMINISHING)
        p.distribution_frequency = extra.pop("frequency", Project.Frequency.MONTHLY)
    else:
        p.margin_pct = Decimal(extra.pop("margin", 12))
        p.repayment_mode = extra.pop("repayment", Project.Repayment.MONTHLY)
        p.guarantee = "Caution personnelle et nantissement du stock."
    for k, v in extra.items():
        setattr(p, k, v)
    p.cover.save("cover.jpg", image_file("cover.jpg", color=(28, 37, 89)), save=False)
    p.save()
    UseOfFunds.objects.create(project=p, category="stock", label="Achat de marchandises", amount=Decimal(target) * Decimal("0.7"))
    UseOfFunds.objects.create(project=p, category="equipment", label="Réfrigérateur et étagères", amount=Decimal(target) * Decimal("0.3"))
    doc = ProjectDocument(project=p, kind="registration", title="Patente 2026")
    doc.file.save("patente.pdf", pdf_file(), save=False)
    doc.save()
    for i in range(3):
        ProjectImage.objects.create(project=p, image=image_file(f"img{i}.jpg", color=(11 + i * 30, 122, 75)))
    if kind == "boutique":
        make_boutique(p)
    elif kind == "company":
        CompanyPlan.objects.create(
            project=p, legal_form="sarl", stage="first_sales", problem="Pas de pain complet à Nouadhibou.",
            solution="Boulangerie artisanale.", target_customers="Familles et hôtels.", competitors="Boulangeries industrielles.",
            advantage="Qualité, livraison matinale.", revenue_model="Vente au comptoir et abonnements hôtels.",
            go_to_market="Abonnements, réseaux sociaux.", key_risks="Prix de la farine.", breakeven_month=8, jobs_created=6)
        TeamMember.objects.create(project=p, name="Aminetou", role="Gérante", years_experience=6)
        for y in (1, 2, 3):
            ProjectionYear.objects.create(project=p, year=y, revenue=Decimal(900_000 * y), expenses=Decimal(700_000 * y))
        Milestone.objects.create(project=p, title="Achat du four", due_date=date.today() + timedelta(days=60))
        Milestone.objects.create(project=p, title="Ouverture", due_date=date.today() + timedelta(days=120))
    else:
        DealPlan.objects.create(
            project=p, operation="livestock", goods_description="120 moutons de race Ladoum croisée pour la Tabaski.",
            supplier="Marché au bétail de Kiffa", purchase_cost=Decimal(target) * Decimal("0.92"),
            other_costs=Decimal(target) * Decimal("0.08"), expected_sale_value=Decimal(target) * Decimal("1.30"),
            cycle_days=75, buyer_identified=True, buyer_details="Revendeurs du marché de Sebkha.", previous_cycles=3,
            collateral="Le troupeau lui-même, assuré.", collateral_value=Decimal(target))
    answer_required(p)
    if status:
        p.status = status
        p.save()
    return p


def make_boutique(p, revenue=Decimal("420000")):
    BoutiqueProfile.objects.create(
        project=p, shop_name=p.title, category="grocery", premises="rented", monthly_rent=Decimal("15000"),
        surface_m2=24, storage_m2=8, location_type="residential", landmark="Face à la mosquée Ibn Abbas",
        competitors_nearby=2, days_open=7, staff_count=1, customers_per_day=140, average_basket=Decimal("100"),
        gross_margin_pct=Decimal("18"), salaries=Decimal("8000"), owner_draw=Decimal("12000"),
        utilities=Decimal("4500"), transport=Decimal("3000"), taxes=Decimal("1000"), other_costs=Decimal("1500"),
        inventory_value=Decimal("260000"), equipment_value=Decimal("90000"), cash_on_hand=Decimal("20000"),
        customer_credit=Decimal("38000"), supplier_debt=Decimal("25000"), cash_sales_pct=60, mobile_money_pct=30,
        credit_sales_pct=10, main_suppliers="Grossistes du marché Capitale", supply_origin="Nouakchott, Dakar",
        keeps_books=True, has_trade_register=True, has_fridge=True, energy="somelec",
        seasonality="Pic pendant le Ramadan et la rentrée scolaire.",
        growth_plan="Doubler le stock de produits de base et ajouter un congélateur pour les produits frais.",
        expected_revenue_uplift_pct=Decimal("25"), latitude=Decimal("18.0504"), longitude=Decimal("-15.9512"))
    today = date.today().replace(day=1)
    rnd = random.Random(p.pk)
    for i in range(12, 0, -1):
        m = today.month - i
        y = today.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        season = Decimal("1.25") if m in (3, 4, 9) else Decimal("1")
        rev = (revenue * season * Decimal(str(rnd.uniform(0.9, 1.1)))).quantize(Decimal("1"))
        BoutiqueMonth.objects.create(project=p, month=date(y, m, 1), revenue=rev, purchases=(rev * Decimal("0.8")).quantize(Decimal("1")))
    for name, unit, buy, sell, qty in [("Riz brisé 50 kg", "sac", 1180, 1250, 90), ("Huile 20 L", "bidon", 1350, 1450, 40),
                                       ("Sucre 50 kg", "sac", 1500, 1580, 35), ("Lait en poudre", "boîte", 95, 120, 600),
                                       ("Thé vert", "paquet", 30, 40, 900), ("Pain", "unité", 8, 10, 3000)]:
        BoutiqueProduct.objects.create(project=p, name=name, unit=unit, buy_price=buy, sell_price=sell, monthly_units=qty)
