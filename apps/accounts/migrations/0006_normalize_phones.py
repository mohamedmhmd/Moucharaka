"""Store every phone in E.164. Accounts added from the admin before this fix kept
the number as typed ("36 12 34 56"), so their owners couldn't log in."""
from django.db import migrations


def normalize(apps, schema_editor):
    from apps.accounts.phones import normalize_phone

    User = apps.get_model("accounts", "User")
    taken = set(User.objects.values_list("phone", flat=True))
    for user in User.objects.all():
        phone = normalize_phone(user.phone)
        if phone and phone != user.phone and phone not in taken:
            taken.discard(user.phone)
            taken.add(phone)
            user.phone = phone
            user.save(update_fields=["phone"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_whatsapp")]
    operations = [migrations.RunPython(normalize, migrations.RunPython.noop)]
