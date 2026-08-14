from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import SwapZone
from books.models import Book, WishlistItem


class WishlistViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zone = SwapZone.objects.create(
            name="Blok M",
            description="Bertemu di lobi.",
            is_active=True,
        )
        cls.user = get_user_model().objects.create_user(
            email="reader@example.com",
            display_name="Pembaca",
            password="safe-test-password",
        )
        cls.user.swap_zones.add(cls.zone)
        cls.other_user = get_user_model().objects.create_user(
            email="other@example.com",
            display_name="Pengguna Lain",
            password="safe-test-password",
        )
        cls.other_user.swap_zones.add(cls.zone)
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

    def setUp(self):
        self.client.force_login(self.user)

    def test_page_is_private_and_lists_only_own_items(self):
        WishlistItem.objects.create(user=self.user, book=self.book)
        WishlistItem.objects.create(user=self.other_user, book=self.other_book)

        response = self.client.get(reverse("books:wishlist"))

        self.assertContains(response, "Matilda")
        self.assertNotContains(response, "Laskar Pelangi")
        self.assertNotContains(response, self.other_user.display_name)
        self.assertNotContains(response, self.other_user.email)

    def test_local_search_matches_title_author_and_normalized_isbn(self):
        for query in ("matilda", "roald dahl", "978-0-14-032872-1"):
            with self.subTest(query=query):
                response = self.client.get(reverse("books:wishlist"), {"q": query})
                self.assertContains(response, "Matilda")

    def test_search_does_not_offer_external_or_manual_entry(self):
        response = self.client.get(reverse("books:wishlist"), {"q": "Tidak Ada"})

        self.assertNotContains(response, "Open Library")
        self.assertNotContains(response, "Masukkan manual")

    def test_add_is_post_only_idempotent_and_preserves_safe_next(self):
        url = reverse("books:wishlist_add", args=[self.book.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

        for _ in range(2):
            response = self.client.post(
                url,
                {"next": reverse("books:wishlist") + "?q=Matilda"},
            )
            self.assertRedirects(response, reverse("books:wishlist") + "?q=Matilda")

        self.assertEqual(
            WishlistItem.objects.filter(user=self.user, book=self.book).count(),
            1,
        )

    def test_add_rejects_external_next(self):
        response = self.client.post(
            reverse("books:wishlist_add", args=[self.book.pk]),
            {"next": "https://attacker.example/steal"},
        )

        self.assertRedirects(response, reverse("books:wishlist"))

    def test_remove_is_post_only_and_scoped_to_user(self):
        own = WishlistItem.objects.create(user=self.user, book=self.book)
        other = WishlistItem.objects.create(user=self.other_user, book=self.other_book)
        own_url = reverse("books:wishlist_remove", args=[self.book.pk])

        self.assertEqual(self.client.get(own_url).status_code, 405)
        self.assertRedirects(self.client.post(own_url), reverse("books:wishlist"))
        self.assertFalse(WishlistItem.objects.filter(pk=own.pk).exists())

        other_url = reverse("books:wishlist_remove", args=[self.other_book.pk])
        self.assertEqual(self.client.post(other_url).status_code, 404)
        self.assertTrue(WishlistItem.objects.filter(pk=other.pk).exists())

    def test_anonymous_user_redirects_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("books:wishlist"))

        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={reverse("books:wishlist")}',
        )

    def test_user_without_active_sarang_redirects_to_profile(self):
        self.user.swap_zones.clear()

        response = self.client.get(reverse("books:wishlist"), follow=True)

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertContains(
            response,
            "Pilih setidaknya satu Sarang aktif di Profil untuk melanjutkan.",
        )
