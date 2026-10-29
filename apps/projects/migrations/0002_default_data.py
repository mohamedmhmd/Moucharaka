from django.db import migrations


def load(apps, schema_editor):
    from apps.projects.questionnaire import load_all

    load_all(apps)


class Migration(migrations.Migration):
    dependencies = [("projects", "0001_initial")]
    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
