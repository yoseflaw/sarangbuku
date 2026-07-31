from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase


class UserModelTests(SimpleTestCase):
    def test_user_uses_email_instead_of_username(self):
        user_model = get_user_model()

        self.assertEqual(user_model.USERNAME_FIELD, "email")
        self.assertNotIn("username", [field.name for field in user_model._meta.fields])


class UserManagerTests(TestCase):
    def test_create_user_normalizes_email(self):
        try:
            user = get_user_model().objects.create_user(
                email="MEMBER@EXAMPLE.COM",
                password="test-password",
                display_name="Anggota",
            )
        except TypeError as error:
            self.fail(f"Email-only user creation is unavailable: {error}")

        self.assertEqual(user.email, "member@example.com")
        self.assertTrue(user.check_password("test-password"))

    def test_create_user_cannot_grant_staff_privileges(self):
        user = get_user_model().objects.create_user(
            email="member@example.com",
            password="test-password",
            display_name="Anggota",
            is_staff=True,
            is_superuser=True,
        )

        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_requires_email(self):
        try:
            with self.assertRaises(ValueError):
                get_user_model().objects.create_user(
                    email="",
                    password="test-password",
                    display_name="Anggota",
                )
        except TypeError as error:
            self.fail(f"Email-only user creation is unavailable: {error}")

    def test_create_superuser_sets_required_flags(self):
        try:
            user = get_user_model().objects.create_superuser(
                email="admin@example.com",
                password="test-password",
                display_name="Admin",
            )
        except TypeError as error:
            self.fail(f"Email-only superuser creation is unavailable: {error}")

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_create_superuser_rejects_missing_flags(self):
        try:
            with self.assertRaises(ValueError):
                get_user_model().objects.create_superuser(
                    email="admin@example.com",
                    password="test-password",
                    display_name="Admin",
                    is_staff=False,
                )
        except TypeError as error:
            self.fail(f"Email-only superuser creation is unavailable: {error}")

    def test_email_login_lookup_ignores_case(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            email="member@example.com",
            password="test-password",
            display_name="Anggota",
        )

        try:
            found = user_model.objects.get_by_natural_key("MEMBER@EXAMPLE.COM")
        except user_model.DoesNotExist:
            self.fail("Email login lookup is case-sensitive.")

        self.assertEqual(found, user)

    def test_email_is_unique_ignoring_case(self):
        user_model = get_user_model()
        first = {"email": "Member@example.com"}
        second = {"email": "member@example.com"}
        if any(field.name == "username" for field in user_model._meta.fields):
            first["username"] = "first"
            second["username"] = "second"

        user_model.objects.create(**first)

        with self.assertRaises(IntegrityError), transaction.atomic():
            user_model.objects.create(**second)
