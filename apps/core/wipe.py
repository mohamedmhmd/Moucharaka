"""Erase a test member's activity, keeping the books balanced.

Used by two commands:
- delete_user: removes the account too (and its identity documents);
- reset_user: keeps the account, its password and its identity verification,
  as if the person had just signed up and been verified.

Money that other members put in this person's projects goes back to their
wallets; fees the platform took on these operations are taken back out of
the platform wallet.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from apps.accounts.models import PhoneOTP
from apps.contracts.models import Contract
from apps.core.models import Notification
from apps.investments.models import (BuybackOffer, DealSettlement, Distribution, Holding, Investment, Payout,
                                     ShareIssue)
from apps.market.models import Listing, Trade
from apps.projects.models import Favorite, Project, ProjectInterest, ProjectQuestion
from apps.sms.models import SMSMessage
from apps.trust.models import Review, TrustEvent, TrustScore
from apps.wallet.models import DepositRequest, PaymentAccount, Transaction, Wallet, WithdrawalRequest


def _delete_files(objects, field):
    for obj in objects:
        f = getattr(obj, field, None)
        if f:
            try:
                f.storage.delete(f.name)
            except Exception:  # noqa: BLE001 - a missing file must not stop the clean-up
                pass


class Wipe:
    def __init__(self, user):
        self.user = user
        self.projects = Project.objects.filter(owner=user)
        self.wallet = Wallet.objects.filter(user=user).first()
        # Their own movements, every movement on their projects, and platform fees taken on their withdrawals
        own_refs = list(WithdrawalRequest.objects.filter(user=user).values_list("reference", flat=True))
        q = Q(project__in=self.projects) | Q(wallet__kind="platform", reference__in=own_refs)
        if self.wallet:
            q |= Q(wallet=self.wallet)
        self.tx = Transaction.objects.filter(q)

    def summary(self):
        u = self.user
        return {
            "account": f"{u.full_name} ({u.phone})",
            "projects": self.projects.count(),
            "money movements": self.tx.count(),
            "deposits": DepositRequest.objects.filter(user=u).count(),
            "withdrawals": WithdrawalRequest.objects.filter(user=u).count(),
            "investments": Investment.objects.filter(Q(investor=u) | Q(project__in=self.projects)).count(),
            "notifications": Notification.objects.filter(user=u).count(),
            "contracts": Contract.objects.filter(Q(project__in=self.projects) | Q(created_by=u)).distinct().count(),
        }

    def blocked_reason(self, verb="delete"):
        """Why it should not run without --force (empty when it is safe)."""
        u = self.user
        others_invested = Investment.objects.filter(project__in=self.projects).exclude(investor=u).exists()
        others_traded = Trade.objects.filter(Q(buyer=u) | Q(seller=u)).exclude(buyer=u, seller=u).exists()
        invested_elsewhere = (Investment.objects.filter(investor=u).exclude(project__owner=u).exists()
                              or Holding.objects.filter(user=u, shares__gt=0).exclude(project__owner=u).exists())
        if others_invested or others_traded:
            return (f"Other members invested in this person's projects or traded shares with them. Add --force "
                    f"to {verb} anyway: the money those members put in these projects goes back to their wallets.")
        if invested_elsewhere:
            return (f"This person invested in another member's project, so their money is now with that project. "
                    f"First {verb} that project's owner with --force (the money comes back), then this account.")
        return ""

    @transaction.atomic
    def run(self, delete_account):
        u, projects, wallet, tx = self.user, self.projects, self.wallet, self.tx

        # 0. Buyback offers made to this person by other companies: give the money back to those owners
        from apps.investments.company import _release

        for offer in BuybackOffer.objects.filter(holder=u, status="pending").exclude(project__in=projects):
            _release(offer)
            offer.status = "cancelled"
            offer.save()

        # 1. Take each movement back out of the other wallets it touched (platform fees, other members)
        reverse = defaultdict(lambda: [Decimal("0"), Decimal("0")])
        for row in tx.exclude(wallet=wallet).values("wallet").annotate(a=Sum("amount"), h=Sum("held_delta")):
            reverse[row["wallet"]] = [row["a"] or 0, row["h"] or 0]
        for wallet_id, (amount, held) in reverse.items():
            w = Wallet.objects.select_for_update().get(pk=wallet_id)
            w.balance = max(Decimal("0"), w.balance - amount)
            w.held = max(Decimal("0"), w.held - held)
            w.save(update_fields=["balance", "held"])

        # 2. Contracts (test data only: real contracts are never deleted), market, payouts, shares, investments
        Contract.objects.filter(Q(project__in=projects) | Q(created_by=u) | Q(signatures__user=u)).distinct().delete()
        Trade.objects.filter(Q(buyer=u) | Q(seller=u) | Q(project__in=projects)).delete()
        Listing.objects.filter(Q(seller=u) | Q(project__in=projects)).delete()
        DealSettlement.objects.filter(project__in=projects).delete()
        BuybackOffer.objects.filter(Q(holder=u) | Q(project__in=projects)).delete()
        ShareIssue.objects.filter(project__in=projects).delete()
        Payout.objects.filter(Q(user=u) | Q(distribution__project__in=projects)).delete()
        Distribution.objects.filter(project__in=projects).delete()
        Holding.objects.filter(Q(user=u) | Q(project__in=projects)).delete()
        Investment.objects.filter(Q(investor=u) | Q(project__in=projects)).delete()
        tx.delete()

        # 3. Deposits and withdrawals (with receipt files)
        deposits = DepositRequest.objects.filter(user=u)
        _delete_files(deposits, "receipt")
        deposits.delete()
        WithdrawalRequest.objects.filter(user=u).delete()

        # 4. Projects and their files
        for p in projects:
            _delete_files([p], "cover")
            _delete_files(p.images.all(), "image")
            _delete_files(p.documents.all(), "file")
            _delete_files(p.reports.all(), "attachment")
            _delete_files(p.updates.all(), "image")
        projects.delete()

        # 5. Login codes and message log
        PhoneOTP.objects.filter(phone=u.phone).delete()
        SMSMessage.objects.filter(phone=u.phone).delete()

        if delete_account:
            kyc = getattr(u, "kyc", None)
            if kyc:
                _delete_files([kyc], "id_front")
                _delete_files([kyc], "id_back")
            if wallet:
                wallet.delete()
            u.delete()  # notifications, trust score, favourites... go with the account
            return

        # Reset: same account, empty history. Identity verification and password are kept.
        if wallet:
            wallet.balance = wallet.held = Decimal("0")
            wallet.save(update_fields=["balance", "held"])
        Notification.objects.filter(user=u).delete()
        TrustEvent.objects.filter(user=u).delete()
        TrustScore.objects.filter(user=u).delete()
        Review.objects.filter(Q(reviewer=u) | Q(owner=u)).delete()
        Favorite.objects.filter(user=u).delete()
        ProjectInterest.objects.filter(user=u).delete()
        ProjectQuestion.objects.filter(asker=u).delete()
        PaymentAccount.objects.filter(user=u).delete()
