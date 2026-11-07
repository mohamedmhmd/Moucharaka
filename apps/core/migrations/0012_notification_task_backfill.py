"""Link team notifications sent before this update to the request they were about, when it can be found."""
import re

from django.db import migrations

PROJECT_URL = re.compile(r"^/(?:[a-z]{2}/)?staff/projects/(\d+)/")
TITLE = re.compile(r"«\s*(.+?)\s*»")


def backfill(apps, schema_editor):
    Notification = apps.get_model("core", "Notification")
    Deposit = apps.get_model("wallet", "DepositRequest")
    KYC = apps.get_model("accounts", "KYCProfile")
    Project = apps.get_model("projects", "Project")
    Settlement = apps.get_model("investments", "DealSettlement")
    Issue = apps.get_model("investments", "ShareIssue")
    for n in Notification.objects.filter(task="", user__is_staff=True).iterator():
        task = ""
        m = PROJECT_URL.match(n.url or "")
        if m:
            task = f"project:{m.group(1)}"
        elif "staff/deposits" in n.url:
            ref = (n.body or "").split(" ")[0]
            d = Deposit.objects.filter(reference=ref).first()
            task = f"deposit:{d.pk}" if d else ""
        elif "staff/kyc" in n.url:
            ks = list(KYC.objects.filter(full_name=(n.body or "").strip())[:2])
            task = f"kyc:{ks[0].pk}" if len(ks) == 1 else ""
        elif "staff/settlements" in n.url or "staff/issues" in n.url:
            t = TITLE.search(n.body or "")
            p = Project.objects.filter(title=t.group(1)).first() if t else None
            if p:
                model, kind = (Settlement, "settlement") if "settlements" in n.url else (Issue, "issue")
                o = model.objects.filter(project=p, created_at__lte=n.created_at).order_by("-created_at").first()
                task = f"{kind}:{o.pk}" if o else ""
        if task:
            Notification.objects.filter(pk=n.pk).update(task=task)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_notification_task"),
        ("wallet", "0005_deposit_ref_per_live_request"),
        ("accounts", "0011_kyc_international_address"),
        ("investments", "0005_share_issues"),
        ("projects", "0011_deal_operations_resale"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
