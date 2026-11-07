"""Called by deploy/backup.sh at the end of each run. Records the result and alerts staff on failure.

    python manage.py record_backup --status ok --stamp 2026-11-07_0315 --size 1234567 --uploaded
    python manage.py record_backup --status failed --message "disk full"
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.core.models import BackupRun
from apps.core.utils import N_, notify


class Command(BaseCommand):
    help = "Record the result of a backup run (used by deploy/backup.sh)."

    def add_arguments(self, parser):
        parser.add_argument("--status", choices=["ok", "failed"], required=True)
        parser.add_argument("--stamp", default="")
        parser.add_argument("--size", type=int, default=0)
        parser.add_argument("--uploaded", action="store_true")
        parser.add_argument("--message", default="")

    def handle(self, status, stamp, size, uploaded, message, **opts):
        run = BackupRun.objects.create(status=status, stamp=stamp, size_bytes=size, uploaded=uploaded,
                                       message=message[:500])
        if status == "failed" or (status == "ok" and not uploaded and message):
            for staff in User.objects.filter(is_superuser=True, is_active=True):
                notify(staff, N_("Sauvegarde : attention"), message[:300] or N_("La sauvegarde de cette nuit a échoué."),
                       url="/staff/", whatsapp=True)
        self.stdout.write(f"recorded backup {run.pk} ({status})")
