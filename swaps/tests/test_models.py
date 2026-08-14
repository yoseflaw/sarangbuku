from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import PROTECT, ProtectedError
from django.test import TestCase

from accounts.models import SwapZone
from books.models import Book, BookCopy
from swaps.admin import BookSwapAdmin, MinatAdmin
from swaps.models import BookSwap, Minat


class SwapModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user(
            email="requester@example.com", password="safe-test-password", display_name="Peminta"
        )
        self.recipient = User.objects.create_user(
            email="recipient@example.com", password="safe-test-password", display_name="Penerima"
        )
        self.other_requester = User.objects.create_user(
            email="other-requester@example.com",
            password="safe-test-password",
            display_name="Peminta lain",
        )
        self.zone = SwapZone.objects.create(name="Blok M", description="Bertemu di lobi.")
        self.other_zone = SwapZone.objects.create(name="Senayan", description="Bertemu di taman.")
        book = Book.objects.create(title="Matilda", authors="Roald Dahl", language="English")
        other = Book.objects.create(title="Laskar Pelangi", authors="Andrea Hirata", language="Indonesia")
        another = Book.objects.create(title="Bumi", authors="Tere Liye", language="Indonesia")
        self.requested = BookCopy.objects.create(
            owner=self.recipient, book=book, condition=BookCopy.Condition.GOOD
        )
        self.other_requested = BookCopy.objects.create(
            owner=self.recipient, book=another, condition=BookCopy.Condition.GOOD
        )
        self.offered = BookCopy.objects.create(
            owner=self.requester, book=other, condition=BookCopy.Condition.VERY_GOOD
        )
        self.other_offered = BookCopy.objects.create(
            owner=self.requester, book=another, condition=BookCopy.Condition.VERY_GOOD
        )

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

    def test_status_values_and_bookswap_shape_are_canonical(self):
        self.assertEqual(
            list(Minat.Status.values),
            ["pending", "accepted", "rejected", "withdrawn", "automatically_rejected"],
        )
        self.assertEqual(list(BookSwap.Status.values), ["coordinating"])
        self.assertFalse(hasattr(BookSwap, "requester"))
        self.assertFalse(hasattr(BookSwap, "completed_at"))

    def test_every_historical_relationship_uses_protect(self):
        for model, field_names in (
            (Minat, ("requester", "recipient", "requested_copy", "offered_copy", "swap_zone")),
            (BookSwap, ("minat", "swap_zone")),
        ):
            for field_name in field_names:
                with self.subTest(model=model.__name__, field=field_name):
                    self.assertIs(
                        model._meta.get_field(field_name).remote_field.on_delete,
                        PROTECT,
                    )

    def test_requested_and_offered_copy_must_differ(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_minat(offered_copy=self.requested)

    def test_only_exact_pending_duplicate_is_forbidden(self):
        first = self.make_minat()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_minat()
        first.status = Minat.Status.REJECTED
        first.save(update_fields=["status", "updated_at"])
        self.make_minat()
        self.assertEqual(Minat.objects.count(), 2)

    def test_pending_combinations_other_than_an_exact_duplicate_are_allowed(self):
        self.make_minat()
        for changes in (
            {"offered_copy": self.other_offered},
            {"requested_copy": self.other_requested},
            {"requester": self.other_requester},
            {"swap_zone": self.other_zone},
        ):
            with self.subTest(changes=changes):
                self.make_minat(**changes)
        self.assertEqual(Minat.objects.count(), 5)

    def test_resolved_at_is_optional_and_newest_minat_is_first(self):
        first = self.make_minat()
        second = self.make_minat(offered_copy=self.other_offered)
        self.assertIsNone(first.resolved_at)
        self.assertEqual(list(Minat.objects.values_list("pk", flat=True)), [second.pk, first.pk])

    def test_historical_relationships_are_protected(self):
        minat = self.make_minat(status=Minat.Status.ACCEPTED)
        swap = BookSwap.objects.create(minat=minat, swap_zone=self.zone)
        for protected in (
            self.requester,
            self.recipient,
            self.requested,
            self.offered,
            self.zone,
            minat,
        ):
            with self.subTest(model=type(protected).__name__), self.assertRaises(ProtectedError):
                protected.delete()
        self.assertTrue(BookSwap.objects.filter(pk=swap.pk).exists())

    def test_admin_is_registered_for_inspection_only(self):
        self.assertIsInstance(admin.site._registry[Minat], MinatAdmin)
        self.assertIsInstance(admin.site._registry[BookSwap], BookSwapAdmin)
        request = type("Request", (), {"user": self.requester})()
        self.assertFalse(admin.site._registry[Minat].has_add_permission(request))
        self.assertFalse(admin.site._registry[Minat].has_delete_permission(request))
        self.assertFalse(admin.site._registry[BookSwap].has_add_permission(request))
        self.assertFalse(admin.site._registry[BookSwap].has_delete_permission(request))
