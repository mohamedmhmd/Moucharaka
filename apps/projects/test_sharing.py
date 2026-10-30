from django.test import TestCase

from apps.core.factories import make_project, make_user
from apps.projects.models import Project, ProjectInterest
from apps.projects.services import approve_project, submit_project


class SharingTests(TestCase):
    def fr_url(self):
        from django.utils import translation

        with translation.override("fr"):
            return self.p.get_absolute_url()

    def setUp(self):
        from django.utils import translation

        translation.activate("ar")
        self.owner = make_user("Cheikh Ould Ahmed", balance=10_000)
        self.p = make_project(self.owner, title="Boutique Teyarett Lumière", neighborhood="Teyarett")

    def test_private_preview_short_link_and_interest(self):
        anon = self.client_class()
        self.assertEqual(anon.get(self.p.get_absolute_url()).status_code, 404)        # draft is private
        self.assertEqual(anon.get(self.p.get_share_path()).status_code, 404)          # public link without key
        # The owner's link carries the preview key
        owner = self.client_class()
        owner.force_login(self.owner)
        r = owner.get(self.fr_url())
        self.assertContains(r, f"?k={self.p.preview_token}")
        self.assertContains(r, "wa.me/?text=")
        self.assertContains(r, self.p.reference)
        # A friend opens it, then registers interest
        friend = make_user("Aminetou Diaspora", phone="+33611223344")
        c = self.client_class()
        c.force_login(friend)
        r = c.get(f"/fr/s/{self.p.reference}/?k={self.p.preview_token}")
        self.assertRedirects(r, self.fr_url())
        self.assertContains(c.get(self.fr_url()), "Je suis intéressé")
        c.post(f"/fr/projects/{self.p.slug}/interest/", {"amount": "20000"})
        it = ProjectInterest.objects.get(project=self.p, user=friend)
        self.assertEqual(int(it.amount), 20000)
        self.assertTrue(self.owner.notifications.filter(title__contains="intention").exists())
        self.assertEqual(Project.objects.get(pk=self.p.pk).shares_count, 1)
        # Opening the campaign notifies interested people
        submit_project(self.p, self.owner)
        self.p.refresh_from_db()
        approve_project(self.p, make_user("Staff", staff=True), "B")
        it.refresh_from_db()
        self.assertIsNotNone(it.notified_at)
        self.assertTrue(friend.notifications.filter(title__contains="collecte est ouverte").exists())
        # Now public: short link works for everyone, lowercase ID too
        self.assertEqual(anon.get(f"/s/{self.p.reference.lower()}/").status_code, 302)

    def test_qr_poster_and_search(self):
        Project.objects.filter(pk=self.p.pk).update(status="funding")
        r = self.client.get(f"/projects/{self.p.slug}/qr.svg")
        self.assertEqual(r["Content-Type"], "image/svg+xml")
        self.assertContains(r, "<svg")
        self.assertContains(self.client.get(f"/fr/projects/{self.p.slug}/poster/"), self.p.reference)
        # ID search jumps to the project, with or without "MP-"
        for q in (self.p.reference, self.p.reference[3:].lower(), f"mp {self.p.reference[3:]}"):
            r = self.client.get("/fr/search/", {"q": q})
            self.assertRedirects(r, self.fr_url())
        for q in ("Lumière", "teyarett", "Cheikh", self.owner.public_id):
            r = self.client.get("/fr/search/", {"q": q})
            self.assertContains(r, "Boutique Teyarett Lumière", msg_prefix=q)
        r = self.client.get("/fr/search/", {"q": "Cheikh"})
        self.assertContains(r, "Porteurs de projet")
        self.assertNotContains(self.client.get("/fr/search/", {"q": "zzzz"}), "Boutique Teyarett")
        r = self.client.get("/api/v1/projects", {"search": self.p.reference})
        self.assertEqual(r.json()["count"], 1)
        # Open Graph tags for WhatsApp link previews
        r = self.client.get(self.p.get_absolute_url())
        self.assertContains(r, 'property="og:title" content="Boutique Teyarett Lumière"')
        self.assertContains(r, 'property="og:image"')
