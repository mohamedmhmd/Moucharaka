"""Delete a test member and everything attached to them.

    python manage.py delete_user +22236123456          # shows what would be deleted
    python manage.py delete_user +22236123456 --yes    # deletes

Removes the account, identity file and documents, wallet and movements, deposits, withdrawals,
projects they own (with photos, documents, investments in them), their investments and shares,
market listings and trades, notifications, trust score, reviews, login codes and message log.
Fees the platform collected from these operations are taken back out of the platform wallet, so the
books stay balanced. The audit log keeps its lines (the person shows as "deleted").

To keep the account and start again from zero, use reset_user instead.
Only for test accounts: refuses a superuser. When other members invested in their projects, --force is
needed and those members get their money back.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.accounts.phones import normalize_phone
from apps.core.wipe import Wipe


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
        wipe = Wipe(user)
        summary = wipe.summary()
        for k, v in summary.items():
            self.stdout.write(f"  {k}: {v}")
        reason = wipe.blocked_reason("delete")
        if not yes:
            if reason:
                self.stdout.write(self.style.WARNING(reason))
            self.stdout.write(self.style.WARNING("Nothing deleted. Run again with --yes to delete."))
            return
        if reason and not force:
            raise CommandError(reason)
        wipe.run(delete_account=True)
        self.stdout.write(self.style.SUCCESS(f"Deleted {summary['account']} and all their data."))
