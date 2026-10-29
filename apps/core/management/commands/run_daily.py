"""Daily maintenance. Schedule it once a day, e.g. with cron:

    15 2 * * *  cd /srv/moucharaka && .venv/bin/python manage.py run_daily
"""
from django.core.management.base import BaseCommand

from apps.projects.jobs import run_all


class Command(BaseCommand):
    help = "Close campaigns, flag late installments and reports, expire listings/deposits, recompute trust scores."

    def handle(self, *args, **options):
        result = run_all()
        for k, v in result.items():
            self.stdout.write(f"{k}: {v}")
