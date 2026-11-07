"""Bankily's public grid, as the cost of sending a withdrawal to a member's Bankily account:
client → client transfer fee + 20 % TOF (rounded up to the ouguiya), and 0.1 % TTE from 5 000 MRU.
Adjust in the admin once the merchant contract is known."""
from decimal import Decimal as D

from django.db import migrations

BANKILY = [  # from amount, flat, %, note
    ("0", "0", "0", "Gratuit jusqu'à 1 000"),
    ("1000.01", "6", "0", "4,31 + TOF"),
    ("3000.01", "11", "0", "8,62 + TOF"),
    ("5000", "11", "0.1", "8,62 + TOF, TTE 0,1 %"),
    ("100000.01", "21", "0.1", "17,24 + TOF, TTE"),
    ("200000.01", "32", "0.1", "25,86 + TOF, TTE"),
    ("300000.01", "42", "0.1", "34,48 + TOF, TTE"),
    ("400000.01", "52", "0.1", "43,10 + TOF, TTE"),
    ("500000.01", "73", "0.1", "60,34 + TOF, TTE"),
    ("1000000.01", "94", "0.1", "77,59 + TOF, TTE"),
]


def fill(apps, schema_editor):
    Fee = apps.get_model("wallet", "WithdrawalFee")
    if Fee.objects.filter(method="bankily").exists():
        return
    for frm, flat, pct, note in BANKILY:
        Fee.objects.create(method="bankily", from_amount=D(frm), flat_fee=D(flat), pct_fee=D(pct), note=note)


def empty(apps, schema_editor):
    apps.get_model("wallet", "WithdrawalFee").objects.filter(method="bankily").delete()


class Migration(migrations.Migration):
    dependencies = [("wallet", "0006_withdrawal_fees")]
    operations = [migrations.RunPython(fill, empty)]
