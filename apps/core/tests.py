from django.test import TestCase
class ContactPageTests(TestCase):
    def test_contact_page_and_footer_show_the_email(self):
        page = self.client.get("/fr/p/contact/").content.decode()
        self.assertIn('href="mailto:moucharaka.mr@gmail.com"', page)
        self.assertIn("/fr/p/contact/", self.client.get("/fr/").content.decode())

    def test_email_can_be_changed_in_settings(self):
        from apps.core.models import PlatformSettings

        from django.core.cache import cache

        self.addCleanup(cache.delete, "platform_settings")  # the database rolls back, the cache would not
        s = PlatformSettings.get()
        s.contact_email = "aide@mou-charaka.com"
        s.save()
        self.assertIn("aide@mou-charaka.com", self.client.get("/p/contact/").content.decode())


class BackupStatusTests(TestCase):
    def test_record_and_dashboard(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.accounts.models import User
        from apps.core.factories import make_user
        from apps.core.models import BackupRun, Notification

        owner = make_user("Owner Admin", staff=True)
        User.objects.filter(pk=owner.pk).update(is_superuser=True)
        self.client.force_login(owner)
        page = self.client.get("/fr/staff/").content.decode()
        self.assertIn("Aucune sauvegarde enregistrée", page)
        call_command("record_backup", "--status", "ok", "--stamp", "2026-11-07_0315", "--size", "2048000",
                     "--uploaded", stdout=StringIO())
        page = self.client.get("/fr/staff/").content.decode()
        self.assertIn("Dernière sauvegarde réussie", page)
        self.assertIn("copiée hors du serveur", page)
        self.assertFalse(Notification.objects.filter(user=owner, title="Sauvegarde : attention").exists())
        call_command("record_backup", "--status", "failed", "--message", "database dump failed", stdout=StringIO())
        self.assertEqual(BackupRun.objects.count(), 2)
        self.assertTrue(Notification.objects.filter(user=owner, title="Sauvegarde : attention").exists())
        self.assertIn("database dump failed", self.client.get("/fr/staff/").content.decode())


class BackupDailyCheckTests(TestCase):
    def test_daily_check_alerts_owners(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.accounts.models import User
        from apps.core.factories import make_user
        from apps.core.models import BackupRun, Notification
        from apps.projects.jobs import check_backups

        owner = make_user("Owner Admin", staff=True)
        User.objects.filter(pk=owner.pk).update(is_superuser=True)
        alerts = Notification.objects.filter(user=owner, title="Sauvegarde : attention")
        self.assertEqual(check_backups(), "not set up")  # nothing before the first backup
        BackupRun.objects.create(status="ok", stamp="a", uploaded=True)
        self.assertEqual(check_backups(), "ok")
        self.assertFalse(alerts.exists())
        BackupRun.objects.update(created_at=timezone.now() - timedelta(hours=40))
        self.assertIn("36 hours", check_backups())
        BackupRun.objects.create(status="failed", stamp="b", message="database dump failed")
        self.assertEqual(check_backups(), "database dump failed")
        self.assertEqual(alerts.count(), 2)


class LanguageSwitchTests(TestCase):
    def lang_of(self, response):
        import re
        return re.search(r'<html[^>]*lang="(\w+)"', response.content.decode()).group(1)

    def test_french_then_back_to_arabic(self):
        r = self.client.post("/i18n/setlang/", {"language": "fr", "next": "/projects/?q=x"})
        self.assertRedirects(r, "/fr/projects/?q=x", fetch_redirect_response=False)
        self.assertEqual(self.lang_of(self.client.get("/fr/")), "fr")
        r = self.client.post("/i18n/setlang/", {"language": "ar", "next": "/fr/projects/?q=x"})
        self.assertRedirects(r, "/projects/?q=x", fetch_redirect_response=False)
        self.assertEqual(self.client.cookies["django_language"].value, "ar")
        self.assertEqual(self.lang_of(self.client.get("/")), "ar")
        r = self.client.post("/i18n/setlang/", {"language": "ar", "next": "/fr/"})
        self.assertRedirects(r, "/", fetch_redirect_response=False)

    def test_outside_links_are_ignored(self):
        r = self.client.post("/i18n/setlang/", {"language": "fr", "next": "https://evil.example/x"})
        self.assertRedirects(r, "/fr/", fetch_redirect_response=False)


class NumberFormatTests(TestCase):
    def test_amounts_keep_their_order_in_arabic(self):
        from apps.core.templatetags.mk import money
        from apps.core.utils import fmt_amount
        self.assertEqual(fmt_amount(15000), "15 000")
        self.assertEqual(fmt_amount("1234567.5", 2), "1 234 567.50")
        self.assertEqual(money(15000), "15 000")
        self.assertNotIn(" ", fmt_amount(15000000))
