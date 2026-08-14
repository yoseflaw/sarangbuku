from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import SwapZone
from books.forms import BookCopyForm, ManualBookCopyForm
from books.models import Book, BookCopy
from swaps import services
from swaps.models import Minat


class ShelfIntegrationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            email="owner-shelf@example.com",
            password="safe-test-password",
            display_name="Pemilik",
        )
        self.first_member = User.objects.create_user(
            email="first-shelf@example.com",
            password="safe-test-password",
            display_name="Anggota Satu",
        )
        self.second_member = User.objects.create_user(
            email="second-shelf@example.com",
            password="safe-test-password",
            display_name="Anggota Dua",
        )
        self.zone = SwapZone.objects.create(name="Sarang Lemari", description="Lobi")
        for user in (self.owner, self.first_member, self.second_member):
            user.swap_zones.add(self.zone)
        self.copy = self.make_copy(self.owner, "Buku Pemilik")
        self.first_copy = self.make_copy(self.first_member, "Buku Pertama")
        self.second_copy = self.make_copy(self.second_member, "Buku Kedua")
        self.client.force_login(self.owner)

    def make_copy(self, owner, title, *, availability=BookCopy.Availability.AVAILABLE):
        return BookCopy.objects.create(
            owner=owner,
            book=Book.objects.create(
                title=title,
                authors="Penulis",
                language="Indonesia",
            ),
            condition=BookCopy.Condition.GOOD,
            availability_status=availability,
        )

    def make_minat(self, **values):
        return Minat.objects.create(swap_zone=self.zone, **values)

    def edit(self, *, availability):
        return self.client.post(
            reverse("books:copy_edit", args=[self.copy.pk]),
            {
                "condition": BookCopy.Condition.FAIR,
                "condition_note": "Sampul terlipat",
                "availability_status": availability,
            },
            follow=True,
        )

    def test_available_to_unavailable_rejects_every_pending_minat_and_notifies_each_requester(self):
        requested = self.make_minat(
            requester=self.first_member,
            recipient=self.owner,
            requested_copy=self.copy,
            offered_copy=self.first_copy,
        )
        offered = self.make_minat(
            requester=self.owner,
            recipient=self.second_member,
            requested_copy=self.second_copy,
            offered_copy=self.copy,
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.edit(availability=BookCopy.Availability.UNAVAILABLE)

        self.assertRedirects(response, reverse("books:shelf"))
        self.copy.refresh_from_db()
        requested.refresh_from_db()
        offered.refresh_from_db()
        self.assertEqual(self.copy.availability_status, BookCopy.Availability.UNAVAILABLE)
        self.assertEqual(requested.status, Minat.Status.AUTOMATICALLY_REJECTED)
        self.assertEqual(offered.status, Minat.Status.AUTOMATICALLY_REJECTED)
        self.assertIsNotNone(requested.resolved_at)
        self.assertIsNotNone(offered.resolved_at)
        self.assertEqual(
            [message.subject for message in mail.outbox].count(
                "Minatmu tidak dapat dilanjutkan"
            ),
            2,
        )

    def test_unavailable_to_available_changes_no_minat(self):
        self.copy.availability_status = BookCopy.Availability.UNAVAILABLE
        self.copy.save(update_fields=["availability_status"])
        minat = self.make_minat(
            requester=self.first_member,
            recipient=self.owner,
            requested_copy=self.copy,
            offered_copy=self.first_copy,
        )
        update = getattr(
            services,
            "update_book_copy",
            lambda **kwargs: self.fail("update_book_copy service is missing"),
        )

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            update(
                copy_id=self.copy.pk,
                owner=self.owner,
                condition=BookCopy.Condition.GOOD,
                condition_note="",
                availability_status=BookCopy.Availability.AVAILABLE,
            )

        minat.refresh_from_db()
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.availability_status, BookCopy.Availability.AVAILABLE)
        self.assertEqual(minat.status, Minat.Status.PENDING)
        self.assertIsNone(minat.resolved_at)
        self.assertEqual(callbacks, [])

    def test_reserved_copy_cannot_be_edited_by_get_or_post_member_flows(self):
        self.copy.availability_status = BookCopy.Availability.RESERVED
        self.copy.save(update_fields=["availability_status"])
        edit_url = reverse("books:copy_edit", args=[self.copy.pk])

        get_response = self.client.get(edit_url, follow=True)
        post_response = self.edit(availability=BookCopy.Availability.AVAILABLE)

        self.assertRedirects(get_response, reverse("books:shelf"))
        self.assertRedirects(post_response, reverse("books:shelf"))
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.condition, BookCopy.Condition.GOOD)
        self.assertEqual(self.copy.condition_note, "")
        self.assertEqual(self.copy.availability_status, BookCopy.Availability.RESERVED)

    def test_reserved_copy_cannot_be_deleted_by_get_or_post_member_flows(self):
        self.copy.availability_status = BookCopy.Availability.RESERVED
        self.copy.save(update_fields=["availability_status"])
        delete_url = reverse("books:copy_delete", args=[self.copy.pk])

        get_response = self.client.get(delete_url, follow=True)
        post_response = self.client.post(delete_url, follow=True)

        self.assertRedirects(get_response, reverse("books:shelf"))
        self.assertRedirects(post_response, reverse("books:shelf"))
        self.assertTrue(BookCopy.objects.filter(pk=self.copy.pk).exists())

    def test_copy_with_historical_minat_cannot_be_deleted(self):
        minat = self.make_minat(
            requester=self.first_member,
            recipient=self.owner,
            requested_copy=self.copy,
            offered_copy=self.first_copy,
        )
        minat.status = Minat.Status.REJECTED
        minat.save(update_fields=["status", "updated_at"])
        self.client.raise_request_exception = False

        response = self.client.post(
            reverse("books:copy_delete", args=[self.copy.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse("books:shelf"))
        self.assertTrue(BookCopy.objects.filter(pk=self.copy.pk).exists())
        self.assertContains(response, services.HistoricalCopyError.message)

    def test_copy_without_minat_remains_deletable_through_service(self):
        delete = getattr(
            services,
            "delete_book_copy",
            lambda **kwargs: self.fail("delete_book_copy service is missing"),
        )

        delete(copy_id=self.copy.pk, owner=self.owner)

        self.assertFalse(BookCopy.objects.filter(pk=self.copy.pk).exists())

    def test_member_forms_reject_reserved_before_service_invocation(self):
        edit_form = BookCopyForm(
            data={
                "condition": BookCopy.Condition.GOOD,
                "condition_note": "",
                "availability_status": BookCopy.Availability.RESERVED,
            },
            instance=self.copy,
        )
        manual_form = ManualBookCopyForm(
            data={
                "title": "Buku Baru",
                "authors": "Penulis",
                "isbn": "",
                "language": "Indonesia",
                "cover_url": "",
                "condition": BookCopy.Condition.GOOD,
                "condition_note": "",
                "availability_status": BookCopy.Availability.RESERVED,
            }
        )

        self.assertFalse(edit_form.is_valid())
        self.assertFalse(manual_form.is_valid())
        self.assertIn("availability_status", edit_form.errors)
        self.assertIn("availability_status", manual_form.errors)

    def test_notification_failure_leaves_copy_unavailable_and_minat_rejected(self):
        minat = self.make_minat(
            requester=self.first_member,
            recipient=self.owner,
            requested_copy=self.copy,
            offered_copy=self.first_copy,
        )

        with patch("swaps.notifications.send_mail", side_effect=Exception("mail unavailable")):
            with self.assertLogs("swaps.notifications", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    self.edit(availability=BookCopy.Availability.UNAVAILABLE)

        self.copy.refresh_from_db()
        minat.refresh_from_db()
        self.assertEqual(self.copy.availability_status, BookCopy.Availability.UNAVAILABLE)
        self.assertEqual(minat.status, Minat.Status.AUTOMATICALLY_REJECTED)
        self.assertIsNotNone(minat.resolved_at)
