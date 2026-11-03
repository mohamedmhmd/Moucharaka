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
        p = self.launch(kind="deal", model="mourabaha", target=300_000, margin=10, duration_months=3)
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
        p = self.launch(kind="deal", model="mourabaha", target=100_000, margin=8, duration_months=2)
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
