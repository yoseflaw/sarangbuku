from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import SwapZone
from books.models import Book, BookCopy

User = get_user_model()


class CatalogSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reader@example.com",
            password="testpass123",
            display_name="Pembaca",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", 
            password="testpass123",
            display_name="Pengguna Lain",
        )
        self.zone = SwapZone.objects.create(
            name="Blok M",
            description="Bertemu di lobi.",
            is_active=True,
        )
        self.user.swap_zones.add(self.zone)

        # Local books for search
        self.matilda_book = Book.objects.create(
            title="Matilda",
            authors="Roald Dahl",
            isbn="9780140328721",
            language="English",
        )
        # Other user's copy (should not show owner identity)
        BookCopy.objects.create(
            owner=self.other_user,
            book=self.matilda_book,
            condition=BookCopy.Condition.GOOD,
        )

    def test_search_matches_title_author_and_normalized_isbn(self):
        self.client.force_login(self.user)
        for query in ("matilda", "roald dahl", "978-0-14-032872-1"):
            with self.subTest(query=query):
                response = self.client.get(reverse("books:add"), {"q": query})
                self.assertContains(response, "Matilda")

    def test_blank_search_has_form_error(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("books:add"), {"q": "   "})
        self.assertContains(response, "Masukkan ISBN, judul, atau penulis.")

    def test_results_do_not_show_owner_or_copy_count(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("books:add"), {"q": "Matilda"})
        self.assertNotContains(response, self.other_user.display_name)
        self.assertNotContains(response, self.other_user.email)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("books:add"))
        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={reverse("books:add")}',
        )

    def test_user_without_active_sarang_is_redirected_to_profile(self):
        user_no_zones = User.objects.create_user(
            email="nozone@example.com",
            password="testpass123", 
            display_name="Tanpa Sarang",
        )
        self.client.force_login(user_no_zones)
        response = self.client.get(reverse("books:add"))
        self.assertRedirects(response, reverse("accounts:profile"))


class CatalogCopyCreationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reader@example.com",
            password="testpass123",
            display_name="Pembaca",
        )
        self.zone = SwapZone.objects.create(
            name="Blok M",
            description="Bertemu di lobi.",
            is_active=True,
        )
        self.user.swap_zones.add(self.zone)
        
        self.book = Book.objects.create(
            title="The Great Gatsby",
            authors="F. Scott Fitzgerald",
            language="English",
        )

    def test_copy_create_creates_bookcopy_not_book(self):
        self.client.force_login(self.user)
        book_count_before = Book.objects.count()
        copy_count_before = BookCopy.objects.count()
        
        response = self.client.post(reverse("books:copy_create", args=[self.book.pk]), {
            "condition": BookCopy.Condition.GOOD,
            "condition_note": "Well maintained",
            "availability_status": "available",
        })
        
        self.assertRedirects(response, reverse("books:shelf"))
        self.assertEqual(Book.objects.count(), book_count_before)  # No new books
        self.assertEqual(BookCopy.objects.count(), copy_count_before + 1)  # One new copy
        
        # Verify the copy was created correctly
        copy = BookCopy.objects.get(owner=self.user, book=self.book)
        self.assertEqual(copy.condition, BookCopy.Condition.GOOD)
        self.assertEqual(copy.condition_note, "Well maintained")
        self.assertEqual(copy.availability_status, BookCopy.Availability.AVAILABLE)

    def test_successful_copy_creation_redirects_to_shelf_with_message(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("books:copy_create", args=[self.book.pk]), {
            "condition": BookCopy.Condition.LIKE_NEW,
            "availability_status": "available",
        }, follow=True)
        
        self.assertRedirects(response, reverse("books:shelf"))
        self.assertContains(response, "Buku sudah ditambahkan ke Lemari.")

    def test_invalid_condition_preserves_errors_creates_nothing(self):
        self.client.force_login(self.user)
        copy_count_before = BookCopy.objects.count()
        
        response = self.client.post(reverse("books:copy_create", args=[self.book.pk]), {
            # Missing required condition field
            "availability_status": "available",
        })
        
        self.assertEqual(response.status_code, 200)  # Form validation failed
        self.assertEqual(BookCopy.objects.count(), copy_count_before)  # No copy created

    def test_copy_create_without_active_sarang_redirects_without_writes(self):
        user_no_zones = User.objects.create_user(
            email="nozone@example.com",
            password="testpass123",
            display_name="Tanpa Sarang",
        )
        self.client.force_login(user_no_zones)
        copy_count_before = BookCopy.objects.count()
        
        response = self.client.post(reverse("books:copy_create", args=[self.book.pk]), {
            "condition": BookCopy.Condition.GOOD,
            "availability_status": "available",
        })
        
        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertEqual(BookCopy.objects.count(), copy_count_before)  # No copy created

    def test_results_are_capped_at_25_and_ordered_deterministically(self):
        # Create more than 25 books
        for i in range(30):
            Book.objects.create(
                title=f"Test Book {i:02d}",
                authors="Test Author",
                language="English",
            )
        
        self.client.force_login(self.user)
        response = self.client.get(reverse("books:add"), {"q": "Test"})
        
        books = response.context["books"]
        self.assertEqual(len(books), 25)
        # Verify ordering
        titles = [book.title for book in books]
        self.assertEqual(titles, sorted(titles))

    def test_anonymous_user_redirected_for_copy_create(self):
        response = self.client.get(reverse("books:copy_create", args=[self.book.pk]))
        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={reverse("books:copy_create", args=[self.book.pk])}',
        )