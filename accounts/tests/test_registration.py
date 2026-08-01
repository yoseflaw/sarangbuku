from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.forms import RegistrationForm
from accounts.models import Invitation
from accounts.services import (
    DuplicateEmail,
    InvalidInvitation,
    generate_invitation_code,
    redeem_invitation,
)


class InvitationRedemptionTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="test-password",
            display_name="Admin",
        )
        self.code, digest = generate_invitation_code()
        self.invitation = Invitation.objects.create(
            code_digest=digest,
            created_by=self.staff,
        )

    def redeem(self, **overrides):
        values = {
            "code": self.code,
            "email": "member@example.com",
            "display_name": "Nadia",
            "password": "safe-test-password",
        }
        values.update(overrides)
        return redeem_invitation(**values)

    def assert_rejected_without_changes(self, **overrides):
        expected_use_count = self.invitation.use_count
        with self.assertRaises(InvalidInvitation):
            self.redeem(**overrides)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.use_count, expected_use_count)
        self.assertFalse(
            get_user_model().objects.filter(email="member@example.com").exists()
        )

    def test_valid_code_creates_user_and_consumes_once(self):
        user = self.redeem(email="MEMBER@EXAMPLE.COM")

        self.invitation.refresh_from_db()
        self.assertEqual(user.email, "member@example.com")
        self.assertTrue(user.check_password("safe-test-password"))
        self.assertEqual(self.invitation.use_count, 1)

    def test_unknown_code_is_rejected(self):
        self.assert_rejected_without_changes(code="not-a-real-code")

    def test_disabled_invitation_is_rejected(self):
        self.invitation.is_active = False
        self.invitation.save(update_fields=["is_active"])

        self.assert_rejected_without_changes()

    def test_expired_invitation_is_rejected(self):
        self.invitation.expires_at = timezone.now() - timedelta(seconds=1)
        self.invitation.save(update_fields=["expires_at"])

        self.assert_rejected_without_changes()

    def test_exhausted_invitation_is_rejected(self):
        self.invitation.use_count = self.invitation.max_uses
        self.invitation.save(update_fields=["use_count"])

        self.assert_rejected_without_changes()

    def test_failure_after_user_creation_rolls_back_everything(self):
        with patch.object(
            Invitation,
            "save",
            side_effect=RuntimeError("database failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.redeem()

        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.use_count, 0)
        self.assertFalse(
            get_user_model().objects.filter(email="member@example.com").exists()
        )

    def test_duplicate_email_does_not_consume_invitation(self):
        get_user_model().objects.create_user(
            email="member@example.com",
            password="test-password",
            display_name="Sudah Ada",
        )

        with self.assertRaises(DuplicateEmail):
            self.redeem(email="MEMBER@EXAMPLE.COM")

        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.use_count, 0)


class RegistrationViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="test-password",
            display_name="Admin",
        )
        self.code, digest = generate_invitation_code()
        self.invitation = Invitation.objects.create(
            code_digest=digest,
            created_by=self.staff,
        )

    def registration_data(self, **overrides):
        values = {
            "invitation_code": self.code,
            "email": "member@example.com",
            "display_name": "Nadia",
            "password1": "safe-test-password",
            "password2": "safe-test-password",
        }
        values.update(overrides)
        return values

    def test_valid_registration_signs_in_and_redirects_to_profile(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(),
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user = get_user_model().objects.get(email="member@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertFalse(user.swap_zones.exists())
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.use_count, 1)

    def test_invalid_invitation_uses_generic_error_and_preserves_safe_values(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(
                invitation_code="unknown-code",
                email="NADIA@EXAMPLE.COM",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Kode undangan ini tidak dapat digunakan. "
            "Periksa kembali kodenya atau hubungi pengelola Sarang Buku.",
        )
        self.assertContains(response, "NADIA@EXAMPLE.COM")
        self.assertContains(response, "Nadia")
        self.assertNotContains(response, "safe-test-password")
        self.assertFalse(
            get_user_model().objects.filter(email="nadia@example.com").exists()
        )

    def test_duplicate_email_has_field_error_without_consuming_invitation(self):
        get_user_model().objects.create_user(
            email="member@example.com",
            password="test-password",
            display_name="Sudah Ada",
        )

        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(email="MEMBER@EXAMPLE.COM"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email ini sudah terdaftar.")
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.use_count, 0)

    def test_password_validation_does_not_create_user_or_consume_invitation(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(password1="123", password2="123"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(
            get_user_model().objects.filter(email="member@example.com").exists()
        )
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.use_count, 0)

    def test_registration_form_rejects_non_atomic_save(self):
        form = RegistrationForm(data=self.registration_data())
        self.assertTrue(form.is_valid(), form.errors)

        with self.assertRaises(ValueError):
            form.save(commit=False)

    def test_authenticated_user_is_redirected_to_profile(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("accounts:register"))

        self.assertRedirects(response, reverse("accounts:profile"))


class ConcurrentRedemptionTests(TransactionTestCase):
    def setUp(self):
        staff = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="test-password",
            display_name="Admin",
        )
        self.code, digest = generate_invitation_code()
        self.invitation = Invitation.objects.create(
            code_digest=digest,
            created_by=staff,
            max_uses=1,
        )

    def redeem(self, barrier, email):
        close_old_connections()
        barrier.wait()
        try:
            redeem_invitation(
                code=self.code,
                email=email,
                display_name=email,
                password="safe-test-password",
            )
            return "created"
        except InvalidInvitation:
            return "rejected"
        finally:
            close_old_connections()

    def test_max_uses_cannot_be_exceeded(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda email: self.redeem(barrier, email),
                    ["one@example.com", "two@example.com"],
                )
            )

        self.assertCountEqual(results, ["created", "rejected"])
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.use_count, 1)
        self.assertEqual(
            get_user_model().objects.filter(is_superuser=False).count(),
            1,
        )
