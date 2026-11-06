"""End-to-end tests of every money flow. The ledger must always balance:
sum of all wallets (available + held) == deposits − withdrawals."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from apps.core.factories import make_project, make_user
from apps.investments.models import Distribution, Holding, Investment
from apps.investments.services import (InvestmentError, buyback, cancel_investment, close_campaign, invest,
                                       pay_installment, pay_profit_distribution, release_funds)
from apps.market.services import MarketError, buy, create_listing
from apps.projects.jobs import check_installments, check_reports
from apps.projects.models import Installment, Project
from apps.projects.services import ProjectError, approve_project, report_periods, submit_project, submit_report
from apps.trust.models import TrustEvent
from apps.trust.services import compute_score
from apps.wallet.models import Transaction, Wallet

D = Decimal


def total_money():
    agg = Wallet.objects.aggregate(b=Sum("balance"), h=Sum("held"))
    return (agg["b"] or 0) + (agg["h"] or 0)


def injected():
    return Transaction.objects.filter(kind__in=["adjustment", "deposit"]).aggregate(s=Sum("amount"))["s"] or 0


class FlowBase(TestCase):
    def setUp(self):
        self.staff = make_user("Staff Member", staff=True)
        self.owner = make_user("Sidi Mohamed", balance=50_000)
        self.inv1 = make_user("Mariem Ahmed", balance=1_000_000)
        self.inv2 = make_user("Cheikh Ould Brahim", balance=1_000_000)

    def assertLedgerBalanced(self):
        self.assertEqual(total_money(), injected())

    def launch(self, **kw):
        p = make_project(self.owner, **kw)
        submit_project(p, self.owner)
        p.refresh_from_db()
        approve_project(p, self.staff, "B")
        p.refresh_from_db()
        return p


class BoutiqueMoucharakaFlow(FlowBase):
    def test_full_lifecycle(self):
        p = self.launch(kind="boutique", model="moucharaka", target=600_000)
        self.assertEqual(p.status, "funding")
        self.assertEqual(p.review_fee_paid, D("100"))
        self.assertEqual(p.total_shares, 600)
        self.assertEqual(p.success_fee_pct, D("5"))

        # Escrow
        invest(self.inv1, p, 240, True)
        w = Wallet.for_user(self.inv1)
        self.assertEqual(w.held, D("240000"))
        with self.assertRaises(InvestmentError):  # 40 % cap
            invest(self.inv1, p, 1, True)
        with self.assertRaises(InvestmentError):  # owner cannot invest
            invest(self.owner, p, 1, True)
        i2 = invest(self.inv2, p, 100, True)
        cancel_investment(i2, self.inv2)
        self.assertEqual(Wallet.for_user(self.inv2).held, 0)
        invest(self.inv2, p, 240, True)
        inv3 = make_user("Fatimetou", balance=200_000)
        invest(inv3, p, 120, True)
        p.refresh_from_db()
        self.assertEqual(p.status, "funded")
        self.assertLedgerBalanced()

        # Release: owner gets 600 000 − 5 %
        owner_before = Wallet.for_user(self.owner).balance
        release_funds(p, by=self.staff)
        p.refresh_from_db()
        self.assertEqual(p.status, "active")
        self.assertEqual(Wallet.for_user(self.owner).balance - owner_before, D("570000"))
        self.assertEqual(Wallet.for_user(self.inv1).held, 0)
        self.assertEqual(Holding.objects.get(user=self.inv1, project=p).shares, 240)
        self.assertLedgerBalanced()

        # Monthly report → profit distribution (40 % of profit, 10 % fee on it)
        p.released_at = timezone.now() - timedelta(days=70)
        p.save()
        periods = report_periods(p)
        self.assertGreaterEqual(len(periods), 1)
        r = submit_report(p, self.owner, periods[0][0], {"revenue": D("500000"), "cogs": D("400000"),
                                                         "expenses": D("40000")})
        self.assertEqual(r.net_profit, D("60000"))
        self.assertEqual(r.investors_share, D("24000"))
        d = pay_profit_distribution(r)
        self.assertEqual(d.platform_fee, D("2400.00"))
        self.assertEqual(d.net_amount, D("21600.00"))
        self.assertEqual(sum(po.amount for po in d.payouts.all()), d.net_amount)
        self.assertEqual(d.payouts.get(user=self.inv1).amount, D("8640.00"))  # 240/600
        with self.assertRaises(InvestmentError):
            pay_profit_distribution(r)
        self.assertLedgerBalanced()

        # Secondary market
        listing = create_listing(self.inv1, p, 50, D("1100"))
        with self.assertRaises(MarketError):
            create_listing(self.inv1, p, 200, D("1100"))  # only 190 free
        with self.assertRaises(MarketError):
            buy(self.owner, listing, 10)
        t = buy(self.inv2, listing, 20)
        self.assertEqual(t.gross, D("22000"))
        self.assertEqual(t.buyer_fee, D("220.00"))
        self.assertEqual(Holding.objects.get(user=self.inv2, project=p).shares, 260)
        h1 = Holding.objects.get(user=self.inv1, project=p)
        self.assertEqual((h1.shares, h1.locked_shares), (220, 30))
        self.assertLedgerBalanced()

        # Diminishing buyback of 100 parts at 1 050 (fee on the 50 MRU gain)
        adj_owner = Wallet.for_user(self.owner).balance
        dist = buyback(p, 100, D("1050"))
        self.assertEqual(dist.shares_retired, 100)
        self.assertEqual(Wallet.for_user(self.owner).balance, adj_owner - D("105000"))
        self.assertEqual(sum(h.shares for h in Holding.objects.filter(project=p)), 500)
        self.assertEqual(Holding.objects.get(user=self.inv1, project=p).locked_shares, 0)  # listing cancelled
        self.assertLedgerBalanced()

        # Full buyback completes the project
        from apps.wallet.services import adjust

        adjust(self.owner, D("600000"), reason="test top-up")
        buyback(p, 500, D("1000"))
        p.refresh_from_db()
        self.assertEqual(p.status, "completed")
        self.assertLedgerBalanced()
        score = compute_score(self.owner)
        self.assertTrue(score.has_track_record)
        self.assertEqual(score.components["outcomes"], 80)  # 50 base + completed 25 + funded 5
        # The report above was filed after its deadline: the late payment shows in the score
        self.assertTrue(TrustEvent.objects.filter(user=self.owner, kind="report_late").exists())

    def test_submit_requires_review_fee_and_checklist(self):
        poor = make_user("Poor Owner", balance=0)
        p = make_project(poor)
        with self.assertRaises(ProjectError):
            submit_project(p, poor)
        p.images.all().delete()
        from apps.wallet.services import adjust

        adjust(poor, D("5000"))
        submit_project(p, poor)  # photos are optional during the launch period
        p.refresh_from_db()
        self.assertEqual(p.status, "submitted")


class MourabahaFlow(FlowBase):
    def test_installments_and_completion(self):
        p = self.launch(kind="boutique", model="mourabaha", target=300_000, margin=10, duration_months=3)
        invest(self.inv1, p, 120, True)
        invest(self.inv2, p, 120, True)
        close_campaign(p)
        p.refresh_from_db()
        self.assertEqual(p.status, "funding")  # not expired yet → close_campaign only acts at deadline
        p.campaign_end = timezone.now() - timedelta(minutes=1)
        p.min_funding_pct = D("80")
        p.save()
        close_campaign(p)
        p.refresh_from_db()
        self.assertEqual(p.status, "funded")
        release_funds(p)
        p.refresh_from_db()
        self.assertEqual(p.raised_amount, D("240000"))
        insts = list(p.installments.all())
        self.assertEqual(len(insts), 3)
        self.assertEqual(sum(i.principal for i in insts), D("240000"))
        self.assertEqual(sum(i.margin for i in insts), D("24000"))
        from apps.wallet.services import adjust

        adjust(self.owner, D("100000"))
        for inst in insts:
            pay_installment(inst)
        p.refresh_from_db()
        self.assertEqual(p.status, "completed")
        # Each investor got principal + margin − 12 % fee on margin
        received = Distribution.objects.filter(project=p).aggregate(s=Sum("net_amount"))["s"]
        self.assertEqual(received, D("240000") + D("24000") - D("2880"))
        self.assertLedgerBalanced()

    def test_late_installment_and_default(self):
        p = self.launch(kind="boutique", model="mourabaha", target=100_000, margin=8, duration_months=2)
        invest(self.inv1, p, 40, True)
        invest(self.inv2, p, 40, True)
        invest(make_user("Third", balance=50_000), p, 20, True)
        p.refresh_from_db()
        release_funds(p)
        inst = p.installments.first()
        today = inst.due_date + timedelta(days=10)
        check_installments(today=today)
        inst.refresh_from_db()
        self.assertEqual(inst.status, Installment.Status.LATE)
        self.assertTrue(TrustEvent.objects.filter(user=self.owner, kind="installment_overdue").exists())
        check_installments(today=inst.due_date + timedelta(days=100))
        p.refresh_from_db()
        self.assertEqual(p.status, Project.Status.DEFAULTED)
        self.assertEqual(compute_score(self.owner).grade in ("D", "E", "C"), True)


class FailedCampaign(FlowBase):
    def test_refund(self):
        p = self.launch(kind="boutique", target=600_000)
        invest(self.inv1, p, 100, True)
        p.campaign_end = timezone.now() - timedelta(days=1)
        p.save()
        close_campaign(p)
        p.refresh_from_db()
        self.assertEqual(p.status, "failed")
        self.assertEqual(Investment.objects.get(project=p).status, "refunded")
        w = Wallet.for_user(self.inv1)
        self.assertEqual((w.balance, w.held), (D("1000000"), D("0")))
        self.assertLedgerBalanced()


class ReportingDiscipline(FlowBase):
    def test_missed_report_penalised_once(self):
        p = self.launch(kind="boutique", target=600_000)
        for u, n in ((self.inv1, 240), (self.inv2, 240), (make_user("X", balance=200_000), 120)):
            invest(u, p, n, True)
        release_funds(p)
        p.refresh_from_db()
        p.released_at = timezone.now() - timedelta(days=75)
        p.save()
        check_reports()
        check_reports()
        self.assertEqual(TrustEvent.objects.filter(user=self.owner, kind="report_missed").count(),
                         len([x for x in report_periods(p) if x[2] < timezone.now().date()]))


class DeleteTestUserCommand(FlowBase):
    """manage.py delete_user removes a test member and everything attached, and the books still balance."""

    def test_delete_investor_then_owner(self):
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from apps.accounts.models import User
        from apps.wallet.services import request_withdrawal

        p = self.launch(kind="deal", model="mourabaha", target=300_000, margin=10, duration_months=3)
        invest(self.inv1, p, 120_000, True)  # a deal counts in MRU
        invest(self.inv2, p, 120_000, True)
        inv3 = make_user("Test Diaspora", balance=200_000)
        invest(inv3, p, 60_000, True)
        p.refresh_from_db()
        release_funds(p, by=self.staff)
        acc = self.inv1.payment_accounts.create(method="bankily", number="36112233", holder_name="Mariem",
                                                verified_at=timezone.now())
        request_withdrawal(self.inv1, D("10000"), acc)
        self.assertLedgerBalanced()

        out = StringIO()
        call_command("delete_user", self.owner.phone, stdout=out)  # dry run
        self.assertIn("Nothing deleted", out.getvalue())
        with self.assertRaises(CommandError):  # others invested in the owner's project
            call_command("delete_user", self.owner.phone, "--yes", stdout=out)
        boss = User.objects.create_superuser(phone="+22220009999", password="x", full_name="Boss")
        with self.assertRaises(CommandError):  # owner accounts are protected
            call_command("delete_user", boss.phone, "--yes", stdout=out)

        with self.assertRaises(CommandError):  # an investor goes after the project owner
            call_command("delete_user", self.inv2.phone, "--yes", stdout=out)
        before = Wallet.for_user(self.inv2).balance
        call_command("delete_user", self.owner.phone, "--yes", "--force", stdout=out)
        self.assertFalse(Project.objects.filter(pk=p.pk).exists())
        self.assertFalse(User.objects.filter(pk=self.owner.pk).exists())
        self.assertEqual(Wallet.for_user(self.inv2).balance, before + D("120000"))  # money back
        self.assertLedgerBalanced()
        for u in (self.inv1, self.inv2, inv3):
            call_command("delete_user", u.phone, "--yes", stdout=out)
            self.assertFalse(User.objects.filter(pk=u.pk).exists())
            self.assertLedgerBalanced()


class DealSettlementFlow(FlowBase):
    """Opération ponctuelle: invest an amount, owner gets the money, owner pays back one total,
    the team validates, each investor receives their share. No parts, no reports, no market."""

    def setUp(self):
        super().setUp()
        self.inv3 = make_user("Aicha Mint Sidi", balance=1_000_000)

    def funded_deal(self, model="moucharaka", **kw):
        kw.setdefault("target", 300_000)
        p = self.launch(kind="deal", model=model, **kw)
        self.assertEqual(p.share_price, D("1"))  # counted in MRU
        invest(self.inv1, p, 120_000, True)
        invest(self.inv2, p, 120_000, True)
        invest(self.inv3, p, 60_000, True)
        p.refresh_from_db()
        self.assertEqual(p.status, "funded")
        release_funds(p, by=self.staff)
        p.refresh_from_db()
        return p

    def test_gain_is_shared_and_fee_taken_on_gain_only(self):
        from apps.investments.models import DealSettlement
        from apps.investments.services import submit_settlement, validate_settlement
        from apps.wallet.services import adjust

        p = self.funded_deal(projected=20)
        self.assertEqual(p.status, "active")
        self.assertFalse(p.installments.exists())
        self.assertEqual(report_periods(p), [])
        self.assertFalse(p.is_tradable)
        adjust(self.owner, D("100000"))
        st = submit_settlement(p, self.owner, D("360000"))
        w = Wallet.for_user(self.owner)
        self.assertEqual(w.held, D("360000"))
        self.assertLedgerBalanced()
        before = [Wallet.for_user(u).balance for u in (self.inv1, self.inv2, self.inv3)]
        platform_before = Wallet.platform().balance
        validate_settlement(st, by=self.staff)
        st.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual(st.status, DealSettlement.Status.VALIDATED)
        self.assertEqual(p.status, "completed")
        # gain 60 000, fee 10 % of the gain = 6 000, 354 000 shared 40/40/20
        self.assertEqual(Wallet.platform().balance - platform_before, D("6000"))
        after = [Wallet.for_user(u).balance for u in (self.inv1, self.inv2, self.inv3)]
        self.assertEqual([a - b for a, b in zip(after, before)], [D("141600"), D("141600"), D("70800")])
        self.assertEqual(Wallet.for_user(self.owner).held, D("0"))
        self.assertFalse(Holding.objects.filter(project=p, shares__gt=0).exists())
        self.assertEqual(Holding.objects.get(user=self.inv1, project=p).received_total, D("141600"))
        self.assertLedgerBalanced()

    def test_capital_only_no_fee(self):
        from apps.investments.services import deal_split, submit_settlement, validate_settlement

        p = self.funded_deal(model="mourabaha", margin=10)
        split = deal_split(p, D("300000"))
        self.assertEqual((split["gain"], split["fee"], split["net"]), (D("0"), D("0"), D("300000")))
        from apps.wallet.services import adjust

        adjust(self.owner, D("50000"))
        st = submit_settlement(p, self.owner, D("300000"))
        validate_settlement(st, by=self.staff)
        self.assertEqual(Holding.objects.get(user=self.inv3, project=p).received_total, D("60000"))
        self.assertLedgerBalanced()

    def test_loss_needs_a_message_and_is_shared(self):
        from apps.investments.services import submit_settlement, validate_settlement

        p = self.funded_deal()
        with self.assertRaises(InvestmentError):
            submit_settlement(p, self.owner, D("150000"))
        st = submit_settlement(p, self.owner, D("150000"), note="La marchandise a été vendue à perte.")
        validate_settlement(st, by=self.staff)
        self.assertEqual(Holding.objects.get(user=self.inv1, project=p).received_total, D("60000"))
        self.assertEqual(Holding.objects.get(user=self.inv3, project=p).received_total, D("30000"))
        self.assertLedgerBalanced()

    def test_cents_add_up_exactly(self):
        from apps.investments.models import Payout
        from apps.investments.services import submit_settlement, validate_settlement
        from apps.wallet.services import adjust

        p = self.funded_deal()
        adjust(self.owner, D("100000"))
        st = submit_settlement(p, self.owner, D("333333.33"))
        validate_settlement(st, by=self.staff)
        st.refresh_from_db()
        total = Payout.objects.filter(distribution=st.distribution).aggregate(s=Sum("amount"))["s"]
        self.assertEqual(total + st.distribution.platform_fee, D("333333.33"))
        self.assertLedgerBalanced()

    def test_reject_and_cancel_give_the_money_back(self):
        from apps.investments.services import cancel_settlement, reject_settlement, submit_settlement

        p = self.funded_deal()
        bal = Wallet.for_user(self.owner).balance
        st = submit_settlement(p, self.owner, D("300000"))
        with self.assertRaises(InvestmentError):  # only one at a time
            submit_settlement(p, self.owner, D("300000"))
        reject_settlement(st, self.staff, "Montant différent du contrat")
        self.assertEqual((Wallet.for_user(self.owner).balance, Wallet.for_user(self.owner).held), (bal, D("0")))
        st2 = submit_settlement(p, self.owner, D("300000"))
        cancel_settlement(st2, self.owner)
        self.assertEqual(Wallet.for_user(self.owner).balance, bal)
        p.refresh_from_db()
        self.assertEqual(p.status, "active")
        self.assertLedgerBalanced()

    def test_pages(self):
        from django.test import Client

        from apps.investments.models import DealSettlement

        p = self.launch(kind="deal", model="moucharaka", target=300_000)
        c = Client()
        c.force_login(self.inv1)
        page = c.get(p.get_absolute_url()).content.decode()
        self.assertIn('name="amount"', page)
        self.assertNotIn('name="shares"', page)
        r = c.post(f"/fr/projects/{p.slug}/invest/", {"amount": "120000", "risk": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Investment.objects.get(project=p, investor=self.inv1).amount, D("120000"))
        invest(self.inv2, p, 120_000, True)
        invest(self.inv3, p, 60_000, True)
        release_funds(p, by=self.staff)

        owner = Client()
        owner.force_login(self.owner)
        page = owner.get(f"/fr/projects/{p.slug}/manage/").content.decode()
        self.assertIn('id="settle"', page)
        self.assertNotIn('id="buyback"', page)
        too_much = owner.post(f"/fr/projects/{p.slug}/manage/settle/", {"amount": "9000000"})
        self.assertIn("/wallet/deposit/", too_much["Location"])
        owner.post(f"/fr/projects/{p.slug}/manage/settle/", {"amount": "310000"})
        st = DealSettlement.objects.get(project=p)
        self.assertEqual(st.status, "pending")

        staff = Client()
        staff.force_login(self.staff)
        page = staff.get("/fr/staff/settlements/").content.decode()
        self.assertIn(p.title, page)
        staff.post("/fr/staff/settlements/", {"id": st.pk, "action": "validate"})
        st.refresh_from_db()
        self.assertEqual(st.status, "validated")
        page = c.get("/fr/portfolio/").content.decode()
        self.assertEqual(c.get("/fr/portfolio/").status_code, 200)
        self.assertLedgerBalanced()

    def test_terms_form_has_no_share_price(self):
        from apps.projects.forms import TermsForm

        p = make_project(self.owner, kind="deal", model="moucharaka")
        form = TermsForm(instance=p)
        self.assertNotIn("share_price", form.fields)
        self.assertNotIn("exit_mode", form.fields)
        form = TermsForm({"target_amount": "250000"}, instance=p)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        p.refresh_from_db()
        self.assertEqual((p.share_price, p.target_amount), (D("1"), D("250000")))

    def test_existing_deal_converted_to_mru(self):
        import importlib

        from django.apps import apps as registry

        mig = importlib.import_module("apps.investments.migrations.0003_deals_in_mru")
        p = make_project(self.owner, kind="deal", model="mourabaha", target=300_000)  # 300 parts of 1 000
        Project.objects.filter(pk=p.pk).update(status="active", shares_sold=200)
        Investment.objects.create(investor=self.inv1, project=p, shares=200, amount=D("200000"), reference="X",
                                  status="settled")
        Holding.objects.create(user=self.inv1, project=p, shares=200, cost_basis=D("200000"))
        mig.forwards(registry, None)
        p.refresh_from_db()
        self.assertEqual((p.share_price, p.shares_sold, p.trading_enabled), (D("1"), 200_000, False))
        self.assertEqual(Holding.objects.get(project=p).shares, 200_000)
        self.assertEqual(Investment.objects.get(project=p).shares, 200_000)


class CompanySharesFlow(FlowBase):
    """Entreprise: parts on sale like an IPO, shareholders at once and for good, dividends,
    buyback offers with counter-proposals, company buying on the market."""

    def company(self, n=1000, price=1000):
        p = self.launch(kind="company", model="moucharaka", target=n * price, share_price=price)
        self.assertEqual(p.status, "active")
        self.assertTrue(p.is_share_offering)
        self.assertEqual(p.total_shares, n)
        return p

    def test_buy_is_immediate_and_rest_stays_on_sale(self):
        p = self.company()
        owner_before = Wallet.for_user(self.owner).balance
        inv = invest(self.inv1, p, 100, True)
        p.refresh_from_db()
        self.assertEqual(inv.status, "settled")
        self.assertEqual(Holding.objects.get(user=self.inv1, project=p).shares, 100)
        self.assertEqual(p.shares_available, 900)
        self.assertTrue(p.is_share_offering)
        # owner paid at once, minus the 7 % success fee
        self.assertEqual(Wallet.for_user(self.owner).balance - owner_before, D("93000"))
        self.assertEqual(Wallet.for_user(self.inv1).held, D("0"))
        self.assertEqual(report_periods(p), [])
        self.assertLedgerBalanced()

    def test_sold_out_closes_the_sale(self):
        p = self.company(n=200)
        invest(self.inv1, p, 80, True)
        invest(self.inv2, p, 80, True)
        invest(make_user("Third", balance=100_000), p, 40, True)
        p.refresh_from_db()
        self.assertFalse(p.offering_open)
        self.assertFalse(p.is_share_offering)
        with self.assertRaises(InvestmentError):
            invest(make_user("Late", balance=100_000), p, 1, True)

    def test_owner_can_stop_the_sale(self):
        from apps.investments.company import close_offering

        p = self.company()
        invest(self.inv1, p, 10, True)
        close_offering(p, self.owner)
        p.refresh_from_db()
        self.assertFalse(p.accepts_investment)
        with self.assertRaises(InvestmentError):
            invest(self.inv2, p, 10, True)

    def test_dividend_per_share(self):
        from apps.investments.company import dividend_preview, pay_dividend

        p = self.company()
        invest(self.inv1, p, 300, True)
        invest(self.inv2, p, 100, True)
        before1, before2 = Wallet.for_user(self.inv1).balance, Wallet.for_user(self.inv2).balance
        prev = dividend_preview(p, D("100000"))
        self.assertEqual((prev["fee"], prev["net"], prev["shares"]), (D("8000"), D("92000"), 400))
        d = pay_dividend(p, self.owner, D("100000"))
        self.assertEqual(d.kind, "dividend")
        self.assertEqual(Wallet.for_user(self.inv1).balance - before1, D("69000"))
        self.assertEqual(Wallet.for_user(self.inv2).balance - before2, D("23000"))
        self.assertLedgerBalanced()

    def test_buyback_offer_counter_and_accept(self):
        from apps.investments.company import answer_buyback, propose_buyback

        p = self.company()
        invest(self.inv1, p, 200, True)
        owner_w = Wallet.for_user(self.owner)
        offer = propose_buyback(p, self.owner, self.inv1, 100, D("1100"), "Nous rachetons la moitié")
        owner_w.refresh_from_db()
        self.assertEqual(owner_w.held, D("110000"))
        with self.assertRaises(InvestmentError):  # not the owner's turn
            answer_buyback(offer, self.owner, "accept")
        answer_buyback(offer, self.inv1, "counter", 80, D("1300"))
        offer.refresh_from_db()
        self.assertEqual((offer.waiting_on, offer.held_amount), ("owner", D("0")))
        self.assertEqual(Wallet.for_user(self.owner).held, D("0"))
        answer_buyback(offer, self.owner, "counter", 80, D("1200"))
        self.assertEqual(Wallet.for_user(self.owner).held, D("96000"))
        before = Wallet.for_user(self.inv1).balance
        answer_buyback(offer, self.inv1, "accept")
        offer.refresh_from_db()
        self.assertEqual(offer.status, "accepted")
        self.assertEqual(Holding.objects.get(user=self.inv1, project=p).shares, 120)
        # 96 000 minus the 1 % seller fee
        self.assertEqual(Wallet.for_user(self.inv1).balance - before, D("95040"))
        self.assertEqual(Wallet.for_user(self.owner).held, D("0"))
        self.assertLedgerBalanced()

    def test_buyback_refused_or_withdrawn_returns_the_money(self):
        from apps.investments.company import answer_buyback, propose_buyback

        p = self.company()
        invest(self.inv1, p, 50, True)
        bal = Wallet.for_user(self.owner).balance
        o = propose_buyback(p, self.owner, self.inv1, 50, D("1000"))
        with self.assertRaises(InvestmentError):  # one discussion at a time
            propose_buyback(p, self.owner, self.inv1, 10, D("1000"))
        with self.assertRaises(InvestmentError):  # more parts than owned
            propose_buyback(p, self.owner, self.inv2, 10, D("1000"))
        answer_buyback(o, self.inv1, "refuse")
        o.refresh_from_db()
        self.assertEqual(o.status, "refused")
        self.assertEqual(Wallet.for_user(self.owner).balance, bal)
        o2 = propose_buyback(p, self.owner, self.inv1, 50, D("1000"))
        answer_buyback(o2, self.owner, "refuse")  # the owner withdraws
        o2.refresh_from_db()
        self.assertEqual(o2.status, "cancelled")
        self.assertEqual(Wallet.for_user(self.owner).balance, bal)
        self.assertLedgerBalanced()

    def test_company_buys_on_the_market_and_parts_are_cancelled(self):
        from apps.investments.company import pay_dividend

        p = self.company()
        invest(self.inv1, p, 100, True)
        invest(self.inv2, p, 100, True)
        listing = create_listing(self.inv1, p, 50, D("1000"))
        buy(self.owner, listing, 50)
        self.assertFalse(Holding.objects.filter(user=self.owner, project=p).exists())
        self.assertEqual(Holding.objects.get(user=self.inv1, project=p).shares, 50)
        before = Wallet.for_user(self.inv2).balance
        pay_dividend(p, self.owner, D("15000"))  # 150 parts left: inv2 holds 100 of them
        self.assertEqual(Wallet.for_user(self.inv2).balance - before, D("9200"))
        self.assertLedgerBalanced()

    def test_pages(self):
        from django.test import Client

        from apps.investments.models import BuybackOffer

        p = self.company()
        c = Client()
        c.force_login(self.inv1)
        page = c.get(p.get_absolute_url()).content.decode()
        self.assertIn('name="shares"', page)
        self.assertIn('id="invest-form"', page)
        c.post(f"/fr/projects/{p.slug}/invest/", {"shares": "30", "risk": "on"})
        self.assertEqual(Holding.objects.get(user=self.inv1, project=p).shares, 30)
        home = Client().get("/fr/").content.decode()
        self.assertIn(p.title, home)

        owner = Client()
        owner.force_login(self.owner)
        page = owner.get(f"/fr/projects/{p.slug}/manage/").content.decode()
        for anchor in ('id="overview"', 'id="dividend"', 'id="shareholders"', 'id="buyback"', 'id="issue"'):
            self.assertIn(anchor, page)
        self.assertNotIn("/manage/buyback/", page)  # the old pro-rata form is not offered to companies
        owner.post(f"/fr/projects/{p.slug}/manage/dividend/", {"amount": "3000"})
        self.assertTrue(p.distributions.filter(kind="dividend").exists())
        self.assertIn(self.inv1.full_name, page)  # the owner sees full names
        owner.post(f"/fr/projects/{p.slug}/manage/buyback-offer/",
                   {"holder": self.inv1.pk, "shares": "10", "price": "1200"})
        offer = BuybackOffer.objects.get(project=p)
        page = c.get("/fr/portfolio/").content.decode()
        self.assertIn('id="offers"', page)
        c.post(f"/fr/projects/buyback-offer/{offer.pk}/", {"action": "counter", "shares": "10", "price": "1500"})
        offer.refresh_from_db()
        self.assertEqual(offer.waiting_on, "owner")
        owner.post(f"/fr/projects/buyback-offer/{offer.pk}/", {"action": "accept"})
        offer.refresh_from_db()
        self.assertEqual(offer.status, "accepted")
        owner.post(f"/fr/projects/{p.slug}/manage/close-offering/")
        p.refresh_from_db()
        self.assertFalse(p.offering_open)
        self.assertLedgerBalanced()

    def test_terms_form_asks_parts_and_price(self):
        from apps.projects.forms import TermsForm

        p = make_project(self.owner, kind="company", model="moucharaka")
        form = TermsForm(instance=p)
        self.assertEqual(list(form.fields)[0], "shares_offered")
        for gone in ("target_amount", "campaign_days", "duration_months", "investor_profit_share_pct", "exit_mode"):
            self.assertNotIn(gone, form.fields)
        form = TermsForm({"shares_offered": "500", "share_price": "2000"}, instance=p)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        p.refresh_from_db()
        self.assertEqual((p.total_shares, p.target_amount), (500, D("1000000")))



class CompanyIssuesAndOwnerPage(FlowBase):
    def company(self, n=500, price=1000):
        p = self.launch(kind="company", model="moucharaka", target=n * price, share_price=price)
        self.assertEqual(p.shares_issued, n)
        return p

    def test_close_cancels_unsold_then_new_issue_on_same_page(self):
        from apps.investments.company import approve_issue, close_offering, request_issue
        from apps.investments.models import ShareIssue

        p = self.company()
        invest(self.inv1, p, 150, True)
        invest(self.inv2, p, 50, True)
        with self.assertRaises(InvestmentError):  # parts still on sale
            request_issue(p, self.owner, 100, 1500)
        close_offering(p, self.owner)
        p.refresh_from_db()
        self.assertEqual((p.total_shares, p.shares_available), (200, 0))
        issue = request_issue(p, self.owner, 100, 1500, "Deuxième four")
        with self.assertRaises(InvestmentError):  # one request at a time
            request_issue(p, self.owner, 10, 1500)
        approve_issue(issue, self.staff)
        p.refresh_from_db()
        issue.refresh_from_db()
        self.assertEqual(issue.status, ShareIssue.Status.APPROVED)
        self.assertTrue(p.is_share_offering)
        self.assertEqual((p.total_shares, p.shares_available, p.share_price), (300, 100, D("1500")))
        # shareholders are told about the dilution: 75 % now, 50 % once the new parts are sold
        from apps.core.models import Notification

        n = Notification.objects.filter(user=self.inv1, title="Nouvelles parts émises").get()
        self.assertIn("75.0", n.body)
        self.assertIn("50.0", n.body)
        before = Wallet.for_user(self.owner).balance
        invest(make_user("New", balance=500_000), p, 100, True)
        p.refresh_from_db()
        self.assertFalse(p.offering_open)
        self.assertEqual(Wallet.for_user(self.owner).balance - before, D("139500"))  # 150 000 − 7 %
        self.assertLedgerBalanced()

    def test_rejected_or_cancelled_issue(self):
        from apps.investments.company import cancel_issue, close_offering, reject_issue, request_issue

        p = self.company()
        invest(self.inv1, p, 100, True)
        close_offering(p, self.owner)
        i1 = request_issue(p, self.owner, 50, 1000)
        reject_issue(i1, self.staff, "Expliquez l'usage des fonds")
        i2 = request_issue(p, self.owner, 50, 1000)
        cancel_issue(i2, self.owner)
        p.refresh_from_db()
        self.assertFalse(p.is_share_offering)
        self.assertEqual(p.total_shares, 100)

    def test_company_buying_last_parts_on_market_finishes_the_project(self):
        from apps.investments.company import close_offering

        p = self.company()
        invest(self.inv1, p, 100, True)
        close_offering(p, self.owner)
        listing = create_listing(self.inv1, p, 100, D("1000"))
        buy(self.owner, listing, 100)
        p.refresh_from_db()
        self.assertEqual(p.status, "completed")

    def test_owner_page_csv_and_staff_queue(self):
        from django.test import Client

        p = self.company()
        invest(self.inv1, p, 100, True)
        invest(self.inv2, p, 60, True)
        owner = Client()
        owner.force_login(self.owner)
        csv = owner.get(f"/fr/projects/{p.slug}/manage/shareholders.csv").content.decode("utf-8-sig")
        self.assertIn("Mariem Ahmed;100;62.50", csv)
        self.assertIn("Cheikh Ould Brahim;60;37.50", csv)
        stranger = Client()
        stranger.force_login(self.inv1)
        self.assertEqual(stranger.get(f"/fr/projects/{p.slug}/manage/shareholders.csv").status_code, 404)
        owner.post(f"/fr/projects/{p.slug}/manage/close-offering/")
        owner.post(f"/fr/projects/{p.slug}/manage/issue/", {"shares": "40", "price": "1200", "reason": "Camion"})
        staff = Client()
        staff.force_login(self.staff)
        page = staff.get("/fr/staff/issues/").content.decode()
        self.assertIn("Camion", page)
        from apps.investments.models import ShareIssue

        staff.post("/fr/staff/issues/", {"id": ShareIssue.objects.get().pk, "action": "approve"})
        p.refresh_from_db()
        self.assertTrue(p.is_share_offering)
        page = owner.get(f"/fr/projects/{p.slug}/manage/").content.decode()
        self.assertIn("Il reste 40 parts en vente", page)


class ResetTestUserCommand(FlowBase):
    """manage.py reset_user: same account and identity verification, everything else back to zero."""

    def test_reset_owner_then_investor(self):
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from apps.core.models import Notification
        from apps.investments.company import pay_dividend, propose_buyback

        company = self.launch(kind="company", model="moucharaka", target=500_000, share_price=1000)
        invest(self.inv1, company, 100, True)
        invest(self.inv2, company, 50, True)
        pay_dividend(company, self.owner, D("15000"))
        propose_buyback(company, self.owner, self.inv1, 10, D("1200"))
        create_listing(self.inv2, company, 20, D("1000"))
        self.assertTrue(Notification.objects.filter(user=self.owner).exists())
        inv1_start = D("1000000")  # their balance before anything (see FlowBase)

        out = StringIO()
        call_command("reset_user", self.owner.phone, stdout=out)  # dry run
        self.assertIn("Nothing erased", out.getvalue())
        self.assertTrue(Project.objects.filter(owner=self.owner).exists())
        with self.assertRaises(CommandError):  # others invested: needs --force
            call_command("reset_user", self.owner.phone, "--yes", stdout=StringIO())
        call_command("reset_user", self.owner.phone, "--yes", "--force", stdout=StringIO())

        self.owner.refresh_from_db()
        self.assertEqual(self.owner.status, "approved")
        self.assertTrue(self.owner.check_password("Moucharaka#2026"))
        self.assertEqual(self.owner.kyc.status, "approved")
        w = Wallet.for_user(self.owner)
        self.assertEqual((w.balance, w.held), (D("0"), D("0")))
        self.assertFalse(Transaction.objects.filter(wallet=w).exists())
        self.assertFalse(Project.objects.filter(owner=self.owner).exists())
        self.assertFalse(Notification.objects.filter(user=self.owner).exists())
        self.assertFalse(TrustEvent.objects.filter(user=self.owner).exists())
        # investors got back what they put in this company (dividends received are taken back too)
        self.assertEqual(Wallet.for_user(self.inv1).balance, inv1_start)
        self.assertFalse(Holding.objects.filter(project=company).exists())
        self.assertLedgerBalanced()

        # now the investor can be reset too
        call_command("reset_user", self.inv1.phone, "--yes", stdout=StringIO())
        self.assertEqual(Wallet.for_user(self.inv1).balance, D("0"))
        self.inv1.refresh_from_db()
        self.assertTrue(self.inv1.is_approved)
        self.assertLedgerBalanced()

    def test_superuser_is_never_reset(self):
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from apps.accounts.models import User

        User.objects.filter(pk=self.staff.pk).update(is_superuser=True)
        with self.assertRaises(CommandError):
            call_command("reset_user", self.staff.phone, "--yes", stdout=StringIO())
