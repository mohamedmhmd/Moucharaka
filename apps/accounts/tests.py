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
        SMSProvider.objects.create(name="Mattel only", backend="console", priority=1, prefixes="2223")
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
        user = User.objects.get(phone="+22246123456")
        self.assertEqual(user.status, "new")
        # Investing is blocked before approval
        r = c.get("/fr/wallet/")
        self.assertEqual(r.status_code, 302)
        m = Moughataa.objects.filter(wilaya__code="NKO").first()
        img = lambda n: SimpleUploadedFile(n, image_file(n).read(), content_type="image/jpeg")  # noqa: E731
        r = c.post("/fr/accounts/identity/", {
            "full_name": "Ahmed Salem", "nni": "1234567890", "id_type": "cni",
            "date_of_birth": "1990-05-05", "place_of_birth": "Atar", "gender": "m", "nationality": "Mauritanienne",
            "wilaya": m.wilaya_id, "moughataa": m.pk, "address": "Ilot C", "profession": "Enseignant",
            "monthly_income": "20-50k", "source_of_funds": "salary", "experience": "none", "purpose": "invest",
            "id_front": img("f.jpg"), "confirm_truth": "on"})
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
        user = User.objects.get(phone="+22236000001")
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
        from django.utils import translation

        translation.activate("ar")  # other tests leave "fr" active in this thread
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
        from apps.wallet.models import PaymentAccount

        PaymentAccount.objects.create(user=inv, method="bankily", number="+22236000099", holder_name="Investor",
                                      is_default=True)
        for user, urls in [
            (None, ["/", "/projects/", "/market/", p.get_absolute_url(), "/p/how/", "/p/fees/", "/p/sharia/", "/p/faq/",
                    "/trust-score/", f"/u/{owner.public_id}/", "/accounts/login/", "/accounts/register/"]),
            (inv, ["/dashboard/", "/portfolio/", "/wallet/", "/wallet/deposit/", "/wallet/withdraw/", "/wallet/accounts/", "/wallet/accounts/add/", "/projects/new/",
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
        self.assertContains(r, "استثمر في المشاريع والمؤسسات")
        r = self.client.get("/fr/")
        self.assertContains(r, 'dir="ltr"')
        self.assertContains(r, "Investissez dans des projets et des entreprises")
        self.assertNotContains(r, "استثمر في المشاريع والمؤسسات")


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


class InternationalPhoneTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_normalization_and_allowlist(self):
        from django.core.exceptions import ValidationError

        from apps.accounts.phones import normalize_phone, validate_phone

        for raw in ("22 12 34 56", "+222 22123456", "0022222123456"):
            self.assertEqual(normalize_phone(raw), "+22222123456")
        self.assertEqual(normalize_phone("+33 6 12 34 56 78"), "+33612345678")
        self.assertEqual(normalize_phone("0033612345678"), "+33612345678")
        validate_phone("+33612345678")
        validate_phone("+79123456789")           # worldwide by default (WhatsApp)
        with self.assertRaises(ValidationError):
            validate_phone("612345678")          # French number typed without +33 → read as Mauritanian, invalid
        with self.settings(PHONE_ALLOWED_COUNTRIES=["MR", "FR"]):
            with self.assertRaises(ValidationError):
                validate_phone("+79123456789")

    def test_diaspora_registration_and_routing(self):
        SMSProvider.objects.create(name="Local MR", backend="console", priority=1, prefixes="222")
        SMSProvider.objects.create(name="International", backend="console", priority=2)
        r = self.client.post("/fr/accounts/register/", {"phone": "+33 6 12 34 56 78", "accept_terms": "on"})
        self.assertRedirects(r, "/fr/accounts/verify/")
        self.assertEqual(SMSMessage.objects.latest("id").provider.name, "International")
        self.assertEqual(SMSMessage.objects.latest("id").phone, "+33612345678")
        self.client.post("/fr/accounts/verify/", {"code": last_code()})
        self.client.post("/fr/accounts/register/finish/", {"full_name": "Sidi Paris", "preferred_language": "fr",
                                                           "password1": "Tres-Sur#2026", "password2": "Tres-Sur#2026"})
        self.assertTrue(User.objects.filter(phone="+33612345678").exists())
        send_sms("+22222123456", "x")
        self.assertEqual(SMSMessage.objects.latest("id").provider.name, "Local MR")
        with self.settings(PHONE_ALLOWED_COUNTRIES=["MR", "FR"]):
            r = self.client_class().post("/fr/accounts/register/", {"phone": "+7 912 345 67 89", "accept_terms": "on"})
        self.assertContains(r, "pas encore ouverte")


class WhatsAppTests(TestCase):
    """Payloads sent to Meta and Twilio, channel order and opt-out."""

    def setUp(self):
        cache.clear()

    def _fake(self, captured, json_resp):
        from unittest import mock

        def post(url, **kw):
            captured.append((url, kw))
            r = mock.Mock(status_code=200, text="ok", content=b"{}")
            r.json.return_value = json_resp
            return r
        return mock.patch("apps.sms.backends.requests.post", side_effect=post)

    def test_meta_cloud_authentication_template(self):
        SMSProvider.objects.create(name="Meta", backend="whatsapp_cloud", priority=1, config={
            "phone_number_id": "111", "access_token": "TOKEN", "otp_template": "moucharaka_code",
            "notification_template": "moucharaka_update"})
        captured = []
        with self._fake(captured, {"messages": [{"id": "wamid.1"}]}):
            from django.utils import translation

            with translation.override("ar"):
                code = issue_otp("+33612345678", "register")
        url, kw = captured[0]
        self.assertEqual(url, "https://graph.facebook.com/v21.0/111/messages")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer TOKEN")
        body = kw["json"]
        self.assertEqual(body["to"], "33612345678")
        self.assertEqual(body["template"]["name"], "moucharaka_code")
        self.assertEqual(body["template"]["language"]["code"], "ar")
        self.assertEqual(body["template"]["components"][0]["parameters"][0]["text"], code)
        self.assertEqual(body["template"]["components"][1]["sub_type"], "url")  # copy-code button
        msg = SMSMessage.objects.latest("id")
        self.assertEqual((msg.channel, msg.status, msg.provider_message_id), ("whatsapp", "sent", "wamid.1"))
        self.assertNotIn(code, msg.body)

    def test_twilio_whatsapp_and_notification(self):
        SMSProvider.objects.create(name="Twilio WA", backend="twilio_whatsapp", priority=1, config={
            "account_sid": "AC1", "auth_token": "t", "from": "+14155238886",
            "otp_content_sid": {"fr": "HXfr", "ar": "HXar"}, "notification_content_sid": "HXnotif"})
        captured = []
        with self._fake(captured, {"sid": "SM1"}):
            from django.utils import translation

            with translation.override("fr"):
                code = issue_otp("+22222123456", "login")
            user = make_user("Notif User", lang="ar")
            from apps.core.utils import N_, notify

            captured.clear()
            notify(user, N_("Dépôt confirmé"), "500 MRU", whatsapp=True)
            user.whatsapp_notifications = False
            notify(user, N_("Dépôt confirmé"), "500 MRU", whatsapp=True)
        self.assertEqual(len(captured), 1)  # opt-out respected
        data = captured[0][1]["data"]
        self.assertEqual(data["ContentSid"], "HXnotif")
        self.assertEqual(data["To"], "whatsapp:" + user.phone)
        self.assertEqual(json.loads(data["ContentVariables"])["1"], "تم تأكيد الإيداع")
        self.assertTrue(code)

    def test_sms_fallback_when_whatsapp_fails(self):
        SMSProvider.objects.create(name="Meta broken", backend="whatsapp_cloud", priority=1, config={})
        SMSProvider.objects.create(name="SMS backup", backend="console", channel="sms", priority=2)
        issue_otp("+22222123456", "register")
        rows = list(SMSMessage.objects.order_by("id").values_list("channel", "status"))
        self.assertEqual(rows, [("whatsapp", "failed"), ("sms", "sent")])
        with self.settings(OTP_CHANNELS=["whatsapp"]):
            cache.clear()
            with self.assertRaises(OTPError):
                issue_otp("+22222123457", "register")


class AdminCreatedUserLoginTests(TestCase):
    """A staff account added in the admin with a number typed with spaces can log in."""

    def setUp(self):
        cache.clear()
        from django.utils import translation
        translation.activate("ar")
        self.admin = User.objects.create_superuser(phone="+22220000000", password="Admin#2026x", full_name="Admin")

    def test_admin_add_user_then_login(self):
        self.client.force_login(self.admin)
        r = self.client.post("/fr/admin/accounts/user/add/", {
            "phone": "36 12 34 56", "full_name": "Agent Conformité",
            "password1": "Staff#2026long", "password2": "Staff#2026long", "_save": "1"})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].form.errors)
        self.assertTrue(User.objects.filter(phone="+22236123456").exists())
        # duplicate in another format is refused
        r = self.client.post("/fr/admin/accounts/user/add/", {
            "phone": "+222 36123456", "full_name": "Doublon",
            "password1": "Staff#2026long", "password2": "Staff#2026long", "_save": "1"})
        self.assertEqual(r.status_code, 200)
        self.client.logout()
        for typed in ("36123456", "36 12 34 56", "+22236123456", "0022236123456"):
            r = self.client.post("/fr/accounts/login/", {"phone": typed, "password": "Staff#2026long"})
            self.assertEqual(r.status_code, 302, typed)
            self.client.logout()

    def test_save_normalizes(self):
        u = make_user(phone="+22237000001")
        u.phone = "37 00 00 02"
        u.save()
        u.refresh_from_db()
        self.assertEqual(u.phone, "+22237000002")


class SimplifiedKYCTests(TestCase):
    """One name field (Arabic or Latin), ID as photo or PDF, no selfie, no proof of address."""

    def test_arabic_name_and_pdf_id(self):
        u = make_user("محمد", approved=False)
        self.client.force_login(u)
        page = self.client.get("/fr/accounts/identity/").content.decode()
        self.assertNotIn("capture=", page)            # gallery / files allowed, not camera only
        self.assertIn('accept="image/*,application/pdf"', page)
        for gone in ('name="selfie"', 'name="proof_of_address"', 'name="full_name_ar"', 'name="full_name_fr"'):
            self.assertNotIn(gone, page)
        m = Moughataa.objects.filter(wilaya__code="NKO").first()
        pdf = SimpleUploadedFile("cni.pdf", b"%PDF-1.4\n%test\n", content_type="application/pdf")
        r = self.client.post("/fr/accounts/identity/", {
            "full_name": "محمد ولد أحمد", "nni": "1234509876", "id_type": "cni",
            "date_of_birth": "1990-05-05", "place_of_birth": "Atar", "gender": "m", "nationality": "Mauritanienne",
            "wilaya": m.wilaya_id, "moughataa": m.pk, "address": "Ilot C", "profession": "Commerçant",
            "monthly_income": "20-50k", "source_of_funds": "salary", "experience": "none", "purpose": "raise",
            "id_front": pdf, "confirm_truth": "on"})
        self.assertRedirects(r, "/fr/accounts/identity/status/")
        self.assertEqual(KYCProfile.objects.get(user=u).full_name, "محمد ولد أحمد")
        for gone in ('name="id_number"', 'name="id_issue_date"', 'name="id_expiry_date"', 'name="id_back"'):
            self.assertNotIn(gone, page)
        # Staff see the PDF inside the review page: the document may be framed by the site itself
        staff = make_user("Staff PDF", staff=True)
        self.client.force_login(staff)
        kyc = KYCProfile.objects.get(user=u)
        review = self.client.get(f"/fr/staff/kyc/{kyc.pk}/").content.decode()
        self.assertIn("<iframe", review)
        doc = self.client.get(f"/fr/accounts/identity/document/{u.pk}/id_front/")
        self.assertEqual(doc["Content-Type"], "application/pdf")
        self.assertEqual(doc["X-Frame-Options"], "SAMEORIGIN")


class CodeOnScreenTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_code_shown_only_when_enabled(self):
        with self.settings(DEBUG=False, OTP_SHOW_ON_SCREEN=True):
            r = self.client.post("/fr/accounts/register/", {"phone": "+222 46 55 44 33", "accept_terms": "on"}, follow=True)
            self.assertContains(r, last_code())
        cache.clear()
        with self.settings(DEBUG=False, OTP_SHOW_ON_SCREEN=False):
            r = self.client.post("/fr/accounts/register/", {"phone": "+222 46 55 44 22", "accept_terms": "on"}, follow=True)
            self.assertNotContains(r, last_code())
