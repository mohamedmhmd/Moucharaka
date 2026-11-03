"""Launch settings (November 2026): deposits go to 33132023 (Bankily, Masrvi and Sedad),
featured listing 100 MRU per 7 days. Both can be changed in Administration › Paramètres de la plateforme."""
from django.db import migrations

ESCROW_NUMBER = "33132023"


def forward(apps, schema_editor):
    PlatformSettings = apps.get_model("core", "PlatformSettings")
    s, _created = PlatformSettings.objects.get_or_create(pk=1)
    s.merchant_bankily = s.merchant_masrvi = s.merchant_sedad = ESCROW_NUMBER
    s.featured_fee = 100
    s.save()


class Migration(migrations.Migration):
    dependencies = [("core", "0002_reference_data")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
