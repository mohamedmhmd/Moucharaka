from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.core.factories import image_file, make_user, pdf_file
from apps.core.models import Moughataa
from apps.projects.models import Project, Question, Sector


def img(name="p.jpg"):
    return SimpleUploadedFile(name, image_file(name).read(), content_type="image/jpeg")


class WizardTests(TestCase):
    """An owner builds a boutique project through every wizard step and submits it."""

    def test_full_wizard(self):
        owner = make_user("Owner Wizard", balance=5_000)
        c = self.client
        c.force_login(owner)
        r = c.post("/fr/projects/new/", {"kind": "boutique", "financing_model": "moucharaka"})
        self.assertRedirects(r, "/fr/projects/new/details/")
        m = Moughataa.objects.filter(wilaya__code="NKS").first()
        r = c.post("/fr/projects/new/details/", {
            "title": "Épicerie Test", "tagline": "Une épicerie de quartier qui veut grandir.",
            "description": "Description complète. " * 30, "sector": Sector.objects.get(slug="commerce").pk,
            "wilaya": m.wilaya_id, "moughataa": m.pk, "neighborhood": "Carrefour", "cover": img("cover.jpg")})
        p = Project.objects.get(owner=owner)
        self.assertRedirects(r, f"/fr/projects/{p.slug}/edit/terms/")
        base = f"/fr/projects/{p.slug}/edit/"

        r = c.post(base + "terms/", {"target_amount": "300000", "share_price": "1000", "min_shares": "1",
                                     "min_funding_pct": "100", "owner_contribution": "50000", "campaign_days": "30",
                                     "duration_months": "24", "investor_profit_share_pct": "40",
                                     "projected_annual_return_pct": "16", "distribution_frequency": "monthly",
                                     "exit_mode": "diminishing", "report_frequency": "monthly"})
        self.assertRedirects(r, base + "details/")
        r = c.post(base + "terms/", {"target_amount": "300500", "share_price": "1000", "min_shares": "1",
                                     "min_funding_pct": "100", "campaign_days": "90", "duration_months": "24",
                                     "investor_profit_share_pct": "40", "projected_annual_return_pct": "16",
                                     "distribution_frequency": "monthly", "exit_mode": "diminishing",
                                     "report_frequency": "monthly", "owner_contribution": "0"})
        self.assertEqual(r.status_code, 200)  # not a multiple of the share price + campaign too long
        self.assertContains(r, "multiple de la valeur")
        self.assertContains(r, "60 jours maximum")

        r = c.get(base + "details/")
        self.assertContains(r, 'id="shop-map"')
        details = {"shop_name": "Épicerie Test", "category": "grocery", "premises": "rented", "monthly_rent": "12000",
                   "surface_m2": "20", "storage_m2": "5", "location_type": "residential", "competitors_nearby": "1",
                   "days_open": "7", "staff_count": "1", "owner_works_in_shop": "on", "customers_per_day": "120",
                   "average_basket": "100", "restock_frequency_days": "7", "gross_margin_pct": "18",
                   "salaries": "8000", "owner_draw": "10000", "utilities": "4000", "transport": "2000", "taxes": "500",
                   "other_costs": "1000", "inventory_value": "200000", "equipment_value": "50000",
                   "cash_on_hand": "10000", "customer_credit": "20000", "supplier_debt": "10000", "other_debt": "0",
                   "cash_sales_pct": "60", "mobile_money_pct": "30", "credit_sales_pct": "10", "energy": "somelec",
                   "growth_plan": "Plus de stock.", "expected_revenue_uplift_pct": "20",
                   "latitude": "18.05", "longitude": "-15.95"}
        r = c.post(base + "details/", details)
        self.assertRedirects(r, base + "figures/")
        self.assertEqual(p.boutique.latitude, Decimal("18.050000"))

        r = c.get(base + "figures/")
        self.assertEqual(r.status_code, 200)
        data = {"months-TOTAL_FORMS": "6", "months-INITIAL_FORMS": "0", "months-MIN_NUM_FORMS": "0",
                "months-MAX_NUM_FORMS": "1000", "products-TOTAL_FORMS": "3", "products-INITIAL_FORMS": "0",
                "products-MIN_NUM_FORMS": "0", "products-MAX_NUM_FORMS": "1000"}
        for i in range(6):
            data[f"months-{i}-month"] = f"2026-0{i + 1}"
            data[f"months-{i}-revenue"] = "360000"
            data[f"months-{i}-purchases"] = "290000"
        for i, name in enumerate(["Riz", "Huile", "Sucre"]):
            data.update({f"products-{i}-name": name, f"products-{i}-buy_price": "1000", f"products-{i}-sell_price": "1100",
                         f"products-{i}-monthly_units": "50"})
        r = c.post(base + "figures/", data)
        self.assertRedirects(r, base + "funds/")
        self.assertEqual(p.boutique_months.count(), 6)
        self.assertEqual(p.boutique_months.first().month, date(2026, 1, 1))

        r = c.post(base + "funds/", {"uof-TOTAL_FORMS": "2", "uof-INITIAL_FORMS": "0", "uof-MIN_NUM_FORMS": "0",
                                     "uof-MAX_NUM_FORMS": "1000", "uof-0-category": "stock", "uof-0-label": "Stock",
                                     "uof-0-amount": "200000", "uof-1-category": "equipment", "uof-1-label": "Frigo",
                                     "uof-1-amount": "100000"})
        self.assertRedirects(r, base + "questions/")

        answers = {}
        for q in Question.objects.filter(active=True):
            if not q.applies("boutique"):
                continue
            key = f"q_{q.pk}"
            answers[key] = {"bool": "1", "number": "3", "money": "0", "date": "2026-01-01"}.get(q.type)
            if q.type == "choice":
                answers[key] = q.choices[0]["value"]
            elif q.type == "multi":
                answers[key] = [q.choices[0]["value"]]
            elif answers[key] is None:
                answers[key] = "Réponse"
        r = c.post(base + "questions/", answers)
        self.assertRedirects(r, base + "media/")

        c.post(base + "media/", {"photos": "1", "images": [img("a.jpg"), img("b.jpg"), img("c.jpg")]})
        self.assertEqual(p.images.count(), 3)
        f = pdf_file("patente.pdf")
        c.post(base + "media/", {"doc": "1", "kind": "registration", "title": "Patente", "visible_to_investors": "on",
                                 "file": SimpleUploadedFile("patente.pdf", f.read(), content_type="application/pdf")})
        self.assertEqual(p.documents.count(), 1)

        r = c.get(base + "submit/")
        self.assertTrue(r.context["ready"], [i for i in r.context["checklist"] if not i["done"]])
        r = c.post(base + "submit/")
        self.assertRedirects(r, "/fr/dashboard/")
        p.refresh_from_db()
        self.assertEqual(p.status, "submitted")
        self.assertEqual(p.review_fee_paid, Decimal("1500"))
        # Preview of the draft page works for the owner and the detail renders the boutique model
        self.assertEqual(c.get(p.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client_class().get(p.get_absolute_url()).status_code, 404)  # not public yet
