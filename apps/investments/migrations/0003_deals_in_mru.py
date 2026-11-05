"""One-off operations (kind "deal") now count in MRU, not in parts.

A "part" of a deal is worth 1 MRU, so every number of parts becomes an amount.
Existing deals are converted (parts × old price), their market listings are
withdrawn (a deal is no longer resold), and unpaid instalments are removed:
the owner now pays everything back once, at the end."""
from decimal import Decimal

from django.db import migrations

ONE = Decimal("1")


def forwards(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    Investment = apps.get_model("investments", "Investment")
    Holding = apps.get_model("investments", "Holding")
    Distribution = apps.get_model("investments", "Distribution")
    Payout = apps.get_model("investments", "Payout")
    Installment = apps.get_model("projects", "Installment")
    Listing = apps.get_model("market", "Listing")
    Trade = apps.get_model("market", "Trade")

    for p in Project.objects.filter(kind="deal"):
        price = p.share_price or ONE
        f = int(price) if price == int(price) and price >= 1 else 1
        if f > 1:
            for inv in Investment.objects.filter(project=p):
                inv.shares *= f
                inv.save(update_fields=["shares"])
            for h in Holding.objects.filter(project=p):
                h.shares *= f
                h.locked_shares = 0
                h.save(update_fields=["shares", "locked_shares"])
            for d in Distribution.objects.filter(project=p):
                d.shares_outstanding *= f
                d.shares_retired *= f
                d.per_share = (d.per_share / f).quantize(Decimal("0.0001"))
                d.save(update_fields=["shares_outstanding", "shares_retired", "per_share"])
            for po in Payout.objects.filter(distribution__project=p):
                po.shares *= f
                po.save(update_fields=["shares"])
            for t in Trade.objects.filter(project=p):
                t.shares *= f
                t.price_per_share = (t.price_per_share / f).quantize(Decimal("0.01"))
                t.save(update_fields=["shares", "price_per_share"])
            for li in Listing.objects.filter(project=p):
                li.shares *= f
                li.remaining *= f
                li.price_per_share = (li.price_per_share / f).quantize(Decimal("0.01"))
                li.save(update_fields=["shares", "remaining", "price_per_share"])
            p.shares_sold *= f
        Listing.objects.filter(project=p, status="active").update(status="cancelled")
        Holding.objects.filter(project=p).update(locked_shares=0)
        Installment.objects.filter(project=p).exclude(status="paid").filter(distributions__isnull=True).delete()
        p.share_price = ONE
        p.min_shares = 100
        p.trading_enabled = False
        p.save(update_fields=["share_price", "min_shares", "shares_sold", "trading_enabled"])


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0002_deal_settlement"),
        ("market", "0001_initial"),
        ("projects", "0006_optional_project_fields"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
