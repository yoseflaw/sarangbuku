from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import SwapZone
from books.models import Book, BookCopy, WishlistItem
from books.services import discoverable_copies


class DiscoverySetupMixin:
    @classmethod
    def setUpTestData(cls):
        cls.shared = SwapZone.objects.create(
            name="Blok M",
            description="Bertemu di lobi.",
            is_active=True,
        )
        cls.second_shared = SwapZone.objects.create(
            name="Gambir",
            description="Bertemu di pintu utama.",
            is_active=True,
        )
        cls.unshared = SwapZone.objects.create(
            name="Bogor",
            description="Bertemu di stasiun.",
            is_active=True,
        )
        cls.inactive_zone = SwapZone.objects.create(
            name="Sarang Lama",
            description="Tidak digunakan.",
            is_active=False,
        )
        cls.viewer = get_user_model().objects.create_user(
            email="viewer@example.com",
            display_name="Pemirsa",
            password="safe-test-password",
        )
        cls.owner = get_user_model().objects.create_user(
            email="owner@example.com",
            display_name="Pemilik Rahasia",
            password="safe-test-password",
        )
        cls.other_owner = get_user_model().objects.create_user(
            email="other-owner@example.com",
            display_name="Pemilik Lain",
            password="safe-test-password",
        )
        cls.inactive_owner = get_user_model().objects.create_user(
            email="inactive@example.com",
            display_name="Tidak Aktif",
            password="safe-test-password",
            is_active=False,
        )
        cls.viewer.swap_zones.add(cls.shared, cls.second_shared, cls.inactive_zone)
        cls.owner.swap_zones.add(cls.shared, cls.second_shared, cls.inactive_zone)
        cls.other_owner.swap_zones.add(cls.unshared)
        cls.inactive_owner.swap_zones.add(cls.shared)
        cls.book = Book.objects.create(
            title="Matilda",
            authors="Roald Dahl",
            isbn="9780140328721",
            language="English",
        )
        cls.other_book = Book.objects.create(
            title="Laskar Pelangi",
            authors="Andrea Hirata",
            language="Indonesia",
        )


class DiscoverableCopiesTests(DiscoverySetupMixin, TestCase):
    def test_returns_available_copy_once_with_all_shared_active_sarang(self):
        copy = BookCopy.objects.create(
            owner=self.owner,
            book=self.book,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )

        result = list(discoverable_copies(viewer=self.viewer))

        self.assertEqual(result, [copy])
        self.assertCountEqual(
            result[0].owner.shared_active_zones,
            [self.shared, self.second_shared],
        )

    def test_excludes_every_ineligible_copy(self):
        eligible = BookCopy.objects.create(
            owner=self.owner,
            book=self.book,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )
        BookCopy.objects.create(
            owner=self.viewer,
            book=self.other_book,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )
        BookCopy.objects.create(
            owner=self.owner,
            book=self.other_book,
            condition=BookCopy.Condition.GOOD,
            is_available=False,
        )
        BookCopy.objects.create(
            owner=self.other_owner,
            book=self.other_book,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )
        BookCopy.objects.create(
            owner=self.inactive_owner,
            book=self.other_book,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )

        self.assertEqual(list(discoverable_copies(viewer=self.viewer)), [eligible])

    def test_inactive_shared_sarang_does_not_qualify(self):
        self.owner.swap_zones.set([self.inactive_zone])
        copy = BookCopy.objects.create(
            owner=self.owner,
            book=self.book,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )

        self.assertNotIn(copy, discoverable_copies(viewer=self.viewer))

    def test_annotates_private_wishlist_match(self):
        copy = BookCopy.objects.create(
            owner=self.owner,
            book=self.book,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )
        WishlistItem.objects.create(user=self.viewer, book=self.book)

        result = discoverable_copies(viewer=self.viewer).get(pk=copy.pk)

        self.assertTrue(result.is_wishlisted)
