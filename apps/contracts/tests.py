from datetime import timedelta
from decimal import Decimal as D

from django.test import Client, TestCase
from django.utils import timezone

from apps.core.factories import make_project, make_user
from apps.investments.models import Holding, Investment
from apps.investments.services import invest, release_funds
from apps.market.models import Listing
from apps.projects.services import approve_project, submit_project
from apps.wallet.models import Wallet

from .models import Contract
from .testing import sign_pending


class SigningTests(TestCase):
    def setUp(self):
        self.staff = make_user("Staff Member", staff=True)
        self.owner = make_user("Sidi Mohamed", balance=50_000)
        self.inv = make_user("Mariem Ahmed", balance=1_000_000)
        self.inv2 = make_user("Cheikh Brahim", balance=1_000_000)
        self.c = Client()
        self.c.force_login(self.inv)

    def launch(self, **kw):
        p = make_project(self.owner, **kw)
        submit_project(p, self.owner)
        p.refresh_from_db()
        approve_project(p, self.staff, "B")
        p.refresh_from_db()
        return p

    def start_deal_investment(self, p, amount="100000"):
        r = self.c.post(f"/fr/projects/{p.slug}/invest/", {"amount": amount, "risk": "on"})
        return Contract.objects.get(reference=r["Location"].split("/contracts/")[1].split("/")[0])

    def test_contract_text_identity_and_seal(self):
        p = self.launch(kind="deal", model="moucharaka", target=300_000, projected=15)
        contract = self.start_deal_investment(p)
        page = self.c.get(f"/fr/contracts/{contract.reference}/sign/").content.decode()
        self.assertIn("Mode développement", page)  # no WhatsApp provider active: code shown on screen
        for text in ("Mariem Ahmed", self.inv.kyc.nni, "Sidi Mohamed", "100 000", "Nouakchott", p.title):
            self.assertIn(text, contract.body)
        self.assertEqual(contract.body_hash, Contract.fingerprint(contract.body))
        # the other party is named, but their NNI and phone stay private
        self.assertNotIn(self.owner.kyc.nni, contract.body)
        self.assertIn(self.owner.public_id, contract.body)
        # wrong code: nothing signed, nothing paid
        r = self.c.post(f"/fr/contracts/{contract.reference}/sign/", {"action": "sign", "accept": "1",
                                                                        "code": "000000"})
        contract.refresh_from_db()
        self.assertEqual(contract.status, "pending")
        self.assertEqual(Wallet.for_user(self.inv).held, D("0"))
        contract, r = sign_pending(self.c, self.inv)
        self.assertEqual(contract.status, "signed")
        self.assertEqual(Wallet.for_user(self.inv).held, D("100000"))
        sig = contract.signatures.get()
        self.assertEqual((sig.role, sig.full_name, sig.nni, sig.method), ("investor", self.inv.kyc.full_name,
                                                                           self.inv.kyc.nni, "whatsapp_otp"))
        self.assertTrue(sig.otp_id)
        self.assertEqual(contract.seal_hash, contract.compute_seal())
        self.assertEqual(contract.object_ref, Investment.objects.get(investor=self.inv).reference)
        page = self.c.get(contract.get_absolute_url()).content.decode()
        self.assertIn("Intégrité vérifiée", page)
        # a change to the stored text is detected
        Contract.objects.filter(pk=contract.pk).update(body=contract.body.replace("100 000", "10 000"))
        self.assertIn("ne correspond plus", self.c.get(contract.get_absolute_url()).content.decode())

    def test_must_tick_the_box_and_can_abandon(self):
        p = self.launch(kind="deal", model="moucharaka", target=300_000)
        contract = self.start_deal_investment(p)
        contract, _r = sign_pending(self.c, self.inv, accept=False)
        self.assertEqual(contract.status, "pending")
        self.c.post(f"/fr/contracts/{contract.reference}/sign/", {"action": "cancel"})
        contract.refresh_from_db()
        self.assertEqual(contract.status, "cancelled")
        self.assertFalse(Investment.objects.exists())

    def test_expired_contract_is_refused(self):
        p = self.launch(kind="deal", model="moucharaka", target=300_000)
        contract = self.start_deal_investment(p)
        Contract.objects.filter(pk=contract.pk).update(created_at=timezone.now() - timedelta(hours=1))
        contract, _r = sign_pending(self.c, self.inv)
        self.assertEqual(contract.status, "cancelled")
        self.assertFalse(Investment.objects.exists())

    def test_refusal_at_signing_cancels_contract_and_moves_no_money(self):
        p = self.launch(kind="company", model="moucharaka", target=200_000, share_price=1000)
        self.c.post(f"/fr/projects/{p.slug}/invest/", {"shares": "80", "risk": "on"})
        # meanwhile, the sale is stopped
        from apps.investments.company import close_offering

        close_offering(p, self.owner)
        contract, _r = sign_pending(self.c, self.inv)
        self.assertEqual(contract.status, "cancelled")
        self.assertTrue(contract.error)
        self.assertEqual(Wallet.for_user(self.inv).balance, D("1000000"))

    def test_cancelled_investment_terminates_contract_and_visibility(self):
        p = self.launch(kind="deal", model="moucharaka", target=300_000)
        self.start_deal_investment(p)
        contract, _r = sign_pending(self.c, self.inv)
        owner = Client()
        owner.force_login(self.owner)
        self.assertEqual(owner.get(contract.get_absolute_url()).status_code, 200)  # the owner is a party
        stranger = Client()
        stranger.force_login(self.inv2)
        self.assertEqual(stranger.get(contract.get_absolute_url()).status_code, 404)
        self.assertIn(contract.reference, self.c.get("/fr/contracts/").content.decode())
        inv = Investment.objects.get(investor=self.inv)
        self.c.post(f"/fr/projects/investment/{inv.pk}/cancel/")
        contract.refresh_from_db()
        self.assertEqual(contract.status, "terminated")

    def test_owner_signs_funding_before_release(self):
        p = self.launch(kind="deal", model="moucharaka", target=200_000)
        invest(self.inv, p, 80_000, True)
        invest(self.inv2, p, 80_000, True)
        invest(make_user("Third", balance=100_000), p, 40_000, True)
        p.refresh_from_db()
        self.assertEqual(p.status, "funded")
        staff = Client()
        staff.force_login(self.staff)
        staff.post(f"/fr/staff/projects/{p.pk}/release/")
        p.refresh_from_db()
        self.assertEqual(p.status, "funded")  # blocked: the owner has not signed
        owner = Client()
        owner.force_login(self.owner)
        self.assertIn("sign-funding", owner.get(f"/fr/projects/{p.slug}/manage/").content.decode())
        owner.post(f"/fr/projects/{p.slug}/manage/sign-funding/")
        contract, _r = sign_pending(owner, self.owner)
        self.assertEqual((contract.kind, contract.status), ("funding", "signed"))
        self.assertIn("Cheikh Brahim", contract.body)  # investors listed in the annex
        self.assertFalse(contract.viewers.filter(pk=self.inv.pk).exists())  # only the owner (and staff) read it
        staff.post(f"/fr/staff/projects/{p.pk}/release/")
        p.refresh_from_db()
        self.assertEqual(p.status, "active")

    def test_company_submission_is_signed(self):
        p = make_project(self.owner, kind="company", model="moucharaka", target=500_000, share_price=1000)
        owner = Client()
        owner.force_login(self.owner)
        owner.post(f"/fr/projects/{p.slug}/edit/submit/", {})
        p.refresh_from_db()
        self.assertEqual(p.status, "draft")  # not sent before signing
        contract, _r = sign_pending(owner, self.owner)
        p.refresh_from_db()
        self.assertEqual((contract.kind, p.status), ("share_issue", "submitted"))
        self.assertIn("500 part", contract.body)

    def test_market_sale_and_purchase_carry_both_signatures(self):
        p = self.launch(kind="company", model="moucharaka", target=500_000, share_price=1000)
        invest(self.inv, p, 100, True)
        self.c.post(f"/fr/market/sell/{p.slug}/", {"shares": "40", "price": "1100", "allow_partial": "on"})
        offer_contract, _r = sign_pending(self.c, self.inv)
        self.assertEqual((offer_contract.kind, offer_contract.status), ("sale_offer", "signed"))
        listing = Listing.objects.get(seller=self.inv)
        buyer = Client()
        buyer.force_login(self.inv2)
        buyer.post(f"/fr/market/listing/{listing.pk}/buy/", {"shares": "40", "confirm": "1"})
        contract, _r = sign_pending(buyer, self.inv2)
        self.assertEqual((contract.kind, contract.status), ("share_transfer", "signed"))
        self.assertEqual(contract.parent, offer_contract)
        roles = dict(contract.signatures.values_list("role", "user"))
        self.assertEqual(roles, {"seller": self.inv.pk, "buyer": self.inv2.pk})
        self.assertEqual(Holding.objects.get(user=self.inv2, project=p).shares, 40)
        self.assertEqual(contract.seal_hash, contract.compute_seal())

    def test_code_is_not_shown_once_whatsapp_is_active(self):
        from apps.sms.models import SMSProvider

        p = self.launch(kind="deal", model="moucharaka", target=300_000)
        SMSProvider.objects.create(name="Meta", backend="console", channel="whatsapp", is_active=True)
        contract = self.start_deal_investment(p)
        page = self.c.get(f"/fr/contracts/{contract.reference}/sign/").content.decode()
        self.assertNotIn("Mode développement", page)
        self.assertIn("Nous avons envoyé un code", page)
