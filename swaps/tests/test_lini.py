from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SwapZone
from books.models import Book, BookCopy
from swaps.models import Minat
from swaps.services import MinatTransitionError, reject_minat, withdraw_minat


class LiniTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user(
            email="requester@example.com", password="safe-test-password", display_name="Peminta Rahasia"
        )
        self.recipient = User.objects.create_user(
            email="recipient@example.com", password="safe-test-password", display_name="Penerima Rahasia"
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", password="safe-test-password", display_name="Anggota Lain"
        )
        self.zone = SwapZone.objects.create(name="Blok M", description="Bertemu di lobi.")
        self.requester.swap_zones.add(self.zone)
        self.recipient.swap_zones.add(self.zone)
        requested_book = Book.objects.create(title="Matilda", authors="Roald Dahl", language="English")
        offered_book = Book.objects.create(title="Laskar Pelangi", authors="Andrea Hirata", language="Indonesia")
        self.requested = BookCopy.objects.create(
            owner=self.recipient, book=requested_book, condition=BookCopy.Condition.GOOD
        )
        self.offered = BookCopy.objects.create(
            owner=self.requester, book=offered_book, condition=BookCopy.Condition.VERY_GOOD
        )
        self.minat = self.make_minat()

    def make_minat(self, **changes):
        values = {
            "requester": self.requester,
            "recipient": self.recipient,
            "requested_copy": self.requested,
            "offered_copy": self.offered,
            "swap_zone": self.zone,
        }
        values.update(changes)
        return Minat.objects.create(**values)

    def test_lini_groups_pending_and_history_newest_first_with_approved_labels(self):
        received = self.minat
        sent = self.make_minat(
            requester=self.recipient,
            recipient=self.requester,
            requested_copy=self.offered,
            offered_copy=self.requested,
        )
        base = timezone.make_aware(datetime(2026, 8, 14, 10, 0))
        older = self.make_minat(
            status=Minat.Status.REJECTED,
            resolved_at=base,
        )
        newer = self.make_minat(
            status=Minat.Status.WITHDRAWN,
            resolved_at=base + timedelta(minutes=1),
        )
        automatic = self.make_minat(
            status=Minat.Status.AUTOMATICALLY_REJECTED,
            resolved_at=base + timedelta(minutes=2),
        )
        accepted = self.make_minat(
            status=Minat.Status.ACCEPTED,
            resolved_at=base + timedelta(minutes=3),
        )
        for index, minat in enumerate((received, sent, older, newer, automatic, accepted)):
            Minat.objects.filter(pk=minat.pk).update(created_at=base + timedelta(minutes=index))

        self.client.force_login(self.recipient)
        response = self.client.get(reverse("swaps:lini"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["received"]), [received])
        self.assertEqual(list(response.context["sent"]), [sent])
        self.assertEqual(list(response.context["history"]), [accepted, automatic, newer, older])
        self.assertContains(response, "Ditunggu")
        self.assertContains(response, "Menunggu")
        self.assertContains(response, "Riwayat")
        self.assertContains(response, "Tolak")
        self.assertContains(response, "Batal")
        for label in ("Diterima", "Ditolak", "Dibatalkan", "Ditolak otomatis"):
            self.assertContains(response, label)

    def test_empty_lini_sections_explain_next_action_and_link_to_temukan(self):
        self.minat.delete()
        self.client.force_login(self.requester)

        response = self.client.get(reverse("swaps:lini"))

        self.assertContains(response, "Belum ada Minat yang menunggu jawabanmu.")
        self.assertContains(response, "Belum ada Minat yang kamu kirim.")
        self.assertContains(response, "Temukan")
        self.assertContains(response, reverse("books:discover"))
        self.assertContains(response, "Belum ada riwayat Minat.")

    def test_lini_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("swaps:lini"))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('swaps:lini')}")

    def test_non_participant_gets_404_from_detail_and_mutations(self):
        self.client.force_login(self.other_user)
        routes = (
            ("get", "swaps:minat_detail"),
            ("post", "swaps:minat_withdraw"),
            ("post", "swaps:minat_reject"),
        )

        for method, route in routes:
            with self.subTest(route=route):
                response = getattr(self.client, method)(reverse(route, args=[self.minat.pk]))
                self.assertEqual(response.status_code, 404)

    def test_requester_cannot_reject_and_recipient_cannot_withdraw(self):
        self.client.force_login(self.requester)
        self.assertEqual(
            self.client.post(reverse("swaps:minat_reject", args=[self.minat.pk])).status_code, 404
        )
        self.client.force_login(self.recipient)
        self.assertEqual(
            self.client.post(reverse("swaps:minat_withdraw", args=[self.minat.pk])).status_code, 404
        )

    def test_action_routes_reject_get_requests(self):
        self.client.force_login(self.requester)
        self.assertEqual(
            self.client.get(reverse("swaps:minat_withdraw", args=[self.minat.pk])).status_code, 405
        )
        self.client.force_login(self.recipient)
        self.assertEqual(
            self.client.get(reverse("swaps:minat_reject", args=[self.minat.pk])).status_code, 405
        )

    def test_withdrawal_changes_only_pending_minat_without_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            withdrawn = withdraw_minat(minat_id=self.minat.pk, requester=self.requester)

        self.requested.refresh_from_db()
        self.offered.refresh_from_db()
        self.assertEqual(withdrawn.status, Minat.Status.WITHDRAWN)
        self.assertIsNotNone(withdrawn.resolved_at)
        self.assertEqual(self.requested.availability_status, BookCopy.Availability.AVAILABLE)
        self.assertEqual(self.offered.availability_status, BookCopy.Availability.AVAILABLE)
        self.assertEqual(mail.outbox, [])

    def test_rejection_changes_only_pending_minat_and_notifies_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            rejected = reject_minat(minat_id=self.minat.pk, recipient=self.recipient)

        self.requested.refresh_from_db()
        self.offered.refresh_from_db()
        self.assertEqual(rejected.status, Minat.Status.REJECTED)
        self.assertIsNotNone(rejected.resolved_at)
        self.assertEqual(self.requested.availability_status, BookCopy.Availability.AVAILABLE)
        self.assertEqual(self.offered.availability_status, BookCopy.Availability.AVAILABLE)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.recipient.display_name, mail.outbox[0].body)
        self.assertNotIn(self.recipient.email, mail.outbox[0].body)

    def test_resolved_minat_cannot_be_withdrawn_or_rejected(self):
        self.minat.status = Minat.Status.REJECTED
        self.minat.save(update_fields=["status", "updated_at"])

        with self.assertRaises(MinatTransitionError):
            withdraw_minat(minat_id=self.minat.pk, requester=self.requester)
        with self.assertRaises(MinatTransitionError):
            reject_minat(minat_id=self.minat.pk, recipient=self.recipient)
        self.minat.refresh_from_db()
        self.assertEqual(self.minat.status, Minat.Status.REJECTED)

    def test_withdraw_view_redirects_with_success_message(self):
        self.client.force_login(self.requester)

        response = self.client.post(reverse("swaps:minat_withdraw", args=[self.minat.pk]), follow=True)

        self.assertRedirects(response, reverse("swaps:minat_detail", args=[self.minat.pk]))
        self.assertContains(response, "Minat sudah dibatalkan.")

    def test_reject_view_redirects_with_success_message_without_revealing_identity(self):
        self.client.force_login(self.recipient)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("swaps:minat_reject", args=[self.minat.pk]), follow=True)

        self.assertRedirects(response, reverse("swaps:minat_detail", args=[self.minat.pk]))
        self.assertContains(response, "Minat sudah ditolak.")
        self.assertNotContains(response, self.requester.display_name)
        self.assertNotContains(response, self.requester.email)

    def test_stale_authorized_action_redirects_with_transition_error(self):
        self.minat.status = Minat.Status.WITHDRAWN
        self.minat.save(update_fields=["status", "updated_at"])
        self.client.force_login(self.requester)

        response = self.client.post(reverse("swaps:minat_withdraw", args=[self.minat.pk]), follow=True)

        self.assertRedirects(response, reverse("swaps:minat_detail", args=[self.minat.pk]))
        self.assertContains(response, MinatTransitionError.message)
