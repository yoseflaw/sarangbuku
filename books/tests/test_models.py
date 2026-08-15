from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase

from books.models import Book, BookCopy, WishlistItem, normalize_isbn, validate_isbn


class IsbnTests(SimpleTestCase):
    def test_normalize_isbn_removes_spaces_and_hyphens(self):
        self.assertEqual(normalize_isbn("978-0-14-032872-1"), "9780140328721")
        self.assertEqual(normalize_isbn("0 306 40615 x"), "030640615X")

    def test_normalize_isbn_returns_empty_string_for_missing_value(self):
        self.assertEqual(normalize_isbn(None), "")
        self.assertEqual(normalize_isbn("  "), "")

    def test_validate_isbn_accepts_valid_checksums(self):
        validate_isbn("0306406152")
        validate_isbn("9780140328721")

    def test_validate_isbn_rejects_invalid_checksums_and_characters(self):
        for value in ("0306406153", "9780140328720", "not-an-isbn"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_isbn(value)


class BookModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="reader@example.com",
            display_name="Pembaca",
            password="safe-test-password",
        )

    def test_book_normalizes_isbn_when_saved(self):
        book = Book.objects.create(
            title="Matilda",
            authors="Roald Dahl",
            isbn="978-0-14-032872-1",
            language="English",
        )
        self.assertEqual(book.isbn, "9780140328721")

    def test_multiple_books_without_isbn_are_allowed(self):
        for _ in range(2):
            Book.objects.create(
                title="Cerita Tanpa ISBN",
                authors="Penulis",
                language="Indonesia",
            )
        self.assertEqual(Book.objects.filter(isbn__isnull=True).count(), 2)

    def test_duplicate_normalized_isbn_is_rejected(self):
        Book.objects.create(
            title="Matilda",
            authors="Roald Dahl",
            isbn="9780140328721",
            language="English",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Book.objects.create(
                title="Matilda lain",
                authors="Roald Dahl",
                isbn="978-0-14-032872-1",
                language="English",
            )

    def test_one_owner_may_have_multiple_copies_of_one_book(self):
        book = Book.objects.create(
            title="Matilda", authors="Roald Dahl", language="English"
        )
        for _ in range(2):
            BookCopy.objects.create(
                owner=self.user,
                book=book,
                condition=BookCopy.Condition.GOOD,
            )
        self.assertEqual(book.copies.filter(owner=self.user).count(), 2)

    def test_condition_values_and_labels_are_canonical(self):
        self.assertEqual(
            list(BookCopy.Condition.choices),
            [
                ("like_new", "Seperti Baru"),
                ("very_good", "Sangat Bagus"),
                ("good", "Masih Bagus"),
                ("fair", "Cukup Bagus"),
                ("bad", "Sudah Buruk"),
            ],
        )

    def test_owner_and_book_deletion_are_protected(self):
        book = Book.objects.create(
            title="Matilda", authors="Roald Dahl", language="English"
        )
        BookCopy.objects.create(
            owner=self.user,
            book=book,
            condition=BookCopy.Condition.GOOD,
        )
        with self.assertRaises(ProtectedError):
            self.user.delete()
        with self.assertRaises(ProtectedError):
            book.delete()

    def test_book_full_clean_rejects_invalid_isbn(self):
        book = Book(isbn="invalid-isbn")
        with self.assertRaises(ValidationError):
            book.full_clean()

    def test_book_full_clean_rejects_ftp_cover_url(self):
        book = Book(cover_url="ftp://example.com/cover.jpg")
        with self.assertRaises(ValidationError):
            book.full_clean()

    def test_book_full_clean_accepts_http_and_https_cover_urls(self):
        for scheme in ("http", "https"):
            book = Book(
                title="Test",
                authors="Test", 
                language="English",
                cover_url=f"{scheme}://example.com/cover.jpg"
            )
            book.full_clean()  # Should not raise

    def test_condition_note_max_length_is_140(self):
        self.assertEqual(BookCopy._meta.get_field('condition_note').max_length, 140)

    def test_database_condition_constraint_rejects_unknown_value(self):
        book = Book.objects.create(
            title="Test", authors="Test", language="English"
        )
        # This should fail at the database level
        with self.assertRaises((IntegrityError, ValidationError)), transaction.atomic():
            copy = BookCopy(owner=self.user, book=book, condition="unknown")
            copy.save()


class BookCopyAvailabilityTests(TestCase):
    def test_availability_values_labels_and_default_are_canonical(self):
        field = BookCopy._meta.get_field("availability_status")
        self.assertEqual(
            list(BookCopy.Availability.choices),
            [
                ("available", "Tersedia"),
                ("reserved", "Ada Peminat"),
                ("unavailable", "Tidak tersedia"),
            ],
        )
        self.assertEqual(field.default, BookCopy.Availability.AVAILABLE)

    def test_unknown_availability_is_rejected_by_database(self):
        owner = get_user_model().objects.create_user(
            email="status@example.com", password="safe-test-password"
        )
        book = Book.objects.create(title="Status", authors="Penulis", language="Indonesia")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BookCopy.objects.create(
                owner=owner,
                book=book,
                condition=BookCopy.Condition.GOOD,
                availability_status="unknown",
            )


class WishlistItemModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="wishlist@example.com",
            display_name="Pembaca",
            password="safe-test-password",
        )
        cls.other_user = get_user_model().objects.create_user(
            email="other-wishlist@example.com",
            display_name="Pembaca Lain",
            password="safe-test-password",
        )
        cls.book = Book.objects.create(
            title="Matilda",
            authors="Roald Dahl",
            language="English",
        )
        cls.other_book = Book.objects.create(
            title="Laskar Pelangi",
            authors="Andrea Hirata",
            language="Indonesia",
        )

    def test_user_and_book_pair_is_unique(self):
        WishlistItem.objects.create(user=self.user, book=self.book)

        with self.assertRaises(IntegrityError), transaction.atomic():
            WishlistItem.objects.create(user=self.user, book=self.book)

    def test_users_and_editions_remain_independent(self):
        WishlistItem.objects.create(user=self.user, book=self.book)
        WishlistItem.objects.create(user=self.other_user, book=self.book)
        WishlistItem.objects.create(user=self.user, book=self.other_book)

        self.assertEqual(WishlistItem.objects.count(), 3)

    def test_deleting_item_preserves_catalog_record(self):
        item = WishlistItem.objects.create(user=self.user, book=self.book)

        item.delete()

        self.assertTrue(Book.objects.filter(pk=self.book.pk).exists())


class AdminTests(SimpleTestCase):
    def test_book_admin_is_registered(self):
        from django.contrib import admin
        from books.models import Book
        from books.admin import BookAdmin
        
        self.assertIsInstance(admin.site._registry[Book], BookAdmin)
        self.assertEqual(BookAdmin.list_display, ("title", "authors", "isbn", "language"))
        self.assertEqual(BookAdmin.search_fields, ("title", "authors", "isbn"))

    def test_bookcopy_admin_is_registered(self):
        from django.contrib import admin
        from books.models import BookCopy
        from books.admin import BookCopyAdmin
        
        self.assertIsInstance(admin.site._registry[BookCopy], BookCopyAdmin)
        self.assertEqual(BookCopyAdmin.list_display, ("book", "owner", "condition", "availability_status"))
        self.assertEqual(BookCopyAdmin.list_filter, ("condition", "availability_status"))
        self.assertEqual(BookCopyAdmin.search_fields, ("book__title", "book__authors", "book__isbn", "owner__email"))
        self.assertEqual(BookCopyAdmin.list_select_related, ("book", "owner"))
        self.assertEqual(
            BookCopyAdmin.readonly_fields,
            ("owner", "book", "availability_status"),
        )

    def test_wishlist_admin_is_registered(self):
        from django.contrib import admin
        from books.admin import WishlistItemAdmin
        from books.models import WishlistItem

        self.assertIsInstance(admin.site._registry[WishlistItem], WishlistItemAdmin)
        self.assertEqual(
            WishlistItemAdmin.list_display,
            ("user", "book", "book_authors", "created_at"),
        )
        self.assertEqual(
            WishlistItemAdmin.search_fields,
            ("user__email", "book__title", "book__authors", "book__isbn"),
        )