from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import NoReverseMatch, reverse

from accounts.models import SwapZone
from books.models import Book, BookCopy
from swaps import services
from swaps.models import BookSwap, Minat


class DeactivationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_superuser(
            email="admin-deactivation@example.com",
            password="safe-test-password",
            display_name="Admin",
        )
        self.member = User.objects.create_user(
            email="member-deactivation@example.com",
            password="safe-test-password",
            display_name="Anggota",
        )
        self.other = User.objects.create_user(
            email="other-deactivation@example.com",
            password="safe-test-password",
            display_name="Anggota Lain",
        )
        self.third = User.objects.create_user(
            email="third-deactivation@example.com",
            password="safe-test-password",
            display_name="Anggota Ketiga",
        )
        self.zone = SwapZone.objects.create(name="Sarang Admin", description="Lobi")
        for user in (self.member, self.other, self.third):
            user.swap_zones.add(self.zone)
        self.member_copy = self.make_copy(self.member, "Buku Anggota")
        self.other_copy = self.make_copy(self.other, "Buku Lain")
        self.third_copy = self.make_copy(self.third, "Buku Ketiga")

    def make_copy(self, owner, title):
        return BookCopy.objects.create(
            owner=owner,
            book=Book.objects.create(
                title=title,
                authors="Penulis",
                language="Indonesia",
            ),
            condition=BookCopy.Condition.GOOD,
        )

    def make_minat(self, **values):
        return Minat.objects.create(swap_zone=self.zone, **values)

    def deactivate(self, user):
        deactivate = getattr(
            services,
            "deactivate_account",
            lambda **kwargs: self.fail("deactivate_account service is missing"),
        )
        return deactivate(user_id=user.pk)

    def post_action(self, action, *users, follow=True):
        self.client.force_login(self.staff)
        return self.client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": action,
                "_selected_action": [user.pk for user in users],
            },
            follow=follow,
        )

    def test_deactivation_rejects_all_pending_sent_and_received_minat_after_commit(self):
        sent = self.make_minat(
            requester=self.member,
            recipient=self.other,
            requested_copy=self.other_copy,
            offered_copy=self.member_copy,
        )
        received = self.make_minat(
            requester=self.third,
            recipient=self.member,
            requested_copy=self.member_copy,
            offered_copy=self.third_copy,
        )

        with self.captureOnCommitCallbacks(execute=True):
            self.deactivate(self.member)

        self.member.refresh_from_db()
        sent.refresh_from_db()
        received.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertEqual(sent.status, Minat.Status.AUTOMATICALLY_REJECTED)
        self.assertEqual(received.status, Minat.Status.AUTOMATICALLY_REJECTED)
        self.assertIsNotNone(sent.resolved_at)
        self.assertIsNotNone(received.resolved_at)
        self.assertEqual(
            [message.subject for message in mail.outbox].count(
                "Minatmu tidak dapat dilanjutkan"
            ),
            2,
        )

    def test_deactivation_leaves_resolved_minat_intact(self):
        rejected = self.make_minat(
            requester=self.member,
            recipient=self.third,
            requested_copy=self.third_copy,
            offered_copy=self.member_copy,
        )
        services.reject_minat(minat_id=rejected.pk, recipient=self.third)
        rejected.refresh_from_db()
        resolved_at = rejected.resolved_at

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.deactivate(self.member)

        self.member.refresh_from_db()
        rejected.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertEqual(rejected.status, Minat.Status.REJECTED)
        self.assertEqual(rejected.resolved_at, resolved_at)
        self.assertEqual(callbacks, [])

    def test_deactivation_is_refused_for_either_participant_in_coordinating_tukar(self):
        accepted = self.make_minat(
            requester=self.member,
            recipient=self.other,
            requested_copy=self.other_copy,
            offered_copy=self.member_copy,
        )
        accepted.status = Minat.Status.ACCEPTED
        accepted.save(update_fields=["status", "updated_at"])
        BookSwap.objects.create(minat=accepted, swap_zone=self.zone)

        for participant in (self.member, self.other):
            with self.subTest(participant=participant.email):
                with self.assertRaises(services.UnfinishedSwapError):
                    self.deactivate(participant)
                participant.refresh_from_db()
                accepted.refresh_from_db()
                self.assertTrue(participant.is_active)
                self.assertEqual(accepted.status, Minat.Status.ACCEPTED)

    def test_admin_change_form_renders_existing_is_active_read_only(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("admin:accounts_user_change", args=[self.member.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<img src="/static/admin/img/icon-yes.svg" alt="True">',
            html=True,
        )
        self.assertNotContains(response, 'name="is_active"')

    @patch("accounts.admin.deactivate_account", create=True)
    def test_admin_deactivation_action_routes_every_account_through_service(self, deactivate):
        response = self.post_action("deactivate_accounts", self.member)

        self.assertEqual(response.status_code, 200)
        deactivate.assert_called_once_with(user_id=self.member.pk)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_admin_deactivation_action_reports_refused_unfinished_accounts(self):
        accepted = self.make_minat(
            requester=self.member,
            recipient=self.other,
            requested_copy=self.other_copy,
            offered_copy=self.member_copy,
        )
        accepted.status = Minat.Status.ACCEPTED
        accepted.save(update_fields=["status", "updated_at"])
        BookSwap.objects.create(minat=accepted, swap_zone=self.zone)

        response = self.post_action("deactivate_accounts", self.member)

        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertContains(response, "1 akun masih memiliki Tukar yang belum selesai.")

    def test_admin_change_post_cannot_bypass_deactivation_service(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("admin:accounts_user_change", args=[self.member.pk]),
            {
                "email": self.member.email,
                "password": self.member.password,
                "display_name": self.member.display_name,
                "is_active": "",
                "is_staff": "",
                "is_superuser": "",
                "groups": [],
                "user_permissions": [],
                "swap_zones": [self.zone.pk],
                "last_login_0": "",
                "last_login_1": "",
                "date_joined_0": self.member.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": self.member.date_joined.strftime("%H:%M:%S"),
                "_save": "Simpan",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_admin_activation_action_explicitly_reactivates_inactive_account(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])

        response = self.post_action("activate_accounts", self.member)

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertContains(response, "1 akun diaktifkan.")

    def test_accounts_has_no_member_deactivation_url(self):
        with self.assertRaises(NoReverseMatch):
            reverse("accounts:deactivate")


class ConcurrentAcceptanceDeactivationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user(
            email="requester-deactivation-race@example.com",
            password="safe-test-password",
            display_name="Peminta",
        )
        self.recipient = User.objects.create_user(
            email="recipient-deactivation-race@example.com",
            password="safe-test-password",
            display_name="Penerima",
        )
        self.zone = SwapZone.objects.create(
            name="Sarang Deaktivasi Balap",
            description="Bertemu di lobi.",
        )
        self.requester.swap_zones.add(self.zone)
        self.recipient.swap_zones.add(self.zone)
        self.requested_copy = self.make_copy(self.recipient, "Buku Diminta")
        self.offered_copy = self.make_copy(self.requester, "Buku Ditawarkan")
        self.minat = Minat.objects.create(
            requester=self.requester,
            recipient=self.recipient,
            requested_copy=self.requested_copy,
            offered_copy=self.offered_copy,
            swap_zone=self.zone,
        )

    def make_copy(self, owner, title):
        return BookCopy.objects.create(
            owner=owner,
            book=Book.objects.create(
                title=title,
                authors="Penulis",
                language="Indonesia",
            ),
            condition=BookCopy.Condition.GOOD,
        )

    def accept(self, barrier):
        close_old_connections()
        try:
            recipient = get_user_model().objects.get(pk=self.recipient.pk)
            barrier.wait()
            try:
                services.accept_minat(minat_id=self.minat.pk, recipient=recipient)
            except services.MinatTransitionError:
                return "acceptance_refused"
            return "accepted"
        finally:
            close_old_connections()

    def deactivate(self, barrier):
        close_old_connections()
        try:
            barrier.wait()
            try:
                services.deactivate_account(user_id=self.requester.pk)
            except services.UnfinishedSwapError:
                return "deactivation_refused"
            return "deactivated"
        finally:
            close_old_connections()

    def test_acceptance_and_deactivation_commit_one_complete_outcome(self):
        self.assertEqual(connection.vendor, "postgresql")
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            accept = executor.submit(self.accept, barrier)
            deactivate = executor.submit(self.deactivate, barrier)
            results = {accept.result(), deactivate.result()}

        self.requester.refresh_from_db()
        self.minat.refresh_from_db()
        self.requested_copy.refresh_from_db()
        self.offered_copy.refresh_from_db()
        self.assertIsNotNone(self.minat.resolved_at)

        if results == {"accepted", "deactivation_refused"}:
            self.assertTrue(self.requester.is_active)
            self.assertEqual(self.minat.status, Minat.Status.ACCEPTED)
            self.assertEqual(
                self.requested_copy.availability_status,
                BookCopy.Availability.RESERVED,
            )
            self.assertEqual(
                self.offered_copy.availability_status,
                BookCopy.Availability.RESERVED,
            )
            self.assertTrue(
                BookSwap.objects.filter(
                    minat=self.minat,
                    status=BookSwap.Status.COORDINATING,
                ).exists()
            )
        else:
            self.assertEqual(results, {"acceptance_refused", "deactivated"})
            self.assertFalse(self.requester.is_active)
            self.assertEqual(
                self.minat.status,
                Minat.Status.AUTOMATICALLY_REJECTED,
            )
            self.assertEqual(
                self.requested_copy.availability_status,
                BookCopy.Availability.AVAILABLE,
            )
            self.assertEqual(
                self.offered_copy.availability_status,
                BookCopy.Availability.AVAILABLE,
            )
            self.assertFalse(BookSwap.objects.filter(minat=self.minat).exists())
