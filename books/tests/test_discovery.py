from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import SwapZone
from books.forms import DiscoveryFilterForm
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


class DiscoveryFilterFormTests(DiscoverySetupMixin, TestCase):
    def test_sarang_choices_are_only_viewers_active_sarang(self):
        form = DiscoveryFilterForm(viewer=self.viewer)

        self.assertCountEqual(
            form.fields["sarang"].queryset,
            [self.shared, self.second_shared],
        )
        self.assertNotIn(self.inactive_zone, form.fields["sarang"].queryset)

    def test_rejects_sarang_outside_viewers_active_choices(self):
        form = DiscoveryFilterForm(
            {"sarang": self.unshared.pk},
            viewer=self.viewer,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("sarang", form.errors)


class DiscoveryListTests(DiscoverySetupMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.copy = BookCopy.objects.create(
            owner=cls.owner,
            book=cls.book,
            condition=BookCopy.Condition.GOOD,
            condition_note="Sampul sedikit terlipat.",
            is_available=True,
        )

    def setUp(self):
        self.client.force_login(self.viewer)

    def test_unfiltered_page_shows_permitted_data_without_owner_identity(self):
        response = self.client.get(reverse("books:discover"))

        self.assertContains(response, "Matilda")
        self.assertContains(response, "Roald Dahl")
        self.assertContains(response, "Masih Bagus")
        self.assertContains(response, "Sampul sedikit terlipat.")
        self.assertContains(response, "Blok M")
        self.assertNotContains(response, self.owner.display_name)
        self.assertNotContains(response, self.owner.email)
        self.assertNotContains(response, "Ajukan Minat")

    def test_search_matches_title_author_and_normalized_isbn(self):
        for query in ("matilda", "roald dahl", "978-0-14-032872-1"):
            with self.subTest(query=query):
                response = self.client.get(reverse("books:discover"), {"q": query})
                self.assertContains(response, "Matilda")

    def test_sarang_condition_and_wishlist_filters_compose(self):
        WishlistItem.objects.create(user=self.viewer, book=self.book)

        response = self.client.get(
            reverse("books:discover"),
            {
                "sarang": self.shared.pk,
                "condition": BookCopy.Condition.GOOD,
                "wishlist": "on",
            },
        )

        self.assertContains(response, "Matilda")
        self.assertContains(response, "Ada di Daftar Minat")

    def test_book_filter_matches_exact_catalog_record(self):
        other_edition = Book.objects.create(
            title="Matilda",
            authors="Roald Dahl",
            isbn="9780142410370",
            language="English",
        )
        BookCopy.objects.create(
            owner=self.owner,
            book=other_edition,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )

        response = self.client.get(
            reverse("books:discover"),
            {"book": self.book.pk},
        )

        self.assertContains(response, self.book.isbn)
        self.assertNotContains(response, other_edition.isbn)

    def test_invalid_book_filter_returns_no_results_instead_of_broadening(self):
        response = self.client.get(reverse("books:discover"), {"book": "999999"})

        self.assertContains(response, "Pilih pilihan yang valid")
        self.assertNotContains(response, "Matilda")

    def test_invalid_filter_error_is_associated_with_control(self):
        response = self.client.get(
            reverse("books:discover"),
            {"condition": "not-a-condition"},
        )

        self.assertContains(
            response,
            'aria-describedby="id_condition_error"',
            html=False,
        )
        self.assertContains(response, 'aria-invalid="true"', html=False)
        self.assertContains(
            response,
            '<div id="id_condition_error" class="invalid-feedback d-block" role="alert">',
            html=False,
        )

    def test_invalid_filter_returns_no_results_instead_of_broadening(self):
        response = self.client.get(
            reverse("books:discover"),
            {"condition": "not-a-condition"},
        )

        self.assertContains(response, "Pilih pilihan yang valid")
        self.assertNotContains(response, "Matilda")

    def test_pagination_is_24_and_preserves_filters(self):
        for index in range(24):
            book = Book.objects.create(
                title=f"Matilda {index:02d}",
                authors="Roald Dahl",
                language="English",
            )
            BookCopy.objects.create(
                owner=self.owner,
                book=book,
                condition=BookCopy.Condition.GOOD,
                is_available=True,
            )

        response = self.client.get(
            reverse("books:discover"),
            {"q": "Matilda", "page": 2},
        )

        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertContains(response, "q=Matilda")

    def test_guards_and_navigation_labels(self):
        response = self.client.get(reverse("books:discover"))
        self.assertContains(response, ">Temukan<", html=False)
        self.assertContains(response, ">Daftar Minat<", html=False)

        self.viewer.swap_zones.clear()
        self.assertRedirects(
            self.client.get(reverse("books:discover")),
            reverse("accounts:profile"),
        )

        self.client.logout()
        self.assertRedirects(
            self.client.get(reverse("books:discover")),
            f'{reverse("accounts:login")}?next={reverse("books:discover")}',
        )


class DiscoveryDetailTests(DiscoverySetupMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.copy = BookCopy.objects.create(
            owner=cls.owner,
            book=cls.book,
            condition=BookCopy.Condition.GOOD,
            condition_note="Sampul sedikit terlipat.",
            is_available=True,
        )

    def setUp(self):
        self.client.force_login(self.viewer)

    def test_anonymous_user_redirects_to_login(self):
        self.client.logout()
        detail_url = reverse("books:discovery_detail", args=[self.copy.pk])

        response = self.client.get(detail_url)

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={detail_url}",
        )

    def test_user_without_active_sarang_redirects_to_profile_with_message(self):
        self.viewer.swap_zones.clear()

        response = self.client.get(
            reverse("books:discovery_detail", args=[self.copy.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertContains(
            response,
            "Pilih setidaknya satu Sarang aktif di Profil untuk melanjutkan.",
        )

    def test_eligible_detail_shows_only_permitted_information(self):
        response = self.client.get(
            reverse("books:discovery_detail", args=[self.copy.pk])
        )

        self.assertContains(response, "Matilda")
        self.assertContains(response, "Roald Dahl")
        self.assertContains(response, "Masih Bagus")
        self.assertContains(response, "Sampul sedikit terlipat.")
        self.assertContains(response, "Blok M")
        self.assertNotContains(response, self.owner.display_name)
        self.assertNotContains(response, self.owner.email)
        self.assertNotContains(response, "Ajukan Minat")

    def test_detail_does_not_expose_owners_other_copy(self):
        BookCopy.objects.create(
            owner=self.owner,
            book=self.other_book,
            condition=BookCopy.Condition.GOOD,
            is_available=True,
        )

        response = self.client.get(
            reverse("books:discovery_detail", args=[self.copy.pk])
        )

        self.assertNotContains(response, "Laskar Pelangi")

    def test_unknown_and_each_newly_ineligible_copy_return_404(self):
        url = reverse("books:discovery_detail", args=[self.copy.pk])
        self.assertEqual(
            self.client.get(reverse("books:discovery_detail", args=[999999])).status_code,
            404,
        )

        self.copy.is_available = False
        self.copy.save(update_fields=["is_available"])
        self.assertEqual(self.client.get(url).status_code, 404)

        self.copy.is_available = True
        self.copy.save(update_fields=["is_available"])
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(url).status_code, 404)

        self.owner.is_active = True
        self.owner.save(update_fields=["is_active"])
        self.owner.swap_zones.clear()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_detail_uses_real_wishlist_mutations(self):
        detail_url = reverse("books:discovery_detail", args=[self.copy.pk])
        response = self.client.get(detail_url)
        self.assertContains(
            response,
            reverse("books:wishlist_add", args=[self.book.pk]),
        )

        self.client.post(
            reverse("books:wishlist_add", args=[self.book.pk]),
            {"next": detail_url},
        )
        response = self.client.get(detail_url)
        self.assertContains(response, "Ada di Daftar Minat")
        self.assertContains(
            response,
            reverse("books:wishlist_remove", args=[self.book.pk]),
        )


class DiscoveryAccessibilityTests(TestCase):
    def test_global_focus_visible_overrides_component_focus_styles(self):
        css = (Path(__file__).resolve().parents[2] / "static/css/sarangbuku.css").read_text()

        self.assertIn(
            ":focus-visible {\n"
            "  outline: 2px solid #000 !important;\n"
            "  outline-offset: 2px;\n"
            "  box-shadow: none !important;\n"
            "}",
            css,
        )
