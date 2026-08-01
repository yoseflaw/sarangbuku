from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import SwapZone


class ProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="member@example.com",
            password="test-password",
            display_name="Anggota",
        )
        self.other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="test-password",
            display_name="Pengguna Lain",
        )
        self.zone_one = SwapZone.objects.create(
            name="Blok M",
            description="Bertemu di lobi.",
        )
        self.zone_two = SwapZone.objects.create(
            name="Gambir",
            description="Bertemu di pintu utama.",
        )
        self.inactive_zone = SwapZone.objects.create(
            name="Sarang Lama",
            description="Tidak lagi digunakan.",
            is_active=False,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("?next=/akun/profil/", response.url)

    def test_multiple_active_zones_can_be_selected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "display_name": "Nadia",
                "email": "member@example.com",
                "swap_zones": [self.zone_one.pk, self.zone_two.pk],
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertCountEqual(
            self.user.swap_zones.values_list("pk", flat=True),
            [self.zone_one.pk, self.zone_two.pk],
        )

    def test_zero_zones_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {"display_name": "Nadia", "email": "member@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pilih setidaknya satu Sarang.")

    def test_only_active_zones_are_offered_with_meeting_guidance(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, self.zone_one.name)
        self.assertContains(response, self.zone_one.description)
        self.assertNotContains(response, self.inactive_zone.name)

    def test_posted_inactive_zone_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "display_name": "Nadia",
                "email": "member@example.com",
                "swap_zones": [self.inactive_zone.pk],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pilih Sarang yang masih aktif.")
        self.assertFalse(self.user.swap_zones.exists())

    def test_existing_inactive_membership_is_retained(self):
        self.user.swap_zones.add(self.inactive_zone)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "display_name": "Nadia",
                "email": "member@example.com",
                "swap_zones": [self.zone_one.pk],
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertCountEqual(
            self.user.swap_zones.values_list("pk", flat=True),
            [self.inactive_zone.pk, self.zone_one.pk],
        )

    def test_email_update_is_normalized(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "display_name": "Nadia",
                "email": "NADIA@EXAMPLE.COM",
                "swap_zones": [self.zone_one.pk],
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "nadia@example.com")

    def test_duplicate_email_has_field_error(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "display_name": "Nadia",
                "email": "OTHER@EXAMPLE.COM",
                "swap_zones": [self.zone_one.pk],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email ini sudah digunakan.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "member@example.com")

    def test_profile_does_not_expose_another_users_email(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, self.user.email)
        self.assertNotContains(response, self.other_user.email)

    def test_add_book_control_is_disabled_and_has_no_book_link(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, "Tambahkan Buku")
        self.assertContains(response, "Belum tersedia")
        self.assertContains(response, "disabled")
        self.assertNotContains(response, "href=\"/buku")
