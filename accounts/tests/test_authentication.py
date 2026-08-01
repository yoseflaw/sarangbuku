import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="member@example.com",
            password="safe-test-password",
            display_name="Nadia",
        )

    def test_email_login_ignores_case_and_redirects_to_profile(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "MEMBER@EXAMPLE.COM", "password": "safe-test-password"},
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_wrong_credentials_do_not_sign_in(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.user.email, "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_sign_in(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.user.email, "password": "safe-test-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.assertEqual(
            self.client.get(reverse("accounts:logout")).status_code,
            405,
        )

    def test_post_logout_clears_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("landing"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signed_out_navigation_shows_account_entry_points(self):
        response = self.client.get(reverse("landing"))

        self.assertContains(response, "Masuk")
        self.assertContains(response, "Daftar dengan undangan")
        self.assertNotContains(response, "Profil")
        self.assertNotContains(response, "Keluar")

    def test_signed_in_navigation_has_profile_and_post_logout(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("landing"))

        self.assertContains(response, "Profil")
        self.assertContains(response, "Keluar")
        self.assertContains(response, 'method="post"')
        self.assertContains(response, 'action="/akun/keluar/"')
        self.assertNotContains(response, "Daftar dengan undangan")


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="member@example.com",
            password="old-safe-password",
            display_name="Nadia",
        )

    def request_reset(self):
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": self.user.email},
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r"http://testserver(?P<path>/\S+)", mail.outbox[0].body)
        self.assertIsNotNone(match)
        return match.group("path")

    def test_active_user_can_reset_password_once(self):
        reset_path = self.request_reset()
        token_response = self.client.get(reset_path)
        self.assertEqual(token_response.status_code, 302)
        cleaned_path = token_response.url

        response = self.client.post(
            cleaned_path,
            {
                "new_password1": "new-safe-password",
                "new_password2": "new-safe-password",
            },
        )

        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("old-safe-password"))
        self.assertTrue(self.user.check_password("new-safe-password"))

        reused = self.client.get(cleaned_path)
        self.assertEqual(reused.status_code, 200)
        self.assertFalse(reused.context["validlink"])

    def test_reset_response_does_not_reveal_account_existence(self):
        known = self.client.post(
            reverse("accounts:password_reset"),
            {"email": self.user.email},
        )
        unknown = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "unknown@example.com"},
        )

        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)
        self.assertEqual(len(mail.outbox), 1)

    def test_inactive_account_receives_no_reset_email(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)
