from django.db import migrations


def load(apps, schema_editor):
    from apps.core.reference import load_reference

    load_reference(apps.get_model("core", "Wilaya"), apps.get_model("core", "Moughataa"))
    apps.get_model("core", "PlatformSettings").objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
