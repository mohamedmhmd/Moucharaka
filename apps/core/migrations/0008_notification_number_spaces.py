"""Notifications already sent wrote amounts with a plain space ("15 000"), which Arabic pages showed
as "000 15". Give them the same narrow no-break space as the rest of the site."""
import re

from django.db import migrations

GROUP = re.compile(r"(?<=\d) (?=\d{3}(?!\d))")


def fix(apps, schema_editor):
    Notification = apps.get_model("core", "Notification")
    for n in Notification.objects.filter(body__regex=r"[0-9] [0-9]{3}") | Notification.objects.filter(
            title__regex=r"[0-9] [0-9]{3}"):
        n.title = GROUP.sub(" ", n.title)
        n.body = GROUP.sub(" ", n.body)
        n.save(update_fields=["title", "body"])


class Migration(migrations.Migration):
    dependencies = [("core", "0007_backup_runs")]
    operations = [migrations.RunPython(fix, migrations.RunPython.noop)]
