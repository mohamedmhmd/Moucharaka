from django.test import TestCase
class ContactPageTests(TestCase):
    def test_contact_page_and_footer_show_the_email(self):
        page = self.client.get("/fr/p/contact/").content.decode()
        self.assertIn('href="mailto:moucharaka.mr@gmail.com"', page)
        self.assertIn("/fr/p/contact/", self.client.get("/fr/").content.decode())

    def test_email_can_be_changed_in_settings(self):
        from apps.core.models import PlatformSettings

        s = PlatformSettings.get()
        s.contact_email = "aide@mou-charaka.com"
        s.save()
        self.assertIn("aide@mou-charaka.com", self.client.get("/p/contact/").content.decode())
