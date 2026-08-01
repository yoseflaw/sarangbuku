import hashlib
from smtplib import SMTPException
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import Invitation, SwapZone
from accounts.services import generate_invitation_code


class InvitationCodeTests(SimpleTestCase):
    def test_generated_code_has_256_bits_and_matching_digest(self):
        code, digest = generate_invitation_code()

        self.assertGreaterEqual(len(code), 43)
        self.assertEqual(digest, hashlib.sha256(code.encode()).hexdigest())
        self.assertNotEqual(code, digest)


class InvitationModelTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="test-password",
            display_name="Admin",
        )

    def test_max_uses_must_be_positive(self):
        invitation = Invitation(
            code_digest="a" * 64,
            max_uses=0,
            created_by=self.staff,
        )

        with self.assertRaises(ValidationError):
            invitation.full_clean()

    def test_use_count_cannot_exceed_max_uses(self):
        invitation = Invitation.objects.create(
            code_digest="b" * 64,
            max_uses=1,
            created_by=self.staff,
        )
        invitation.use_count = 2

        with self.assertRaises(ValidationError):
            invitation.full_clean()

    def test_code_digest_is_unique(self):
        Invitation.objects.create(
            code_digest="c" * 64,
            created_by=self.staff,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Invitation.objects.create(
                code_digest="c" * 64,
                created_by=self.staff,
            )

    def test_string_does_not_reveal_usable_code(self):
        code, digest = generate_invitation_code()
        invitation = Invitation.objects.create(
            code_digest=digest,
            created_by=self.staff,
        )

        self.assertNotIn(code, str(invitation))
        self.assertNotIn(digest, str(invitation))

    def test_user_can_select_multiple_swap_zones(self):
        user = get_user_model().objects.create_user(
            email="member@example.com",
            password="test-password",
            display_name="Anggota",
        )
        zones = [
            SwapZone.objects.create(name="Blok M", description="Lobi"),
            SwapZone.objects.create(name="Gambir", description="Pintu utama"),
        ]

        user.swap_zones.set(zones)

        self.assertCountEqual(user.swap_zones.all(), zones)


class InvitationAdminTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="test-password",
            display_name="Admin",
        )
        self.client.force_login(self.staff)

    def test_admin_emails_code_but_persists_only_digest(self):
        response = self.client.post(
            reverse("admin:accounts_invitation_add"),
            {
                "recipient_email": "reader@example.com",
                "max_uses": 1,
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        invitation = Invitation.objects.get()
        self.assertEqual(invitation.created_by, self.staff)
        self.assertEqual(len(mail.outbox), 1)
        code = mail.outbox[0].body.split("Kode undanganmu: ", 1)[1].splitlines()[0]
        self.assertEqual(
            hashlib.sha256(code.encode()).hexdigest(),
            invitation.code_digest,
        )
        self.assertNotIn(code, str(invitation.__dict__))

    @patch("accounts.admin.send_mail", side_effect=SMTPException("offline"))
    def test_email_failure_rolls_back_invitation(self, _send_mail):
        with self.assertRaises(SMTPException):
            self.client.post(
                reverse("admin:accounts_invitation_add"),
                {
                    "recipient_email": "reader@example.com",
                    "max_uses": 1,
                    "is_active": "on",
                },
            )

        self.assertFalse(Invitation.objects.exists())
