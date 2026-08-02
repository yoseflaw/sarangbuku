from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import SwapZone
from books.forms import ManualBookCopyForm
from books.models import Book, BookCopy

User = get_user_model()

VALID_DATA = {
    "title": "Matilda",
    "authors": "Roald Dahl",
    "isbn": "978-0-14-032872-1",
    "language": "English",
    "cover_url": "https://covers.openlibrary.org/b/id/123-M.jpg",
    "condition": "good",
    "condition_note": "Ada sedikit lipatan.",
    "is_available": "on",
}


class ManualEntryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="test")
        self.zone = SwapZone.objects.create(name="Jakarta", description="Jakarta area")
        self.user.swap_zones.add(self.zone)
        self.client.force_login(self.user)
        self.form = ManualBookCopyForm(VALID_DATA)

    def test_manual_form_creates_book_and_copy(self):
        response = self.client.post(reverse("books:manual_create"), VALID_DATA)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("books:shelf"))
        
        self.assertEqual(Book.objects.count(), 1)
        book = Book.objects.first()
        self.assertEqual(book.title, "Matilda")
        self.assertEqual(book.authors, "Roald Dahl")
        self.assertEqual(book.isbn, "9780140328721")  # normalized
        
        self.assertEqual(BookCopy.objects.count(), 1)
        copy = BookCopy.objects.first()
        self.assertEqual(copy.owner, self.user)
        self.assertEqual(copy.book, book)
        self.assertEqual(copy.condition, "good")
        self.assertEqual(copy.condition_note, "Ada sedikit lipatan.")
        self.assertTrue(copy.is_available)

    def test_invalid_isbn_checksum_rejected(self):
        data = VALID_DATA.copy()
        data["isbn"] = "978-0-14-032872-2"  # wrong checksum
        response = self.client.post(reverse("books:manual_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Masukkan ISBN-10 atau ISBN-13 yang valid.")
        self.assertEqual(Book.objects.count(), 0)

    def test_ftp_cover_url_rejected(self):
        data = VALID_DATA.copy()
        data["cover_url"] = "ftp://example.com/cover.jpg"
        response = self.client.post(reverse("books:manual_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Masukkan URL yang valid.")
        self.assertEqual(Book.objects.count(), 0)

    def test_long_condition_note_rejected(self):
        data = VALID_DATA.copy()
        data["condition_note"] = "x" * 141
        response = self.client.post(reverse("books:manual_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pastikan nilai ini mengandung paling banyak 140 karakter")
        self.assertEqual(Book.objects.count(), 0)

    def test_missing_required_fields_rejected(self):
        for field in ["title", "authors", "language", "condition"]:
            with self.subTest(field=field):
                data = VALID_DATA.copy()
                del data[field]
                response = self.client.post(reverse("books:manual_create"), data)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Bidang ini tidak boleh kosong.")
                self.assertEqual(Book.objects.count(), 0)

    def test_invalid_fields_are_identified_by_indonesian_labels(self):
        data = VALID_DATA.copy()
        data.update(
            isbn="9780306406158",
            cover_url="ftp://example.com/cover.jpg",
            condition_note="x" * 141,
        )
        response = self.client.post(reverse("books:manual_create"), data)

        self.assertContains(response, '<div class="alert alert-danger" role="alert">')
        self.assertContains(
            response,
            "<li>ISBN: Masukkan ISBN-10 atau ISBN-13 yang valid.</li>",
            html=True,
        )
        self.assertContains(
            response,
            "<li>URL sampul: Masukkan URL yang valid.</li>",
            html=True,
        )
        self.assertContains(
            response,
            "<li>Catatan kondisi: Pastikan nilai ini mengandung paling banyak 140 karakter (sekarang 141 karakter).</li>",
            html=True,
        )

    def test_safe_values_remain_after_validation_failure(self):
        data = VALID_DATA.copy()
        data["isbn"] = "invalid"
        response = self.client.post(reverse("books:manual_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, data["title"])
        self.assertContains(response, data["authors"])

    def test_user_without_active_sarang_creates_nothing(self):
        self.user.swap_zones.clear()
        response = self.client.post(reverse("books:manual_create"), VALID_DATA)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertEqual(Book.objects.count(), 0)

    def test_anonymous_user_redirected(self):
        self.client.logout()
        response = self.client.post(reverse("books:manual_create"), VALID_DATA)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/akun/masuk/", response.url)

    def test_existing_isbn_reuses_book_without_overwriting_metadata(self):
        existing = Book.objects.create(
            title="Judul lokal",
            authors="Penulis lokal",
            isbn="9780140328721",
            language="Indonesia",
        )
        response = self.client.post(reverse("books:manual_create"), VALID_DATA)
        self.assertEqual(response.status_code, 302)
        
        self.assertEqual(Book.objects.count(), 1)
        book = Book.objects.first()
        self.assertEqual(book.title, "Judul lokal")  # unchanged
        self.assertEqual(book.authors, "Penulis lokal")  # unchanged
        self.assertEqual(book.language, "Indonesia")  # unchanged
        
        copy = BookCopy.objects.first()
        self.assertEqual(copy.book, existing)

    def test_copy_failure_rolls_back_new_book(self):
        self.assertTrue(self.form.is_valid())
        with patch("books.services.BookCopy.objects.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.form.save(owner=self.user)
        self.assertFalse(Book.objects.filter(title="Matilda").exists())

    def test_no_isbn_submissions_create_distinct_books(self):
        data = VALID_DATA.copy()
        data["isbn"] = ""
        
        # First submission
        response = self.client.post(reverse("books:manual_create"), data)
        self.assertEqual(response.status_code, 302)
        
        # Second submission with same data but different title
        data["title"] = "Different Title"
        response = self.client.post(reverse("books:manual_create"), data)
        self.assertEqual(response.status_code, 302)
        
        self.assertEqual(Book.objects.count(), 2)
        self.assertEqual(BookCopy.objects.count(), 2)


class ConcurrentIsbnCreationTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="test")
        self.zone = SwapZone.objects.create(name="Jakarta", description="Jakarta area")
        self.user.swap_zones.add(self.zone)

    def worker(self, barrier):
        close_old_connections()
        try:
            barrier.wait()

            # Fresh instances for each thread
            user = User.objects.get(pk=self.user.pk)
            data = VALID_DATA.copy()
            data["title"] = f"Title {barrier.parties}"  # Different titles

            form = ManualBookCopyForm(data)
            if form.is_valid():
                form.save(owner=user)
        finally:
            close_old_connections()

    def test_concurrent_same_isbn_creates_one_book_two_copies(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.worker, barrier) for _ in range(2)]
            for future in futures:
                future.result()

        self.assertEqual(Book.objects.filter(isbn="9780140328721").count(), 1)
        self.assertEqual(BookCopy.objects.filter(book__isbn="9780140328721").count(), 2)