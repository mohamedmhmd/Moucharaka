"""Two staff roles. Superusers keep every right; add staff members to one of
these groups from the admin (Utilisateurs › Groupes)."""
from django.db import migrations

GROUPS = {
    "Conformité": {  # KYC, project review, reports, trust
        "accounts": ["view_user", "change_user", "view_kycprofile", "change_kycprofile"],
        "projects": ["view_project", "change_project", "view_financialreport", "change_financialreport",
                     "view_projectdocument", "change_projectdocument", "view_question", "change_question",
                     "add_question", "view_questionsection", "change_questionsection"],
        "trust": ["view_trustscore", "view_trustevent", "add_trustevent", "view_review", "change_review"],
        "core": ["view_auditlog"],
    },
    "Opérations": {  # money desk
        "wallet": ["view_wallet", "view_transaction", "view_depositrequest", "change_depositrequest",
                   "view_withdrawalrequest", "change_withdrawalrequest"],
        "investments": ["view_investment", "view_holding", "view_distribution"],
        "market": ["view_listing", "change_listing", "view_trade"],
        "projects": ["view_project", "view_installment"],
        "sms": ["view_smsmessage", "view_smsprovider"],
        "core": ["view_auditlog"],
    },
}


def create(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, perms in GROUPS.items():
        g, _c = Group.objects.get_or_create(name=name)
        for app_label, codenames in perms.items():
            g.permissions.add(*Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames))


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_initial"), ("auth", "0012_alter_user_first_name_max_length"),
        ("projects", "0002_default_data"), ("wallet", "0001_initial"), ("investments", "0001_initial"),
        ("market", "0001_initial"), ("trust", "0001_initial"), ("sms", "0001_initial"), ("core", "0002_reference_data"),
    ]
    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
