"""Launch simplification (November 2026):

- boutiques paused for new projects (fee grids closed; reopen in Administration › Grilles tarifaires);
- "Future entreprise" becomes "Entreprise existante ou en création";
- shorter questionnaire: education, dependents, references, debts, assets owned, stress test,
  late-sale plan, previous operations and the whole impact section are switched off
  (answers already given are kept, just no longer asked or shown);
- the word "tontine" removed from the financing-history choices;
- review fee 100 MRU for every project type.
"""
from django.db import migrations

RETIRED = ["owner_education", "owner_dependents", "owner_references", "existing_debt", "monthly_debt_payment",
           "assets_owned", "stress_plan", "deal_worst_case", "deal_history",
           "jobs_now", "jobs_after", "women_youth", "local_sourcing"]
SECTION_RENAMES = [("La future entreprise", "L'entreprise", "المؤسسة"), ("Finances et dettes", "Finances", "المالية")]


def forward(apps, schema_editor):
    Question = apps.get_model("projects", "Question")
    QuestionSection = apps.get_model("projects", "QuestionSection")
    FeePolicy = apps.get_model("projects", "FeePolicy")

    Question.objects.filter(code__in=RETIRED).update(active=False)
    q = Question.objects.filter(code="owner_previous_financing").first()
    if q:
        for c in q.choices:
            if c.get("value") == "tontine":
                c["fr"], c["ar"] = "Caisse d'entraide", "صندوق تضامني"
        q.save(update_fields=["choices"])
    for old_fr, new_fr, new_ar in SECTION_RENAMES:
        QuestionSection.objects.filter(title_fr=old_fr).update(title_fr=new_fr, title_ar=new_ar)

    FeePolicy.objects.update(review_fee=100)
    FeePolicy.objects.filter(kind="boutique").update(is_enabled=False)


def backward(apps, schema_editor):
    apps.get_model("projects", "Question").objects.filter(code__in=RETIRED).update(active=True)
    apps.get_model("projects", "FeePolicy").objects.filter(kind="boutique").update(is_enabled=True)


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_sharing")]
    operations = [migrations.RunPython(forward, backward)]
