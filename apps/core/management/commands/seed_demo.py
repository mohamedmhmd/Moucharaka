"""Populate a demo platform with realistic history.

Every operation goes through the real services (escrow, release, reports,
distributions, market), with the clock moved back in time, so balances,
ledgers and trust scores are all consistent.

    python manage.py seed_demo            # once, on an empty database
    python manage.py seed_demo --password Demo#2026
"""
import contextlib
import random
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import KYCProfile, User
from apps.core.factories import make_project, make_user
from apps.core.models import PlatformSettings
from apps.investments.services import invest, pay_installment, pay_profit_distribution, release_funds
from apps.market.services import buy, create_listing
from apps.projects.models import Project, ProjectInterest, ProjectQuestion, ProjectUpdate
from apps.projects.services import approve_project, report_periods, submit_project, submit_report
from apps.trust.models import Review
from apps.trust.services import compute_score
from apps.wallet.services import adjust

D = Decimal


@contextlib.contextmanager
def travel(when):
    with mock.patch("django.utils.timezone.now", return_value=when):
        yield


class Command(BaseCommand):
    help = "Create demo users, projects and 4 months of activity."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Moucharaka#2026")
        parser.add_argument("--force", action="store_true", help="Run even if projects already exist.")

    def handle(self, *args, password, force, **opts):
        if Project.objects.exists() and not force:
            raise CommandError("Database already has projects. Use --force to add demo data anyway.")
        rnd = random.Random(42)
        now = timezone.now()
        t0 = now - timedelta(days=130)
        with transaction.atomic():
            s = PlatformSettings.get()
            s.merchant_bankily, s.merchant_masrvi, s.merchant_sedad = "36 00 00 01", "36 00 00 02", "36 00 00 03"
            s.bank_details = "BMCI — Moucharaka SA — compte de cantonnement — RIB 00012 00001 0123456789 01"
            s.support_phone = "+222 45 00 00 00"
            s.save()
            with travel(t0 - timedelta(days=30)):
                admin = User.objects.create_superuser("20000000", password, full_name="Administrateur Moucharaka",
                                                      preferred_language="fr")
                staff = make_user("Khadijetou Mint Ahmed", staff=True, phone="20000001", password=password)
                from django.contrib.auth.models import Group

                staff.groups.add(*Group.objects.filter(name__in=["Conformité", "Opérations"]))
                owners = {
                    "cheikh": make_user("Cheikh Ould Mohamed Lemine", phone="22000101", password=password, balance=60_000, wilaya_code="NKS"),
                    "aicha": make_user("Aïcha Mint Sidi", phone="22000102", password=password, balance=20_000, wilaya_code="NKN"),
                    "brahim": make_user("Brahim Ould Ely", phone="22000103", password=password, balance=150_000, wilaya_code="ASB"),
                    "mariem": make_user("Mariem Mint Abdallahi", phone="22000104", password=password, balance=40_000, wilaya_code="DNO"),
                    "sidi": make_user("Sidi Ould Cheikh", phone="22000105", password=password, balance=80_000, wilaya_code="NKS"),
                }
                names = ["Mohamed Ould Baba", "Fatimetou Mint Salem", "Ahmed Ould Sidi", "Zeinabou Mint Cheikh",
                         "Moussa Ba", "Oumar Diallo", "Vatimetou Mint Isselmou", "Abdallahi Ould Ahmedou",
                         "Lalla Mint Moctar", "El Hacen Ould Mahfoudh", "Coumba Sy", "Yahya Ould Brahim"]
                # Diaspora members log in with their foreign WhatsApp number
                diaspora = {1: "+33612345601", 3: "+34612345603", 6: "+971501234506", 9: "+12025550109"}
                investors = [make_user(n, phone=diaspora.get(i, f"3300{i:04d}"), password=password,
                                       balance=rnd.choice([300_000, 500_000, 800_000]))
                             for i, n in enumerate(names)]
            demo_investor = investors[0]

            # 1. Active boutique (Moucharaka) with 4 months of reports and dividends
            with travel(t0):
                p1 = make_project(owners["cheikh"], "boutique", "moucharaka", 600_000, title="Boutique Ahl Cheikh — Arafat",
                                  tagline="Doubler le stock d'une épicerie de quartier qui vend 420 000 MRU par mois.",
                                  description=DESC_BOUTIQUE, neighborhood="Arafat, carrefour Tieb-Tieb", profit_share=45,
                                  projected=19, owner_contribution=120_000, duration_months=36)
                submit_project(p1, owners["cheikh"])
                p1.refresh_from_db()
                approve_project(p1, staff, "B", "Boutique visitée le 3 du mois. Cahier de ventes tenu depuis 2 ans, cohérent avec "
                                                "les relevés Bankily. Point d'attention : crédit clients un peu élevé.")
            self._fill(p1, investors, rnd, t0, total=600)
            with travel(t0 + timedelta(days=12)):
                release_funds(Project.objects.get(pk=p1.pk), by=staff)
            p1.refresh_from_db()
            for i, (start, end, due) in enumerate(report_periods(p1, today=now.date())):
                when = timezone.make_aware(timezone.datetime.combine(end + timedelta(days=rnd.randint(3, 8)), timezone.datetime.min.time())) \
                    + timedelta(hours=10)
                if when > now:
                    break
                revenue = D(rnd.randint(500_000, 560_000))
                with travel(when):
                    r = submit_report(p1, owners["cheikh"], start, {
                        "revenue": revenue, "cogs": (revenue * D("0.82")).quantize(D("1")), "expenses": D("47000"),
                        "inventory_value": D(rnd.randint(420_000, 480_000)), "cash_balance": D(rnd.randint(30_000, 60_000)),
                        "customer_credit": D(rnd.randint(30_000, 45_000)),
                        "notes": "Bon mois, forte demande en lait et sucre." if i % 2 == 0 else "Rupture de riz une semaine, rattrapée."})
                    r.status = "verified"
                    r.verified_by = staff
                    r.save()
                    adjust(owners["cheikh"], r.investors_share, reason="Recette du mois (démo)")
                    pay_profit_distribution(r)
            with travel(now - timedelta(days=20)):
                ProjectUpdate.objects.create(project=p1, title="Nouveau congélateur installé",
                                             body="Le congélateur est en place : nous vendons maintenant poulet et poisson. Ventes en hausse de 9 %.")
                ProjectQuestion.objects.create(project=p1, asker=investors[3], question="Quel est le délai de paiement de vos fournisseurs ?",
                                               answer="15 jours chez le grossiste du marché Capitale, paiement comptant pour le riz.",
                                               answered_at=now - timedelta(days=18))
                for inv in investors[:3]:
                    Review.objects.get_or_create(project=p1, reviewer=inv, defaults={
                        "owner": owners["cheikh"], "communication": 5, "transparency": rnd.choice([4, 5]), "commitments": 5,
                        "comment": "Rapports chaque mois avec photo du cahier. Sérieux."})
            with travel(now - timedelta(days=15)):
                l1 = create_listing(investors[1], p1, 20, D("1080"), note="Besoin de liquidités pour un mariage.")
                buy(investors[7], l1, 10)
            with travel(now - timedelta(days=4)):
                create_listing(investors[2], p1, 15, D("1120"))
                create_listing(investors[4], p1, 8, D("1050"), allow_partial=False)

            # 2. Boutique in funding
            with travel(now - timedelta(days=12)):
                p2 = make_project(owners["aicha"], "boutique", "moucharaka", 400_000, title="Alimentation Dar Naïm Express",
                                  tagline="Une boutique tenue par deux sœurs, ouverte jusqu'à minuit, qui veut ajouter un rayon frais.",
                                  description=DESC_AICHA, neighborhood="Dar Naïm, près du marché Tarhil", profit_share=40,
                                  projected=17, wilaya_code="NKN", owner_contribution=60_000)
                submit_project(p2, owners["aicha"])
                p2.refresh_from_db()
                approve_project(p2, staff, "C", "Activité jeune (14 mois) mais ventes régulières. Bail de 3 ans signé.")
            with travel(now - timedelta(days=8)):
                for inv in investors[2:9]:
                    invest(inv, Project.objects.get(pk=p2.pk), rnd.choice([20, 30, 40, 50]), True)

            # 3. Mourabaha deal in funding (Tabaski sheep)
            with travel(now - timedelta(days=6)):
                p3 = make_project(owners["brahim"], "deal", "mourabaha", 900_000, title="Moutons de Tabaski — Kiffa",
                                  tagline="Achat de 120 moutons à Kiffa, engraissement et revente à Nouakchott avant la fête.",
                                  description=DESC_DEAL, neighborhood="Marché au bétail", margin=9, duration_months=4,
                                  repayment=Project.Repayment.BULLET, wilaya_code="ASB", owner_contribution=150_000)
                submit_project(p3, owners["brahim"])
                p3.refresh_from_db()
                approve_project(p3, staff, "B", "Troisième opération identique ; les deux précédentes ont été vendues en 40 jours. Troupeau assuré.")
                for inv in investors[5:10]:
                    invest(inv, Project.objects.get(pk=p3.pk), rnd.choice([40, 60, 80]), True)

            # 4. Active Mourabaha boutique stock financing with installments
            with travel(t0 + timedelta(days=20)):
                p4 = make_project(owners["sidi"], "boutique", "mourabaha", 300_000, title="Quincaillerie El Mina",
                                  tagline="Stock de ciment et de fer à béton pour la saison de construction.",
                                  description=DESC_QUINCAILLERIE, neighborhood="El Mina, route de Rosso", margin=8, duration_months=6,
                                  repayment=Project.Repayment.MONTHLY, owner_contribution=90_000)
                p4.boutique.category = "hardware"
                p4.boutique.save()
                submit_project(p4, owners["sidi"])
                p4.refresh_from_db()
                approve_project(p4, staff, "A", "Commerce de 9 ans, comptes bancaires fournis, garant solide.")
            self._fill(p4, investors[3:], rnd, t0 + timedelta(days=21), total=300)
            with travel(t0 + timedelta(days=30)):
                release_funds(Project.objects.get(pk=p4.pk), by=staff)
            for inst in Project.objects.get(pk=p4.pk).installments.all():
                pay_day = timezone.make_aware(timezone.datetime.combine(inst.due_date - timedelta(days=1), timezone.datetime.min.time())) + timedelta(hours=11)
                if pay_day > now:
                    break
                with travel(pay_day):
                    adjust(owners["sidi"], inst.amount, reason="Ventes (démo)")
                    pay_installment(inst)

            # 5. Future company in funding
            with travel(now - timedelta(days=3)):
                p5 = make_project(owners["mariem"], "company", "moucharaka", 1_500_000, title="Boulangerie Le Banc d'Arguin",
                                  tagline="Pain complet et viennoiseries livrés chaque matin aux familles et hôtels de Nouadhibou.",
                                  description=DESC_COMPANY, neighborhood="Numerowatt", profit_share=35, projected=22,
                                  wilaya_code="DNO", exit_mode=Project.Exit.OPEN, frequency=Project.Frequency.QUARTERLY,
                                  owner_contribution=300_000, duration_months=48)
                submit_project(p5, owners["mariem"])
                p5.refresh_from_db()
                approve_project(p5, staff, "D", "Projet prometteur mais sans historique de ventes : risque élevé. Équipe expérimentée.")
                invest(investors[10], Project.objects.get(pk=p5.pk), 100, True)
                invest(investors[11], Project.objects.get(pk=p5.pk), 60, True)

            # 6. Queues for the back-office
            make_project(owners["sidi"], "boutique", "moucharaka", 250_000, title="Boutique Sebkha Bord de Mer",
                         status=Project.Status.SUBMITTED, wilaya_code="NKO")
            # A draft shared privately with relatives, who already signalled interest
            draft = make_project(owners["aicha"], "boutique", "moucharaka", 200_000, title="Couture Mint Sidi — Ksar",
                                 tagline="Atelier de melhfa et de broderie qui veut acheter deux machines.",
                                 wilaya_code="NKO")
            for inv, amount in ((investors[1], 20_000), (investors[6], 50_000), (investors[9], None)):
                ProjectInterest.objects.create(project=draft, user=inv, amount=amount)

            # Payment accounts: Bankily / Masrvi / Sedad numbers in Mauritania, even for diaspora members
            from apps.wallet.models import PaymentAccount

            methods = ["bankily", "masrvi", "sedad"]
            for i, u in enumerate(User.objects.filter(status="approved").order_by("pk")):
                PaymentAccount.objects.create(user=u, method=methods[i % 3], number=f"+2224{i:07d}",
                                              holder_name=u.full_name, is_default=True, verified_at=now)
            PaymentAccount.objects.create(user=investors[1], method="bank", number="MR1300020001010000123456753",
                                          bank_name="BMCI", holder_name=investors[1].full_name,
                                          label="Compte de ma famille à Nouakchott")
            pending = make_user("Hawa Sow", approved=False, phone="44000001", password=password)
            from apps.core.factories import image_file
            from apps.core.models import Moughataa
            m = Moughataa.objects.filter(wilaya__code="NKO").first()
            k = KYCProfile(user=pending, full_name="Hawa Sow", nni="2999000001", id_number="2999000001",
                           id_issue_date=now.date() - timedelta(days=900), id_expiry_date=now.date() + timedelta(days=1200),
                           date_of_birth=now.date().replace(year=now.year - 31), place_of_birth="Kaédi", gender="f",
                           wilaya=m.wilaya, moughataa=m, address="Ksar, îlot B", profession="Couturière",
                           monthly_income="20-50k", source_of_funds="business", experience="informal", status="submitted",
                           submitted_at=now)
            k.id_front.save("front.jpg", image_file(text="ID FRONT"), save=False)
            k.save()
            pending.status = User.Status.PENDING
            pending.save(update_fields=["status"])

            for u in User.objects.all():
                compute_score(u)
        self.stdout.write(self.style.SUCCESS(
            f"Demo ready. Admin: 20000000 / {password} · Staff: 20000001 · Owner: 22000101 · "
            f"Investor: {demo_investor.phone} · Diaspora investor: +33612345601 (same password)."))
        self.stdout.write(f"Admin user id {admin.pk}.")

    def _fill(self, project, investors, rnd, start, total):
        """Investors subscribe until the campaign is fully funded."""
        cap = int(total * 0.4)
        when = start
        left = total
        pool = list(investors)
        rnd.shuffle(pool)
        for inv in pool * 3:
            if left <= 0:
                break
            p = Project.objects.get(pk=project.pk)
            if p.status != "funding":
                break
            n = min(left, rnd.choice([20, 30, 50, 60, 80]), cap)
            when += timedelta(hours=rnd.randint(6, 40))
            with travel(when):
                from apps.investments.services import InvestmentError, max_shares_for

                n = min(n, max_shares_for(inv, p))
                if n <= 0:
                    continue
                try:
                    invest(inv, p, n, True)
                    left -= n
                except InvestmentError:
                    continue


DESC_BOUTIQUE = (
    "Je tiens cette épicerie au carrefour Tieb-Tieb d'Arafat depuis 2019. Nous vendons riz, huile, sucre, lait, thé, "
    "pain et produits d'entretien à environ 140 familles chaque jour. Le problème : je manque régulièrement de "
    "marchandises en fin de mois parce que tout mon argent est immobilisé dans le stock et les crédits clients.\n\n"
    "Avec 600 000 MRU, j'achète en demi-gros (sacs de 50 kg, cartons) directement chez le grossiste, ce qui améliore "
    "ma marge de 2 à 3 points, et j'installe un congélateur pour vendre poulet et poisson. Les investisseurs reçoivent "
    "45 % du bénéfice net chaque mois, et je rachète progressivement leurs parts à partir de la deuxième année.")
DESC_AICHA = (
    "Ma sœur et moi avons ouvert cette boutique il y a 14 mois dans une rue très habitée de Dar Naïm. Nous ouvrons de "
    "7 h à minuit, 7 jours sur 7. Nos clientes nous demandent des légumes, des œufs et des produits frais que nous "
    "n'avons pas les moyens de stocker. Le financement sert à acheter un réfrigérateur vitrine, des panneaux solaires "
    "pour ne plus dépendre des coupures, et à élargir le stock. Nous publierons chaque mois une photo de notre cahier.")
DESC_DEAL = (
    "Chaque année avant la Tabaski, j'achète des moutons sur le marché de Kiffa, je les engraisse 45 jours dans notre "
    "enclos familial puis je les revends à Nouakchott, au marché de Sebkha et à des familles qui me commandent "
    "à l'avance. C'est ma troisième opération ; les deux précédentes ont été vendues en 40 jours avec une marge brute "
    "de 25 à 30 %. Le financement est une Mourabaha : les investisseurs achètent le troupeau et me le revendent avec "
    "une marge de 9 %, payée en une fois après la fête. Les moutons sont assurés et restent en garantie jusqu'au paiement.")
DESC_QUINCAILLERIE = (
    "Quincaillerie ouverte en 2017 sur la route de Rosso. La demande en ciment et fer à béton explose pendant la saison "
    "sèche. Je finance un stock de saison en Mourabaha : 6 échéances mensuelles fixes, marge de 8 % sur la durée. "
    "Un commerçant de la même rue se porte garant. Mes clients sont les petits entrepreneurs du bâtiment d'El Mina et "
    "de Riyad, qui achètent à crédit sur 15 jours ; je tiens un registre de ces crédits depuis 2019 et mon taux "
    "d'impayés reste sous 2 %.")
DESC_COMPANY = (
    "Nouadhibou n'a pas de boulangerie artisanale de qualité. Nous ouvrons une boulangerie qui produira pain complet, "
    "pain traditionnel et viennoiseries, livrés chaque matin par abonnement aux familles, aux hôtels et aux bateaux "
    "de passage. L'équipe : une boulangère formée à Dakar avec 6 ans d'expérience, un gérant qui a dirigé une "
    "supérette, et un livreur. Les investisseurs deviennent associés de la SARL à hauteur de 35 % des bénéfices.")
