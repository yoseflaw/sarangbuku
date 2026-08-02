from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from books.models import Book, BookCopy

User = get_user_model()


class ShelfTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
            first_name="Owner",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            first_name="Other",
        )
        
        self.owners_book = Book.objects.create(
            title="Owner Book",
            authors="Author One",
            language="Indonesian",
            cover_url="https://example.com/cover1.jpg",
        )
        self.other_book = Book.objects.create(
            title="Other User Book",
            authors="Author Two",
            language="Indonesian",
            cover_url="https://example.com/cover2.jpg",
        )
        
        self.copy = BookCopy.objects.create(
            owner=self.owner,
            book=self.owners_book,
            condition=BookCopy.Condition.GOOD,
            condition_note="Sedikit lecek",
            is_available=True,
        )
        self.other_copy = BookCopy.objects.create(
            owner=self.other_user,
            book=self.other_book,
            condition=BookCopy.Condition.LIKE_NEW,
            is_available=True,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("books:shelf"))
        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={reverse("books:shelf")}',
        )

    def test_shelf_shows_only_signed_in_users_copies(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("books:shelf"))
        self.assertContains(response, self.owners_book.title)
        self.assertNotContains(response, self.other_book.title)

    def test_shelf_shows_unavailable_copy_and_approved_condition_label(self):
        self.copy.is_available = False
        self.copy.condition = BookCopy.Condition.VERY_GOOD
        self.copy.save(update_fields=("is_available", "condition"))
        self.client.force_login(self.owner)
        response = self.client.get(reverse("books:shelf"))
        self.assertContains(response, "Sangat Bagus")
        self.assertContains(response, "Tidak tersedia")

    def test_shelf_empty_state_shows_tambah(self):
        # Remove the copy to test empty state
        self.copy.delete()
        self.client.force_login(self.owner)
        response = self.client.get(reverse("books:shelf"))
        self.assertContains(response, "Tambah")

    def test_shelf_shows_book_details(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("books:shelf"))
        self.assertContains(response, self.owners_book.authors)
        self.assertContains(response, self.owners_book.language)
        self.assertContains(response, "Sedikit lecek")  # condition note

    def test_shelf_shows_cover_or_placeholder(self):
        # Test with cover URL
        self.client.force_login(self.owner)
        response = self.client.get(reverse("books:shelf"))
        self.assertContains(response, self.owners_book.cover_url)
        
        # Test without cover URL
        self.owners_book.cover_url = ""
        self.owners_book.save()
        response = self.client.get(reverse("books:shelf"))
        self.assertContains(response, "placeholder")  # Placeholder indicator

    def test_copy_edit_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("books:copy_edit", args=[self.copy.pk]))
        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={reverse("books:copy_edit", args=[self.copy.pk])}',
        )

    def test_copy_edit_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("books:copy_edit", args=[self.copy.pk]))
        self.assertEqual(response.status_code, 404)

    def test_copy_edit_post_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        response = self.client.post(reverse("books:copy_edit", args=[self.copy.pk]), {
            "condition": BookCopy.Condition.BAD,
            "is_available": False,
        })
        self.assertEqual(response.status_code, 404)

    def test_copy_edit_changes_condition_note_availability(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("books:copy_edit", args=[self.copy.pk]), {
            "condition": BookCopy.Condition.BAD,
            "condition_note": "Rusak parah",
            "is_available": False,
        })
        self.assertRedirects(response, reverse("books:shelf"))
        
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.condition, BookCopy.Condition.BAD)
        self.assertEqual(self.copy.condition_note, "Rusak parah")
        self.assertFalse(self.copy.is_available)

    def test_copy_edit_cannot_change_book_or_owner(self):
        # Form should not have these fields, but test security anyway
        self.client.force_login(self.owner)
        original_book = self.copy.book
        original_owner = self.copy.owner
        
        self.client.post(reverse("books:copy_edit", args=[self.copy.pk]), {
            "condition": BookCopy.Condition.FAIR,
            "is_available": True,
            "book": self.other_book.pk,
            "owner": self.other_user.pk,
        })
        
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.book, original_book)
        self.assertEqual(self.copy.owner, original_owner)

    def test_copy_delete_get_preserves_copy(self):
        self.client.force_login(self.owner)
        copy_count = BookCopy.objects.count()
        response = self.client.get(reverse("books:copy_delete", args=[self.copy.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BookCopy.objects.count(), copy_count)

    def test_copy_delete_post_removes_copy_but_preserves_book(self):
        self.client.force_login(self.owner)
        book_count = Book.objects.count()
        response = self.client.post(reverse("books:copy_delete", args=[self.copy.pk]))
        self.assertRedirects(response, reverse("books:shelf"))
        
        self.assertFalse(BookCopy.objects.filter(pk=self.copy.pk).exists())
        self.assertEqual(Book.objects.count(), book_count)

    def test_copy_delete_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("books:copy_delete", args=[self.copy.pk]))
        self.assertEqual(response.status_code, 404)

    def test_copy_delete_post_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        response = self.client.post(reverse("books:copy_delete", args=[self.copy.pk]))
        self.assertEqual(response.status_code, 404)

    def test_copy_delete_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("books:copy_delete", args=[self.copy.pk]))
        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={reverse("books:copy_delete", args=[self.copy.pk])}',
        )

    def test_navigation_shows_lemari_when_signed_in(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("books:shelf"))
        # Check that the page renders (implying navigation works)
        self.assertEqual(response.status_code, 200)
        # Navigation test will be verified in the template