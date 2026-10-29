import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.accounts.models import KYCProfile, PhoneOTP, User
from apps.accounts.otp import OTPError, issue_otp, verify_otp
from apps.accounts.services import approve_kyc
from apps.core.factories import image_file, make_project, make_user
from apps.core.models import Moughataa
from apps.sms.backends import ConsoleBackend
from apps.sms.models import SMSMessage, SMSProvider
from apps.sms.service import send_sms
from apps.wallet.models import DepositRequest, Wallet


def last_code():
    phone, body = ConsoleBackend.outbox[-1]
    return "".join(c for c in body.split(":")[1] if c.isdigit())[:6] if ":" in body else ""


class OTPTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_issue_and_verify(self):
        code = issue_otp("22123456", "register")
        with self.assertRaises(OTPError):
            verify_otp("22123456", "register", "000000" if code != "000000" else "111111")
        self.assertTrue(verify_otp("22123456", "register", code))
        with self.assertRaises(OTPError):  # single use
            verify_otp("22123456", "register", code)
        # SMS log never stores the code
        self.assertNotIn(code, SMSMessage.objects.latest("created_at").body)

    def test_attempts_and_throttle(self):
        issue_otp("22123457", "register")
        for _i in range(5):
            with self.assertRaises(OTPError):
                verify_otp("22123457", "register", "999999x")
        self.assertFalse(PhoneOTP.objects.filter(phone="22123457").first().is_valid)
        for _i in range(5):
            issue_otp("22123458", "login")
        with self.assertRaises(OTPError):
            issue_otp("22123458", "login")


class SMSFailoverTests(TestCase):
    def test_failover_to_next_provider(self):
        SMSProvider.objects.create(name="Broken", backend="http", priority=1, config={})  # no url → fails
        SMSProvider.objects.create(name="Console", backend="console", priority=2)
        self.assertTrue(send_sms("32000000", "hello", purpose="test"))
        statuses = list(SMSMessage.objects.order_by("id").values_list("status", "backend"))
        self.assertEqual(statuses, [("failed", "http"), ("sent", "console")])

    def test_prefix_routing(self):
        SMSProvider.objects.create(name="Mattel only", backend="console", priority=1, prefixes="3")
        SMSProvider.objects.create(name="Fallback", backend="console", priority=5)
        send_sms("22000000", "x")
        self.assertEqual(SMSMessage.objects.latest("id").provider.name, "Fallback")
        send_sms("33000000", "x")
        self.assertEqual(SMSMessage.objects.latest("id").provider.name, "Mattel only")


@override_settings(DEBUG=True, SMS_FALLBACK_BACKEND="console")
class RegistrationFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_register_kyc_approve(self):
        c = self.client
        r = c.post("/fr/accounts/register/", {"phone": "+222 46 12 34 56", "accept_terms": "on"})
        self.assertRedirects(r, "/fr/accounts/verify/")
        code = next(o.code_hash for o in PhoneOTP.objects.all()) and last_code()
        r = c.post("/fr/accounts/verify/", {"code": code})
        self.assertRedirects(r, "/fr/accounts/register/finish/")
        r = c.post("/fr/accounts/register/finish/", {"full_name": "Ahmed Salem", "email": "", "preferred_language": "ar",
                                                     "password1": "Tres-Sur#2026", "password2": "Tres-Sur#2026"})
        self.assertRedirects(r, "/fr/accounts/identity/")
        user = User.objects.get(phone="46123456")
        self.assertEqual(user.status, "new")
        # Investing is blocked before approval
        r = c.get("/fr/wallet/")
        self.assertEqual(r.status_code, 302)
        m = Moughataa.objects.filter(wilaya__code="NKO").first()
        img = lambda n: SimpleUploadedFile(n, image_file(n).read(), content_type="image/jpeg")  # noqa: E731
        r = c.post("/fr/accounts/identity/", {
            "full_name_fr": "Ahmed Salem", "full_name_ar": "أحمد سالم", "nni": "1234567890", "id_type": "cni",
            "id_number": "1234567890", "id_issue_date": "2022-01-10", "id_expiry_date": "2032-01-10",
            "date_of_birth": "1990-05-05", "place_of_birth": "Atar", "gender": "m", "nationality": "Mauritanienne",
            "wilaya": m.wilaya_id, "moughataa": m.pk, "address": "Ilot C", "profession": "Enseignant",
            "monthly_income": "20-50k", "source_of_funds": "salary", "experience": "none", "purpose": "invest",
            "id_front": img("f.jpg"), "selfie": img("s.jpg"), "confirm_truth": "on"})
        self.assertRedirects(r, "/fr/accounts/identity/status/")
        user.refresh_from_db()
        self.assertEqual(user.status, "pending")
        # Documents are private
        other = make_user("Other")
        c2 = self.client_class()
        c2.force_login(other)
        self.assertEqual(c2.get(f"/fr/accounts/identity/document/{user.pk}/id_front/").status_code, 404)
        self.assertEqual(c.get(f"/fr/accounts/identity/document/{user.pk}/id_front/").status_code, 200)
        approve_kyc(user.kyc, make_user("Staff", staff=True))
        user.refresh_from_db()
        self.assertTrue(user.is_approved)
        self.assertEqual(c.get("/fr/wallet/").status_code, 200)

    def test_underage_rejected(self):
        u = make_user("Young", approved=False)
        self.client.force_login(u)
        m = Moughataa.objects.first()
        r = self.client.post("/fr/accounts/identity/", {"date_of_birth": date.today().replace(year=date.today().year - 16),
                                                         "wilaya": m.wilaya_id, "moughataa": m.pk})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(KYCProfile.objects.filter(user=u).exists())


class APITests(TestCase):
    def setUp(self):
        cache.clear()

    def test_api_register_and_invest(self):
        c = self.client
        r = c.post("/api/v1/auth/otp/request", {"phone": "36000001", "purpose": "register"}, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        r = c.post("/api/v1/auth/otp/verify", {"phone": "36000001", "purpose": "register", "code": last_code()},
                   content_type="application/json")
        ver = r.json()["verification"]
        r = c.post("/api/v1/auth/register", {"verification": ver, "full_name": "Api User", "password": "Api-User#2026"},
                   content_type="application/json")
        self.assertEqual(r.status_code, 201)
        token = r.json()["token"]
        auth = {"HTTP_AUTHORIZATION": f"Token {token}"}
        self.assertEqual(c.get("/api/v1/wallet", **auth).status_code, 403)  # not approved yet
        # Approve, fund and invest
        user = User.objects.get(phone="36000001")
        staff = make_user("Staff", staff=True)
        owner = make_user("Owner", balance=10_000)
        from apps.projects.services import approve_project, submit_project
        from apps.wallet.services import adjust

        p = make_project(owner)
        submit_project(p, owner)
        p.refresh_from_db()
        approve_project(p, staff, "B")
        user.status = "approved"
        user.save()
        adjust(user, Decimal("50000"))
        r = c.get("/api/v1/projects?kind=boutique")
        self.assertEqual(r.json()["count"], 1)
        r = c.get(f"/api/v1/projects/{p.slug}")
        self.assertIn("scenarios", r.json()["model"])
        r = c.post(f"/api/v1/projects/{p.slug}/invest", {"shares": 10, "risk_acknowledged": True},
                   content_type="application/json", **auth)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Wallet.for_user(user).held, Decimal("10000"))
        self.assertEqual(c.get("/api/v1/portfolio", **auth).status_code, 200)
        self.assertEqual(c.get(f"/api/v1/users/{owner.public_id}").status_code, 200)


@override_settings(PAYMENT_WEBHOOK_SECRET="s3cret")
class WebhookTests(TestCase):
    def test_signed_webhook_confirms_deposit(self):
        u = make_user("Payer")
        dep = DepositRequest.objects.create(user=u, amount=Decimal("5000"), method="bankily")
        body = json.dumps({"reference": dep.reference, "amount": 5000, "transaction_id": "BK123", "status": "success"}).encode()
        r = self.client.post("/wallet/webhook/bankily/", body, content_type="application/json", HTTP_X_SIGNATURE="bad")
        self.assertEqual(r.status_code, 403)
        sig = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        r = self.client.post("/wallet/webhook/bankily/", body, content_type="application/json", HTTP_X_SIGNATURE=sig)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Wallet.for_user(u).balance, Decimal("5000"))
        # Replay is idempotent
        self.client.post("/wallet/webhook/bankily/", body, content_type="application/json", HTTP_X_SIGNATURE=sig)
        self.assertEqual(Wallet.for_user(u).balance, Decimal("5000"))


class PagesRenderTests(TestCase):
    """Every main page renders in both languages for each role."""

    def test_pages(self):
        owner = make_user("Owner", balance=10_000)
        staff = make_user("Staff", staff=True)
        staff.is_superuser = True
        staff.save()
        inv = make_user("Investor", balance=100_000)
        from apps.investments.services import invest
        from apps.projects.services import approve_project, submit_project

        p = make_project(owner)
        submit_project(p, owner)
        p.refresh_from_db()
        approve_project(p, staff, "B")
        invest(inv, p, 5, True)
        for user, urls in [
            (None, ["/", "/projects/", "/market/", p.get_absolute_url(), "/p/how/", "/p/fees/", "/p/sharia/", "/p/faq/",
                    "/trust-score/", f"/u/{owner.public_id}/", "/accounts/login/", "/accounts/register/"]),
            (inv, ["/dashboard/", "/portfolio/", "/wallet/", "/wallet/deposit/", "/wallet/withdraw/", "/projects/new/",
                   p.get_absolute_url(), "/notifications/", "/accounts/settings/"]),
            (owner, [f"/projects/{p.slug}/manage/"]),
            (staff, ["/staff/", "/staff/kyc/", "/staff/projects/", f"/staff/projects/{p.pk}/", "/staff/deposits/",
                     "/admin/", "/admin/core/platformsettings/"]),
        ]:
            c = self.client_class()
            if user:
                c.force_login(user)
            for prefix in ("", "/fr"):
                for u in urls:
                    r = c.get(prefix + u)
                    self.assertEqual(r.status_code, 200, f"{prefix}{u} → {r.status_code}")
        r = self.client.get("/")
        self.assertContains(r, 'dir="rtl"')
        self.assertContains(r, "استثمر في متاجر حيّك")
        r = self.client.get("/fr/")
        self.assertContains(r, 'dir="ltr"')
        self.assertContains(r, "Investissez dans les boutiques de votre quartier")
        self.assertNotContains(r, "استثمر في متاجر حيّك")


class NotificationLanguageTests(TestCase):
    def test_body_rendered_in_recipient_language(self):
        from django.utils import translation

        from apps.core.utils import N_, notify

        fr_user = make_user("Fr User", lang="fr")
        ar_user = make_user("Ar User", lang="ar")
        with translation.override("ar"):
            n1 = notify(fr_user, N_("Dépôt confirmé"), N_("%(a)s MRU ont été ajoutés à votre portefeuille.") % {"a": "500"})
        with translation.override("fr"):
            n2 = notify(ar_user, N_("Dépôt confirmé"), N_("%(a)s MRU ont été ajoutés à votre portefeuille.") % {"a": "500"})
        self.assertEqual(n1.title, "Dépôt confirmé")
        self.assertEqual(n1.body, "500 MRU ont été ajoutés à votre portefeuille.")
        self.assertEqual(n2.title, "تم تأكيد الإيداع")
        self.assertIn("500", n2.body)
        self.assertIn("محفظتك", n2.body)
