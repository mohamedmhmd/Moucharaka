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
