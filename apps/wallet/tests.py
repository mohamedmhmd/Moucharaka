from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import PhoneOTP
from apps.core.factories import make_user
from apps.sms.backends import ConsoleBackend
from apps.wallet.models import DepositRequest, PaymentAccount, Wallet, WithdrawalRequest
from apps.wallet.services import WalletError, confirm_deposit, request_withdrawal


def last_code():
    return "".join(c for c in ConsoleBackend.outbox[-1][1].split(":")[1] if c.isdigit())[:6]


@override_settings(DEBUG=True)
class PaymentAccountTests(TestCase):
    def setUp(self):
        cache.clear()
        # Diaspora member: WhatsApp number in France, Bankily account in Mauritania
        self.user = make_user("Moussa Paris", phone="+33612345678", balance=50_000)
        self.client.force_login(self.user)

    def add(self, **data):
        base = {"method": "bankily", "number": "36 11 22 33", "holder_name": "Moussa Ba", "bank_name": "", "label": ""}
        base.update(data)
        return self.client.post("/fr/wallet/accounts/add/", base)

    def test_add_validate_and_default(self):
        r = self.add(number="+33 6 98 76 54 32")  # a French number can't be a Bankily account
        self.assertContains(r, "numéros mauritaniens")
        r = self.add()
        self.assertRedirects(r, "/fr/wallet/accounts/")
        acc = PaymentAccount.objects.get(user=self.user)
        self.assertEqual(acc.number, "+22236112233")
        self.assertTrue(acc.is_default)  # first account becomes default
        self.assertContains(self.add(), "déjà enregistré")
        r = self.add(method="bank", number="MR13 0002 0001 0100 0012 3456 753", bank_name="")
        self.assertContains(r, "nom de la banque")
        self.add(method="bank", number="MR13 0002 0001 0100 0012 3456 753", bank_name="BMCI", is_default="on")
        bank = PaymentAccount.objects.get(method="bank")
        self.assertEqual(bank.number, "MR1300020001010000123456753")
        acc.refresh_from_db()
        self.assertFalse(acc.is_default)
        self.assertTrue(self.user.notifications.filter(title__contains="compte de paiement").exists())

    def test_withdrawal_hold_and_verification_by_deposit(self):
        self.add()
        acc = PaymentAccount.objects.get(user=self.user)
        self.assertFalse(acc.can_receive_withdrawal)
        with self.assertRaises(WalletError):
            request_withdrawal(self.user, Decimal("1000"), acc)
        # A confirmed deposit from this account verifies it immediately
        r = self.client.post("/fr/wallet/deposit/", {"amount": "2000", "account": acc.pk})
        dep = DepositRequest.objects.get(user=self.user)
        self.assertRedirects(r, f"/fr/wallet/deposit/{dep.reference}/")
        self.assertEqual((dep.method, dep.payer_phone), ("bankily", "+22236112233"))
        confirm_deposit(dep)
        acc.refresh_from_db()
        self.assertIsNotNone(acc.verified_at)
        # Withdraw through the web flow, confirmed by a WhatsApp code
        r = self.client.post("/fr/wallet/withdraw/", {"amount": "1000", "account": acc.pk})
        self.assertContains(r, "Code reçu sur WhatsApp")
        r = self.client.post("/fr/wallet/withdraw/", {"code": last_code()})
        self.assertRedirects(r, "/fr/wallet/")
        wr = WithdrawalRequest.objects.get(user=self.user)
        self.assertEqual((wr.payment_account, wr.destination, wr.method), (acc, "+22236112233", "bankily"))
        self.assertTrue(PhoneOTP.objects.filter(phone="+33612345678", purpose="withdraw").exists())

    def test_hold_expires_and_remove(self):
        self.add()
        acc = PaymentAccount.objects.get(user=self.user)
        PaymentAccount.objects.filter(pk=acc.pk).update(created_at=timezone.now() - timedelta(hours=25))
        acc.refresh_from_db()
        wr = request_withdrawal(self.user, Decimal("1000"), acc)
        self.assertEqual(Wallet.for_user(self.user).held, wr.total)
        r = self.client.post(f"/fr/wallet/accounts/{acc.pk}/remove/")
        acc.refresh_from_db()
        self.assertTrue(acc.is_active)  # pending withdrawal blocks removal
        WithdrawalRequest.objects.filter(pk=wr.pk).update(status="paid")
        self.client.post(f"/fr/wallet/accounts/{acc.pk}/remove/")
        acc.refresh_from_db()
        self.assertFalse(acc.is_active)
        r = self.client.get("/fr/wallet/withdraw/")
        self.assertRedirects(r, "/fr/wallet/accounts/add/?next=/fr/wallet/withdraw/")

    def test_other_users_account_rejected(self):
        other = make_user("Other")
        acc = PaymentAccount.objects.create(user=other, method="sedad", number="+22222000999", holder_name="X",
                                            verified_at=timezone.now())
        with self.assertRaises(WalletError):
            request_withdrawal(self.user, Decimal("1000"), acc)
        self.assertEqual(self.client.post(f"/fr/wallet/accounts/{acc.pk}/remove/").status_code, 404)


class TransactionIdTests(TestCase):
    def setUp(self):
        self.a = make_user("Payer A")
        self.b = make_user("Payer B")

    def dep(self, user, method, ref="", status="proof"):
        return DepositRequest.objects.create(user=user, amount=Decimal("1000"), method=method, external_ref=ref,
                                             status=status)

    def test_same_id_allowed_on_different_services(self):
        self.dep(self.a, "bankily", "123456")
        self.dep(self.b, "sedad", "123456")
        self.dep(self.b, "masrvi", "123456")
        self.assertEqual(DepositRequest.objects.filter(external_ref="123456").count(), 3)

    def test_same_id_refused_twice_on_one_service_even_with_spaces_or_case(self):
        from apps.wallet.forms import DepositProofForm
        self.dep(self.a, "sedad", "ab12cd")
        d = self.dep(self.b, "sedad", status="pending")
        form = DepositProofForm({"external_ref": " AB 12 CD "}, instance=d)
        self.assertFalse(form.is_valid())
        self.assertIn("external_ref", form.errors)

    def test_refused_request_frees_its_id(self):
        from apps.wallet.forms import DepositProofForm
        self.dep(self.a, "bankily", "999", status="rejected")
        d = self.dep(self.a, "bankily", status="pending")
        form = DepositProofForm({"external_ref": "999"}, instance=d)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(DepositRequest.objects.filter(external_ref="999").count(), 2)

    def test_gateway_cannot_confirm_with_an_id_already_used(self):
        self.dep(self.a, "bankily", "777", status="confirmed")
        d = self.dep(self.b, "bankily", status="pending")
        with self.assertRaises(WalletError):
            confirm_deposit(d, external_ref="777")
