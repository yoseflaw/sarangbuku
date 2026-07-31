from django.test import SimpleTestCase


class LandingPageTests(SimpleTestCase):
    def test_landing_page_is_public(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "landing.html")
        self.assertContains(response, "Temukan bacaanmu berikutnya")
