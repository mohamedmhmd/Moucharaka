import apps.accounts.phones
from django.db import migrations, models


def to_e164(apps, schema_editor):
    """Existing accounts were stored as 8 Mauritanian digits: prefix them with +222."""
    User = apps.get_model("accounts", "User")
    for user in User.objects.exclude(phone__startswith="+"):
        digits = "".join(c for c in user.phone if c.isdigit())
        user.phone = "+222" + digits[-8:]
        user.save(update_fields=["phone"])
    # Pending codes were hashed with the old format: drop them.
    apps.get_model("accounts", "PhoneOTP").objects.all().delete()


def to_local(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.filter(phone__startswith="+222"):
        user.phone = user.phone[4:]
        user.save(update_fields=["phone"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_staff_groups"),
    ]

    operations = [
        migrations.AlterField(
            model_name="phoneotp",
            name="phone",
            field=models.CharField(db_index=True, max_length=16),
        ),
        migrations.AlterField(
            model_name="user",
            name="phone",
            field=models.CharField(
                help_text="Format international E.164, ex. +22222123456",
                max_length=16,
                unique=True,
                validators=[apps.accounts.phones.validate_phone],
                verbose_name="téléphone",
            ),
        ),
        migrations.RunPython(to_e164, to_local),
    ]
