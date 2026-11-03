"""Delete a test member and everything attached to them.

    python manage.py delete_user +22236123456          # shows what would be deleted
    python manage.py delete_user +22236123456 --yes    # deletes

Removes: the account, identity file and its documents, wallet and its movements, deposits, withdrawals,
payment accounts, projects they own (with photos, documents, reports, investments in them), their
investments and shares, market listings and trades, notifications, trust score, reviews, login codes
and WhatsApp message log. Fees the platform collected from these test operations are taken back out
of the platform wallet, so the books stay balanced. The audit log keeps its lines (the person shows as
"deleted"), as a trace that something was removed.

Only for test accounts: refuses a superuser. When other members invested in their projects, --force is
needed and those members get their money back. Someone who invested in another member's project is
deleted after that project's owner (otherwise the books would no longer balance).
"""
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Sum

from apps.accounts.models import PhoneOTP, User
from apps.accounts.phones import normalize_phone
from apps.investments.models import Distribution, Holding, Investment, Payout
from apps.market.models import Listing, Trade
from apps.projects.models import Project
from apps.sms.models import SMSMessage
from apps.wallet.models import DepositRequest, Transaction, Wallet, WithdrawalRequest


def _delete_files(objects, field):
    for obj in objects:
        f = getattr(obj, field, None)
        if f:
            try:
                f.storage.delete(f.name)
            except Exception:  # noqa: BLE001 - a missing file must not stop the clean-up
                pass


class Command(BaseCommand):
    help = "Delete a test member and all their data (dry run unless --yes)."

    def add_arguments(self, parser):
        parser.add_argument("phone", help="WhatsApp number of the account, e.g. +22236123456")
        parser.add_argument("--yes", action="store_true", help="really delete")
        parser.add_argument("--force", action="store_true",
                            help="also when other members invested in their projects or traded with them")

    def handle(self, phone, yes, force, **opts):
        user = User.objects.filter(phone=normalize_phone(phone)).first()
        if not user:
            raise CommandError(f"No account with the number {phone}.")
        if user.is_superuser:
            raise CommandError("This is an owner (superuser) account: it is never deleted by this command.")

        projects = Project.objects.filter(owner=user)
        others_invested = Investment.objects.filter(project__in=projects).exclude(investor=user)
        others_traded = Trade.objects.filter(Q(buyer=user) | Q(seller=user)).exclude(buyer=user, seller=user)
        invested_elsewhere = (Investment.objects.filter(investor=user).exclude(project__owner=user).exists()
                              or Holding.objects.filter(user=user, shares__gt=0).exclude(project__owner=user).exists())
        blocked_msg = ""
        if others_invested.exists() or others_traded.exists():
            blocked_msg = ("Other members invested in this person's projects or traded shares with them. Add --force "
                           "to delete anyway: the money those members put in these projects goes back to their wallets.")
        elif invested_elsewhere:
            blocked_msg = ("This person invested in another member's project, so their money is now with that "
                           "project. Delete the project owner first (with --force: the money comes back), then this "
                           "account.")
        blocked = bool(blocked_msg) and not force

        wallet = Wallet.objects.filter(user=user).first()
        # Their own movements, every movement on their projects, and platform fees taken on their withdrawals
        own_refs = list(WithdrawalRequest.objects.filter(user=user).values_list("reference", flat=True))
        q = Q(project__in=projects) | Q(wallet__kind="platform", reference__in=own_refs)
        if wallet:
            q |= Q(wallet=wallet)
        tx = Transaction.objects.filter(q)
        summary = {
            "account": f"{user.full_name} ({user.phone})",
            "projects": projects.count(),
            "money movements": tx.count(),
            "deposits": DepositRequest.objects.filter(user=user).count(),
            "withdrawals": WithdrawalRequest.objects.filter(user=user).count(),
            "investments": Investment.objects.filter(Q(investor=user) | Q(project__in=projects)).count(),
        }
        for k, v in summary.items():
            self.stdout.write(f"  {k}: {v}")
        if not yes:
            if blocked:
                self.stdout.write(self.style.WARNING(blocked_msg))
            self.stdout.write(self.style.WARNING("Nothing deleted. Run again with --yes to delete."))
            return
        if blocked:
            raise CommandError(blocked_msg)

        with transaction.atomic():
            # 1. Take each movement back out of the other wallets it touched (platform fees, other test users)
            reverse = defaultdict(lambda: [Decimal("0"), Decimal("0")])
            for row in tx.exclude(wallet=wallet).values("wallet").annotate(a=Sum("amount"), h=Sum("held_delta")):
                reverse[row["wallet"]] = [row["a"] or 0, row["h"] or 0]
            for wallet_id, (amount, held) in reverse.items():
                w = Wallet.objects.select_for_update().get(pk=wallet_id)
                w.balance = max(Decimal("0"), w.balance - amount)
                w.held = max(Decimal("0"), w.held - held)
                w.save(update_fields=["balance", "held"])

            # 2. Market, payouts, shares, investments
            Trade.objects.filter(Q(buyer=user) | Q(seller=user) | Q(project__in=projects)).delete()
            Listing.objects.filter(Q(seller=user) | Q(project__in=projects)).delete()
            Payout.objects.filter(Q(user=user) | Q(distribution__project__in=projects)).delete()
            Distribution.objects.filter(project__in=projects).delete()
            Holding.objects.filter(Q(user=user) | Q(project__in=projects)).delete()
            Investment.objects.filter(Q(investor=user) | Q(project__in=projects)).delete()
            tx.delete()

            # 3. Deposits and withdrawals (with receipt files)
            deposits = DepositRequest.objects.filter(user=user)
            _delete_files(deposits, "receipt")
            deposits.delete()
            WithdrawalRequest.objects.filter(user=user).delete()

            # 4. Projects and their files
            for p in projects:
                _delete_files([p], "cover")
                _delete_files(p.images.all(), "image")
                _delete_files(p.documents.all(), "file")
                _delete_files(p.reports.all(), "attachment")
                _delete_files(p.updates.all(), "image")
            projects.delete()

            # 5. Identity documents, wallet, login codes, message log, then the account
            kyc = getattr(user, "kyc", None)
            if kyc:
                _delete_files([kyc], "id_front")
                _delete_files([kyc], "id_back")
            if wallet:
                wallet.delete()
            PhoneOTP.objects.filter(phone=user.phone).delete()
            SMSMessage.objects.filter(phone=user.phone).delete()
            user.delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {summary['account']} and all their data."))
