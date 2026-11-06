"""Questions no longer asked: "Can someone stand guarantor for you?" and
"Do you accept interest-free financing?" (every project is Moucharaka anyway).
Past answers are kept in the database, they are just no longer asked or shown."""
from django.db import migrations

RETIRED = ["guarantor", "sharia_commitment"]


def forward(apps, schema_editor):
    apps.get_model("projects", "Question").objects.filter(code__in=RETIRED).update(active=False)


def backward(apps, schema_editor):
    apps.get_model("projects", "Question").objects.filter(code__in=RETIRED).update(active=True)


class Migration(migrations.Migration):
    dependencies = [("projects", "0009_moucharaka_only")]

    operations = [migrations.RunPython(forward, backward)]
