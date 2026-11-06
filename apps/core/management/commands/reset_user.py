"""Reset a test member to a fresh start, keeping their account.

    python manage.py reset_user +22236123456          # shows what would be erased
    python manage.py reset_user +22236123456 --yes    # erases

Kept: the account (number, name, password, language) and the identity verification (documents and
"verified" status), so the person can log in and invest straight away.
Erased: wallet back to 0 MRU, every money movement, deposits and withdrawals, projects they own
(with photos and documents), their investments and shares, market listings and trades, buyback
offers, notifications, trust score and history, reviews, favourites, questions, saved payment
numbers, login codes and message log.

Fees the platform took on these operations are taken back out of the platform wallet. When other
members invested in this person's projects, --force is needed and those members get their money back.
Refuses a superuser.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.accounts.phones import normalize_phone
from apps.core.wipe import Wipe


class Command(BaseCommand):
    help = "Reset a test member to zero, keeping the account and identity verification (dry run unless --yes)."

    def add_arguments(self, parser):
        parser.add_argument("phone", help="WhatsApp number of the account, e.g. +22236123456")
        parser.add_argument("--yes", action="store_true", help="really erase")
        parser.add_argument("--force", action="store_true",
                            help="also when other members invested in their projects or traded with them")

    def handle(self, phone, yes, force, **opts):
        user = User.objects.filter(phone=normalize_phone(phone)).first()
        if not user:
            raise CommandError(f"No account with the number {phone}.")
        if user.is_superuser:
            raise CommandError("This is an owner (superuser) account: it is never reset by this command.")
        wipe = Wipe(user)
        summary = wipe.summary()
        for k, v in summary.items():
            self.stdout.write(f"  {k}: {v}")
        self.stdout.write(f"  identity verification: kept ({user.get_status_display()})")
        reason = wipe.blocked_reason("reset")
        if not yes:
            if reason:
                self.stdout.write(self.style.WARNING(reason))
            self.stdout.write(self.style.WARNING("Nothing erased. Run again with --yes to reset."))
            return
        if reason and not force:
            raise CommandError(reason)
        wipe.run(delete_account=False)
        self.stdout.write(self.style.SUCCESS(f"Reset {summary['account']}: wallet at 0 MRU, history erased."))
