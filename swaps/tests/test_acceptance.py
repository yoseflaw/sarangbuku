from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import SwapZone
from books.models import Book, BookCopy
from swaps import services
from swaps.models import BookSwap, Minat
from swaps.services import MinatTransitionError


class AcceptanceTests(TestCase):
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
        self.zone = SwapZone.objects.create(name="Blok M", description="Bertemu di lobi.")
        self.requester.swap_zones.add(self.zone)
        self.recipient.swap_zones.add(self.zone)
        self.requested = self.make_copy(self.recipient, "Matilda")
        self.offered = self.make_copy(self.requester, "Laskar Pelangi")
        self.minat = self.make_minat(
            requester=self.requester,
            recipient=self.recipient,
            requested_copy=self.requested,
            offered_copy=self.offered,
        )

    def make_user(self, name):
        user = get_user_model().objects.create_user(
            email=f"{name.lower()}@example.com",
            password="safe-test-password",
            display_name=name,
        )
        user.swap_zones.add(self.zone)
        return user

    def make_copy(self, owner, title):
        book = Book.objects.create(title=title, authors="Penulis", language="Indonesia")
        return BookCopy.objects.create(
            owner=owner,
            book=book,
            condition=BookCopy.Condition.GOOD,
        )

    def make_minat(self, **values):
        return Minat.objects.create(swap_zone=self.zone, **values)

    def add_conflicts(self):
        first = self.make_user("Konflik Satu")
        first_copy = self.make_copy(first, "Buku Satu")
        second = self.make_user("Konflik Dua")
        second_copy = self.make_copy(second, "Buku Dua")
        third = self.make_user("Konflik Tiga")
        third_copy = self.make_copy(third, "Buku Tiga")
        fourth = self.make_user("Konflik Empat")
        fourth_copy = self.make_copy(fourth, "Buku Empat")
        conflicts = [
            self.make_minat(
                requester=first,
                recipient=self.recipient,
                requested_copy=self.requested,
                offered_copy=first_copy,
            ),
            self.make_minat(
                requester=self.recipient,
                recipient=second,
                requested_copy=second_copy,
                offered_copy=self.requested,
            ),
            self.make_minat(
                requester=third,
                recipient=self.requester,
                requested_copy=self.offered,
                offered_copy=third_copy,
            ),
            self.make_minat(
                requester=self.requester,
                recipient=fourth,
                requested_copy=fourth_copy,
                offered_copy=self.offered,
            ),
        ]
        unrelated_requester = self.make_user("Tidak Terkait Satu")
        unrelated_recipient = self.make_user("Tidak Terkait Dua")
        unrelated = self.make_minat(
            requester=unrelated_requester,
            recipient=unrelated_recipient,
            requested_copy=self.make_copy(unrelated_recipient, "Buku Bebas Satu"),
            offered_copy=self.make_copy(unrelated_requester, "Buku Bebas Dua"),
        )
        return conflicts, unrelated

    def database_state(self):
        return {
            "minat": list(
                Minat.objects.order_by("pk").values_list(
                    "pk",
                    "status",
                    "resolved_at",
                    "requester_id",
                    "recipient_id",
                    "requested_copy_id",
                    "offered_copy_id",
                    "swap_zone_id",
                )
            ),
            "copies": list(
                BookCopy.objects.order_by("pk").values_list(
                    "pk", "owner_id", "availability_status"
                )
            ),
            "swaps": list(BookSwap.objects.order_by("pk").values_list("pk", flat=True)),
        }

    def assert_refused_without_changes(self, *, recipient=None):
        if Minat.objects.count() == 1:
            competing_requester = self.make_user("Penjaga Konflik")
            self.make_minat(
                requester=competing_requester,
                recipient=self.recipient,
                requested_copy=self.requested,
                offered_copy=self.make_copy(competing_requester, "Buku Penjaga"),
            )
        before = self.database_state()
        with self.assertRaises(MinatTransitionError):
            services.accept_minat(
                minat_id=self.minat.pk,
                recipient=recipient or self.recipient,
            )
        self.assertEqual(self.database_state(), before)

    def assert_locked_relationship_change_is_refused(self, field, replacement_id):
        lock_users = services._lock_users
        before = self.database_state()

        def change_after_seed(*user_ids):
            Minat.objects.filter(pk=self.minat.pk).update(**{field: replacement_id})
            return lock_users(*user_ids)

        with patch("swaps.services._lock_users", side_effect=change_after_seed):
            with self.assertRaises(MinatTransitionError):
                services.accept_minat(minat_id=self.minat.pk, recipient=self.recipient)

        self.assertEqual(self.database_state(), before)

    def test_only_recipient_may_accept_and_route_is_authenticated_post_only(self):
        route = reverse("swaps:minat_accept", args=[self.minat.pk])

        self.assertRedirects(self.client.post(route), f"{reverse('accounts:login')}?next={route}")
        self.client.force_login(self.requester)
        self.assertEqual(self.client.post(route).status_code, 404)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.post(route).status_code, 404)
        self.client.force_login(self.recipient)
        self.assertEqual(self.client.get(route).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.recipient)
        self.assertEqual(csrf_client.post(route).status_code, 403)

    def test_nonparticipants_get_404_before_method_rejection(self):
        route = reverse("swaps:minat_accept", args=[self.minat.pk])
        for user in (self.requester, self.other_user):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(route).status_code, 404)

    def test_pending_recipient_sees_accept_action_on_detail_and_lini(self):
        route = reverse("swaps:minat_accept", args=[self.minat.pk])
        self.client.force_login(self.recipient)

        detail = self.client.get(reverse("swaps:minat_detail", args=[self.minat.pk]))
        lini = self.client.get(reverse("swaps:lini"))

        self.assertContains(detail, route)
        self.assertContains(detail, "Terima")
        self.assertContains(lini, route)
        self.assertContains(lini, "Terima")
        self.client.force_login(self.requester)
        self.assertNotContains(
            self.client.get(reverse("swaps:minat_detail", args=[self.minat.pk])), route
        )

    def test_locked_requester_must_match_unlocked_seed(self):
        replacement = self.make_user("Peminta Pengganti")
        self.assert_locked_relationship_change_is_refused("requester_id", replacement.pk)

    def test_locked_recipient_must_match_unlocked_seed(self):
        replacement = self.make_user("Penerima Pengganti")
        self.assert_locked_relationship_change_is_refused("recipient_id", replacement.pk)

    def test_locked_requested_copy_must_match_unlocked_seed(self):
        replacement = self.make_copy(self.recipient, "Buku Diminta Pengganti")
        self.assert_locked_relationship_change_is_refused("requested_copy_id", replacement.pk)

    def test_locked_offered_copy_must_match_unlocked_seed(self):
        replacement = self.make_copy(self.requester, "Buku Ditawarkan Pengganti")
        self.assert_locked_relationship_change_is_refused("offered_copy_id", replacement.pk)

    def test_locked_sarang_must_match_unlocked_seed(self):
        replacement = SwapZone.objects.create(
            name="Sarang Pengganti", description="Bertemu di teras."
        )
        self.requester.swap_zones.add(replacement)
        self.recipient.swap_zones.add(replacement)
        self.assert_locked_relationship_change_is_refused("swap_zone_id", replacement.pk)

    def test_non_pending_minat_is_refused_without_changes(self):
        self.minat.status = Minat.Status.REJECTED
        self.minat.save(update_fields=["status", "updated_at"])

        self.assert_refused_without_changes()

    def test_inactive_participant_is_refused_without_changes(self):
        for participant in (self.requester, self.recipient):
            with self.subTest(participant=participant.email):
                participant.is_active = False
                participant.save(update_fields=["is_active"])
                self.assert_refused_without_changes()
                participant.is_active = True
                participant.save(update_fields=["is_active"])

    def test_changed_copy_ownership_is_refused_without_changes(self):
        for copy in (self.requested, self.offered):
            with self.subTest(copy=copy.pk):
                original_owner = copy.owner
                copy.owner = self.other_user
                copy.save(update_fields=["owner"])
                self.assert_refused_without_changes()
                copy.owner = original_owner
                copy.save(update_fields=["owner"])

    def test_unavailable_copy_is_refused_without_changes(self):
        for copy in (self.requested, self.offered):
            for status in (
                BookCopy.Availability.RESERVED,
                BookCopy.Availability.UNAVAILABLE,
            ):
                with self.subTest(copy=copy.pk, status=status):
                    copy.availability_status = status
                    copy.save(update_fields=["availability_status"])
                    self.assert_refused_without_changes()
                    copy.availability_status = BookCopy.Availability.AVAILABLE
                    copy.save(update_fields=["availability_status"])

    def test_inactive_or_unshared_sarang_is_refused_without_changes(self):
        self.zone.is_active = False
        self.zone.save(update_fields=["is_active"])
        self.assert_refused_without_changes()
        self.zone.is_active = True
        self.zone.save(update_fields=["is_active"])

        for participant in (self.requester, self.recipient):
            with self.subTest(participant=participant.email):
                participant.swap_zones.remove(self.zone)
                self.assert_refused_without_changes()
                participant.swap_zones.add(self.zone)

    def test_success_creates_one_tukar_reserves_copies_and_resolves_every_conflict(self):
        conflicts, unrelated = self.add_conflicts()

        with self.captureOnCommitCallbacks(execute=False):
            swap = services.accept_minat(minat_id=self.minat.pk, recipient=self.recipient)

        self.minat.refresh_from_db()
        self.requested.refresh_from_db()
        self.offered.refresh_from_db()
        for conflict in conflicts:
            conflict.refresh_from_db()
        unrelated.refresh_from_db()
        self.assertEqual(BookSwap.objects.count(), 1)
        self.assertEqual(swap.minat, self.minat)
        self.assertEqual(swap.swap_zone, self.zone)
        self.assertEqual(swap.status, BookSwap.Status.COORDINATING)
        self.assertEqual(self.minat.status, Minat.Status.ACCEPTED)
        self.assertIsNotNone(self.minat.resolved_at)
        self.assertEqual(self.requested.availability_status, BookCopy.Availability.RESERVED)
        self.assertEqual(self.offered.availability_status, BookCopy.Availability.RESERVED)
        self.assertTrue(
            all(item.status == Minat.Status.AUTOMATICALLY_REJECTED for item in conflicts)
        )
        self.assertTrue(all(item.resolved_at == self.minat.resolved_at for item in conflicts))
        self.assertEqual(unrelated.status, Minat.Status.PENDING)
        self.assertIsNone(unrelated.resolved_at)

    def test_acceptance_notifications_wait_for_commit_and_reach_each_affected_requester(self):
        conflicts, _ = self.add_conflicts()

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            services.accept_minat(minat_id=self.minat.pk, recipient=self.recipient)

        self.assertEqual(mail.outbox, [])
        self.assertEqual(len(callbacks), 1 + len(conflicts))
        for callback in callbacks:
            callback()
        self.assertEqual(
            [message.subject for message in mail.outbox].count("Minat diterima"),
            2,
        )
        self.assertEqual(
            [message.subject for message in mail.outbox].count(
                "Minatmu tidak dapat dilanjutkan"
            ),
            len(conflicts),
        )
        self.assertCountEqual(
            [message.to[0] for message in mail.outbox],
            [self.requester.email, self.recipient.email]
            + [item.requester.email for item in conflicts],
        )

    def test_delivery_failure_cannot_undo_acceptance_or_conflict_resolution(self):
        conflicts, _ = self.add_conflicts()
        with patch("swaps.notifications.send_mail", side_effect=Exception("mail unavailable")):
            with self.assertLogs("swaps.notifications", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    services.accept_minat(minat_id=self.minat.pk, recipient=self.recipient)

        self.minat.refresh_from_db()
        self.requested.refresh_from_db()
        self.offered.refresh_from_db()
        self.assertEqual(self.minat.status, Minat.Status.ACCEPTED)
        self.assertEqual(BookSwap.objects.count(), 1)
        self.assertEqual(self.requested.availability_status, BookCopy.Availability.RESERVED)
        self.assertEqual(self.offered.availability_status, BookCopy.Availability.RESERVED)
        self.assertFalse(
            Minat.objects.filter(
                pk__in=[item.pk for item in conflicts], status=Minat.Status.PENDING
            ).exists()
        )

    def test_repeated_acceptance_creates_no_second_tukar(self):
        with self.captureOnCommitCallbacks(execute=False):
            first = services.accept_minat(minat_id=self.minat.pk, recipient=self.recipient)

        with self.assertRaises(MinatTransitionError):
            services.accept_minat(minat_id=self.minat.pk, recipient=self.recipient)

        self.assertEqual(BookSwap.objects.count(), 1)
        self.assertEqual(BookSwap.objects.get(), first)

    def test_stale_accept_view_shows_generic_error_without_identity_details(self):
        self.requested.availability_status = BookCopy.Availability.UNAVAILABLE
        self.requested.save(update_fields=["availability_status"])
        self.client.force_login(self.recipient)

        response = self.client.post(
            reverse("swaps:minat_accept", args=[self.minat.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse("swaps:minat_detail", args=[self.minat.pk]))
        self.assertContains(response, MinatTransitionError.message)
        self.assertNotContains(response, self.requester.display_name)
        self.assertNotContains(response, self.requester.email)
        self.assertEqual(BookSwap.objects.count(), 0)

    def test_accept_view_redirects_with_success_and_history_status(self):
        self.client.force_login(self.recipient)

        with self.captureOnCommitCallbacks(execute=False):
            response = self.client.post(
                reverse("swaps:minat_accept", args=[self.minat.pk]),
                follow=True,
            )

        self.assertRedirects(response, reverse("swaps:minat_detail", args=[self.minat.pk]))
        self.assertContains(response, "Minat diterima. Tukar ini siap dikoordinasikan.")
        self.assertContains(self.client.get(reverse("swaps:lini")), "Diterima")


class ConcurrentAcceptanceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        User = get_user_model()
        self.recipient = User.objects.create_user(
            email="recipient-race@example.com",
            password="safe-test-password",
            display_name="Penerima",
        )
        first_requester = User.objects.create_user(
            email="first-race@example.com",
            password="safe-test-password",
            display_name="Peminta Satu",
        )
        second_requester = User.objects.create_user(
            email="second-race@example.com",
            password="safe-test-password",
            display_name="Peminta Dua",
        )
        zone = SwapZone.objects.create(name="Sarang Balap", description="Bertemu di lobi.")
        self.recipient.swap_zones.add(zone)
        first_requester.swap_zones.add(zone)
        second_requester.swap_zones.add(zone)
        self.shared_copy = BookCopy.objects.create(
            owner=self.recipient,
            book=Book.objects.create(title="Buku Bersama", authors="Penulis", language="Indonesia"),
            condition=BookCopy.Condition.GOOD,
        )
        first_offered = BookCopy.objects.create(
            owner=first_requester,
            book=Book.objects.create(title="Buku Satu", authors="Penulis", language="Indonesia"),
            condition=BookCopy.Condition.GOOD,
        )
        second_offered = BookCopy.objects.create(
            owner=second_requester,
            book=Book.objects.create(title="Buku Dua", authors="Penulis", language="Indonesia"),
            condition=BookCopy.Condition.GOOD,
        )
        self.first = Minat.objects.create(
            requester=first_requester,
            recipient=self.recipient,
            requested_copy=self.shared_copy,
            offered_copy=first_offered,
            swap_zone=zone,
        )
        self.second = Minat.objects.create(
            requester=second_requester,
            recipient=self.recipient,
            requested_copy=self.shared_copy,
            offered_copy=second_offered,
            swap_zone=zone,
        )

    def worker(self, minat_id, barrier):
        close_old_connections()
        try:
            recipient = get_user_model().objects.get(pk=self.recipient.pk)
            barrier.wait()
            try:
                swap = services.accept_minat(minat_id=minat_id, recipient=recipient)
                return ("accepted", swap.pk)
            except MinatTransitionError:
                return ("refused", None)
        finally:
            close_old_connections()

    def test_same_copy_can_be_reserved_by_only_one_concurrent_acceptance(self):
        self.assertEqual(connection.vendor, "postgresql")
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda minat_id: self.worker(minat_id, barrier),
                    [self.first.pk, self.second.pk],
                )
            )

        self.assertCountEqual([result[0] for result in results], ["accepted", "refused"])
        self.assertEqual(BookSwap.objects.count(), 1)
        self.shared_copy.refresh_from_db()
        self.assertEqual(
            self.shared_copy.availability_status,
            BookCopy.Availability.RESERVED,
        )
        self.assertCountEqual(
            Minat.objects.values_list("status", flat=True),
            [Minat.Status.ACCEPTED, Minat.Status.AUTOMATICALLY_REJECTED],
        )
