"""Identity file simplified: one full-name field (Latin or Arabic letters),
no selfie, no proof of address. Existing Latin names are kept."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_normalize_phones")]

    operations = [
        migrations.RenameField("kycprofile", "full_name_fr", "full_name"),
        migrations.AlterField(
            "kycprofile", "full_name",
            models.CharField(max_length=150, verbose_name="nom complet",
                             help_text="En lettres latines ou en arabe, comme sur votre pièce d'identité."),
        ),
        migrations.RemoveField("kycprofile", "full_name_ar"),
        migrations.RemoveField("kycprofile", "selfie"),
        migrations.RemoveField("kycprofile", "proof_of_address"),
    ]
