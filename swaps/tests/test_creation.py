from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import send_mail
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import SwapZone
from books.models import Book, BookCopy
from swaps.forms import MinatCreateForm
from swaps.models import Minat
from swaps.services import (
    DuplicatePendingMinat,
    MinatEligibilityError,
    _lock_copies,
    create_minat,
)


class MinatCreationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user(
            email="requester@example.com",
            password="safe-test-password",
            display_name="Peminta Rahasia",
        )
        self.recipient = User.objects.create_user(
            email="recipient@example.com",
            password="safe-test-password",
            display_name="Penerima Rahasia",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="safe-test-password",
            display_name="Anggota Lain",
        )
        self.shared = SwapZone.objects.create(name="Blok M", description="Bertemu di lobi.")
        self.unshared = SwapZone.objects.create(name="Bogor", description="Bertemu di stasiun.")
        self.inactive = SwapZone.objects.create(
            name="Sarang Lama", description="Tidak digunakan.", is_active=False
        )
        self.requester.swap_zones.add(self.shared, self.inactive)
        self.recipient.swap_zones.add(self.shared, self.inactive)
        self.other_user.swap_zones.add(self.unshared)
        requested_book = Book.objects.create(
            title="Matilda", authors="Roald Dahl", language="English"
        )
        offered_book = Book.objects.create(
            title="Laskar Pelangi", authors="Andrea Hirata", language="Indonesia"
        )
        self.requested = BookCopy.objects.create(
            owner=self.recipient,
            book=requested_book,
            condition=BookCopy.Condition.GOOD,
        )
        self.offered = BookCopy.objects.create(
            owner=self.requester,
            book=offered_book,
            condition=BookCopy.Condition.VERY_GOOD,
        )

    def create(self, **changes):
        values = {
            "requester": self.requester,
            "requested_copy_id": self.requested.pk,
            "offered_copy_id": self.offered.pk,
            "swap_zone_id": self.shared.pk,
        }
        values.update(changes)
        return create_minat(**values)

    def test_form_offers_only_requesters_available_copies_and_shared_active_sarang(self):
        unavailable = BookCopy.objects.create(
            owner=self.requester,
            book=Book.objects.create(title="Bumi", authors="Tere Liye", language="Indonesia"),
            condition=BookCopy.Condition.GOOD,
            availability_status=BookCopy.Availability.UNAVAILABLE,
        )
        self.requester.swap_zones.add(self.unshared)

        form = MinatCreateForm(requester=self.requester, requested_copy=self.requested)

        self.assertQuerySetEqual(form.fields["offered_copy"].queryset, [self.offered])
        self.assertQuerySetEqual(form.fields["swap_zone"].queryset, [self.shared])
        self.assertNotIn(unavailable, form.fields["offered_copy"].queryset)

    def test_copy_lock_query_locks_only_bookcopy_rows(self):
        self.assertEqual(connection.vendor, "postgresql")

        with CaptureQueriesContext(connection) as queries:
            _lock_copies(self.requested.pk, self.offered.pk)

        self.assertEqual(len(queries), 1)
        sql = queries[0]["sql"]
        self.assertIn('FROM "books_bookcopy"', sql)
        self.assertIn("FOR UPDATE", sql)
        self.assertNotIn(" JOIN ", sql)

    def test_create_revalidates_and_keeps_both_sides_anonymous(self):
        self.client.force_login(self.requester)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("swaps:minat_create", args=[self.requested.pk]),
                {"offered_copy": self.offered.pk, "swap_zone": self.shared.pk},
            )

        minat = Minat.objects.get()
        self.assertRedirects(response, reverse("swaps:minat_detail", args=[minat.pk]))
        self.assertEqual(minat.recipient, self.recipient)
        self.assertEqual(minat.status, Minat.Status.PENDING)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.requester.display_name, mail.outbox[0].body)
        self.assertNotIn(self.requester.email, mail.outbox[0].body)

        requester_detail = self.client.get(reverse("swaps:minat_detail", args=[minat.pk]))
        self.assertNotContains(requester_detail, self.recipient.display_name)
        self.assertNotContains(requester_detail, self.recipient.email)
        self.client.force_login(self.recipient)
        recipient_detail = self.client.get(reverse("swaps:minat_detail", args=[minat.pk]))
        self.assertNotContains(recipient_detail, self.requester.display_name)
        self.assertNotContains(recipient_detail, self.requester.email)

    def test_create_refuses_inactive_requester(self):
        self.requester.is_active = False
        self.requester.save(update_fields=["is_active"])

        with self.assertRaises(MinatEligibilityError):
            self.create()

    def test_create_refuses_inactive_recipient(self):
        self.recipient.is_active = False
        self.recipient.save(update_fields=["is_active"])

        with self.assertRaises(MinatEligibilityError):
            self.create()

    def test_create_refuses_own_requested_copy(self):
        own_requested = BookCopy.objects.create(
            owner=self.requester,
            book=Book.objects.create(title="Bumi", authors="Tere Liye", language="Indonesia"),
            condition=BookCopy.Condition.GOOD,
        )

        with self.assertRaises(MinatEligibilityError):
            self.create(requested_copy_id=own_requested.pk)

    def test_create_refuses_requested_copy_that_changes_owner_before_locking(self):
        locked_requested = BookCopy.objects.get(pk=self.requested.pk)
        locked_requested.owner = self.other_user
        locked_offered = BookCopy.objects.get(pk=self.offered.pk)
        with patch(
            "swaps.services._lock_copies",
            return_value={locked_requested.pk: locked_requested, locked_offered.pk: locked_offered},
        ):
            with self.assertRaises(MinatEligibilityError):
                self.create()

    def test_create_refuses_requested_or_offered_copy_that_is_not_available(self):
        for field, status in (
            ("requested", BookCopy.Availability.RESERVED),
            ("requested", BookCopy.Availability.UNAVAILABLE),
            ("offered", BookCopy.Availability.RESERVED),
            ("offered", BookCopy.Availability.UNAVAILABLE),
        ):
            with self.subTest(field=field, status=status):
                copy = getattr(self, field)
                copy.availability_status = status
                copy.save(update_fields=["availability_status"])
                with self.assertRaises(MinatEligibilityError):
                    self.create()
                copy.availability_status = BookCopy.Availability.AVAILABLE
                copy.save(update_fields=["availability_status"])

    def test_create_refuses_offered_copy_not_owned_by_requester(self):
        other_offered = BookCopy.objects.create(
            owner=self.other_user,
            book=Book.objects.create(title="Bumi", authors="Tere Liye", language="Indonesia"),
            condition=BookCopy.Condition.GOOD,
        )

        with self.assertRaises(MinatEligibilityError):
            self.create(offered_copy_id=other_offered.pk)

    def test_create_refuses_same_copy(self):
        with self.assertRaises(MinatEligibilityError):
            self.create(offered_copy_id=self.requested.pk)

    def test_create_refuses_inactive_or_unshared_sarang(self):
        for swap_zone in (self.inactive, self.unshared):
            with self.subTest(swap_zone=swap_zone):
                with self.assertRaises(MinatEligibilityError):
                    self.create(swap_zone_id=swap_zone.pk)

    def test_create_refuses_exact_pending_duplicate(self):
        with self.captureOnCommitCallbacks(execute=False):
            self.create()

        with self.assertRaises(DuplicatePendingMinat):
            self.create()

    def test_member_post_tampering_returns_field_errors(self):
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("swaps:minat_create", args=[self.requested.pk]),
            {"offered_copy": self.requested.pk, "swap_zone": self.unshared.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("offered_copy", response.context["form"].errors)
        self.assertIn("swap_zone", response.context["form"].errors)
        self.assertEqual(Minat.objects.count(), 0)

    def test_duplicate_normal_validation_uses_duplicate_message(self):
        with self.captureOnCommitCallbacks(execute=False):
            self.create()
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("swaps:minat_create", args=[self.requested.pk]),
            {"offered_copy": self.offered.pk, "swap_zone": self.shared.pk},
        )

        self.assertContains(response, DuplicatePendingMinat.message)

    def test_duplicate_constraint_race_becomes_duplicate_error(self):
        cause = Exception()
        cause.diag = SimpleNamespace(constraint_name="swaps_minat_unique_pending_combination")
        error = IntegrityError()
        error.__cause__ = cause

        with patch("swaps.services.Minat.objects.create", side_effect=error):
            with self.assertRaises(DuplicatePendingMinat):
                self.create()

    def test_unrelated_integrity_error_is_reraised(self):
        error = IntegrityError("unexpected database failure")

        with patch("swaps.services.Minat.objects.create", side_effect=error):
            with self.assertRaises(IntegrityError):
                self.create()

    def test_create_schedules_notification_only_after_commit(self):
        with patch("swaps.services.notify_new_minat") as notify:
            with self.captureOnCommitCallbacks(execute=False):
                self.create()

        notify.assert_not_called()

    def test_notification_failure_is_logged_without_sensitive_content_or_rollback(self):
        with patch(
            "swaps.notifications.send_mail",
            side_effect=Exception("address requester@example.com credential secret"),
        ):
            with self.assertLogs("swaps.notifications", level="ERROR") as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    minat = self.create()

        self.assertTrue(Minat.objects.filter(pk=minat.pk).exists())
        output = "\n".join(logs.output)
        self.assertIn(f"type=new_minat record_id={minat.pk}", output)
        for secret in (
            "requester@example.com",
            "recipient@example.com",
            "credential",
            "secret",
            "SMTPException",
        ):
            self.assertNotIn(secret, output)

    def test_private_routes_hide_ineligible_and_unrelated_records(self):
        self.client.force_login(self.requester)
        self.assertEqual(
            self.client.get(reverse("swaps:minat_create", args=[999999])).status_code,
            404,
        )
        with self.captureOnCommitCallbacks(execute=False):
            minat = self.create()
        self.client.force_login(self.other_user)

        self.assertEqual(
            self.client.get(reverse("swaps:minat_detail", args=[minat.pk])).status_code,
            404,
        )
