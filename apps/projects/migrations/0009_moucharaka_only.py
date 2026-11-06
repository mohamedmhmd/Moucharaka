"""The platform works only in Moucharaka.

- Mourabaha fee grids are closed to new requests.
- Existing Mourabaha projects become Moucharaka, keeping the agreed margin as
  the expected return. One-off operations already repay once at the end, so
  nothing changes for their investors. Only a project that still has a
  Mourabaha payment schedule (instalments) is left as it is, to finish its
  schedule."""
from django.db import migrations


def forwards(apps, schema_editor):
    FeePolicy = apps.get_model("projects", "FeePolicy")
    Project = apps.get_model("projects", "Project")
    FeePolicy.objects.filter(financing_model="mourabaha").update(is_enabled=False)
    for p in Project.objects.filter(financing_model="mourabaha", installments__isnull=True).distinct():
        if p.projected_annual_return_pct is None and p.margin_pct is not None:
            p.projected_annual_return_pct = p.margin_pct
        p.financing_model = "moucharaka"
        if not p.exit_mode:
            p.exit_mode = "diminishing"
        p.save(update_fields=["financing_model", "projected_annual_return_pct", "exit_mode"])


class Migration(migrations.Migration):
    dependencies = [("projects", "0008_shares_issued")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
