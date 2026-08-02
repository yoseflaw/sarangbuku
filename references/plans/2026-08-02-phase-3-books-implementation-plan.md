# Phase 3 Books Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an authenticated user find or create a local catalog record, add a physical copy, and manage it privately in `Lemari`.

**Architecture:** Keep catalog records and physical copies in the existing `books` Django app. Use ordinary server-rendered GET/POST/redirect flows, PostgreSQL constraints, one atomic persistence service, and a small Python standard-library Open Library client. Local pages read only local data; external metadata is revalidated by the same form used for manual entry before persistence.

**Tech Stack:** Django 5.2, PostgreSQL, Django Templates, Bootstrap, Python standard library, WhiteNoise

## Global Constraints

- The working source of truth is `references/mvp/MVP_SPEC.md`; the approved Phase 3 design is `references/specs/2026-08-02-phase-3-books-design.md`.
- Keep bibliographic `Book` records separate from owned physical `BookCopy` rows.
- A user may own multiple copies of the same `Book`.
- Use all five conditions with these labels: `like_new` / `Seperti Baru`, `very_good` / `Sangat Bagus`, `good` / `Masih Bagus`, `fair` / `Cukup Bagus`, `bad` / `Sudah Buruk`.
- Limit condition notes to 140 characters.
- Use external cover URLs or a placeholder; do not add uploads.
- Require authentication for every books page and an active selected Sarang before adding a copy.
- Never expose another user's identity, email, or books.
- Use natural conversational Indonesian that follows EYD; use `Lemari` and `Tambah` in the interface.
- Use Django's CSRF, escaping, form validation, and server-side ownership checks.
- Preserve mobile usability, visible labels, keyboard access, focus visibility, and adequate contrast.
- Add no dependency and no speculative model, route, or placeholder for wishlist, discovery, Minat, reservations, ownership history, or public book details.
- Use PostgreSQL for development and tests; do not add a SQLite fallback.

---

## File Map

### Create

- `books/forms.py`: search, physical-copy, and combined metadata/copy forms
- `books/services.py`: atomic ISBN reuse and copy creation
- `books/open_library.py`: bounded Open Library HTTP client and response mapping
- `books/urls.py`: books routes
- `books/migrations/0001_phase_3_books.py`: initial books schema
- `books/tests/__init__.py`
- `books/tests/test_models.py`
- `books/tests/test_shelf.py`
- `books/tests/test_catalog.py`
- `books/tests/test_manual_entry.py`
- `books/tests/test_open_library.py`
- `templates/books/shelf.html`
- `templates/books/add.html`
- `templates/books/copy_form.html`
- `templates/books/manual_form.html`
- `templates/books/copy_confirm_delete.html`

### Modify

- `books/models.py`: `Book`, `BookCopy`, and ISBN helpers
- `books/admin.py`: catalog and copy administration
- `books/views.py`: Lemari, search, add, edit, and delete flows
- `config/urls.py`: mount `books.urls` at `/buku/`
- `templates/base.html`: authenticated `Lemari` and `Tambah` navigation
- `templates/accounts/profile.html`: activate the `Tambah` card
- `static/css/sarangbuku.css`: cover and book-card presentation
- `accounts/tests/test_profile.py`: update the Phase 2 placeholder assertion

### Delete

- `books/tests.py`: replaced by the focused `books/tests/` package

---

### Task 1: Catalog and Physical-Copy Domain

**Files:**
- Delete: `books/tests.py`
- Create: `books/tests/__init__.py`
- Create: `books/tests/test_models.py`
- Modify: `books/models.py`
- Modify: `books/admin.py`
- Create: `books/migrations/0001_phase_3_books.py`

**Interfaces:**
- Produces: `normalize_isbn(value: str | None) -> str`
- Produces: `validate_isbn(value: str) -> None`
- Produces: `Book`
- Produces: `BookCopy` and `BookCopy.Condition`
- Consumes: `settings.AUTH_USER_MODEL`

- [ ] **Step 1: Replace the placeholder test module with a test package**

Delete `books/tests.py`, create empty `books/tests/__init__.py`, and create `books/tests/test_models.py` with failing tests for ISBN helpers before the helpers exist:

```python
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from books.models import normalize_isbn, validate_isbn


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
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_models.IsbnTests --verbosity 2
```

Expected: import failure because `normalize_isbn` and `validate_isbn` do not exist.

- [ ] **Step 3: Implement ISBN normalization and checksum validation**

Add to `books/models.py`:

```python
import re

from django.core.exceptions import ValidationError


def normalize_isbn(value: str | None) -> str:
    return re.sub(r"[-\s]", "", value or "").upper()


def validate_isbn(value: str) -> None:
    value = normalize_isbn(value)
    valid = False

    if len(value) == 10 and value[:9].isdigit() and (
        value[9].isdigit() or value[9] == "X"
    ):
        total = sum((10 - index) * int(char) for index, char in enumerate(value[:9]))
        total += 10 if value[9] == "X" else int(value[9])
        valid = total % 11 == 0
    elif len(value) == 13 and value.isdigit():
        total = sum(
            int(char) * (1 if index % 2 == 0 else 3)
            for index, char in enumerate(value[:12])
        )
        valid = (10 - total % 10) % 10 == int(value[12])

    if not valid:
        raise ValidationError("Masukkan ISBN-10 atau ISBN-13 yang valid.")
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_models.IsbnTests --verbosity 2
```

Expected: four tests pass.

- [ ] **Step 5: Add failing model tests**

Extend `books/tests/test_models.py` with tests proving:

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from books.models import Book, BookCopy


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
```

Also test `Book.full_clean()` rejects an invalid ISBN and an `ftp://` cover, accepts `http://` and `https://`, `condition_note.max_length == 140`, and the database condition constraint rejects an unknown value.

- [ ] **Step 6: Implement the models minimally**

Replace `books/models.py` with the ISBN helpers plus:

```python
from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q


class Book(models.Model):
    title = models.CharField(max_length=255)
    authors = models.CharField(max_length=500)
    isbn = models.CharField(max_length=17, blank=True, null=True)
    language = models.CharField(max_length=100)
    cover_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title", "authors", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("isbn",),
                condition=Q(isbn__isnull=False),
                name="books_book_isbn_unique",
            ),
            models.CheckConstraint(
                condition=Q(isbn__isnull=True) | ~Q(isbn=""),
                name="books_book_isbn_not_empty",
            ),
        ]

    def clean(self):
        super().clean()
        self.isbn = normalize_isbn(self.isbn) or None
        if self.isbn:
            validate_isbn(self.isbn)
        if self.cover_url:
            URLValidator(schemes=("http", "https"))(self.cover_url)

    def save(self, *args, **kwargs):
        self.isbn = normalize_isbn(self.isbn) or None
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} — {self.authors}"


class BookCopy(models.Model):
    class Condition(models.TextChoices):
        LIKE_NEW = "like_new", "Seperti Baru"
        VERY_GOOD = "very_good", "Sangat Bagus"
        GOOD = "good", "Masih Bagus"
        FAIR = "fair", "Cukup Bagus"
        BAD = "bad", "Sudah Buruk"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="book_copies",
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.PROTECT,
        related_name="copies",
    )
    condition = models.CharField(max_length=20, choices=Condition.choices)
    condition_note = models.CharField(max_length=140, blank=True)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(condition__in=Condition.values),
                name="books_bookcopy_condition_valid",
            )
        ]

    def __str__(self):
        return f"{self.book} milik {self.owner}"
```

Keep the URL-scheme assertion in model tests because Django's default `URLField` also accepts FTP unless explicitly restricted.

- [ ] **Step 7: Generate and inspect the initial migration**

Run:

```bash
.venv/bin/python manage.py makemigrations books --name phase_3_books
.venv/bin/python manage.py sqlmigrate books 0001
```

Expected: `books/migrations/0001_phase_3_books.py` creates both tables, the conditional ISBN uniqueness constraint, the nonempty ISBN constraint, and the condition constraint. It depends on `settings.AUTH_USER_MODEL`.

- [ ] **Step 8: Register both models in Django Admin**

Use focused admin classes in `books/admin.py`:

```python
from django.contrib import admin

from .models import Book, BookCopy


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "authors", "isbn", "language")
    search_fields = ("title", "authors", "isbn")


@admin.register(BookCopy)
class BookCopyAdmin(admin.ModelAdmin):
    list_display = ("book", "owner", "condition", "is_available")
    list_filter = ("condition", "is_available")
    search_fields = ("book__title", "book__authors", "book__isbn", "owner__email")
    list_select_related = ("book", "owner")
```

Add a small admin test asserting these registrations and configured search/filter fields.

- [ ] **Step 9: Run domain checks**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_models --verbosity 2
.venv/bin/python manage.py migrate
.venv/bin/python manage.py makemigrations --check
.venv/bin/python manage.py check
```

Expected: all tests and checks pass; no migration drift remains.

- [ ] **Step 10: Commit the domain layer**

```bash
git add books/models.py books/admin.py books/migrations/0001_phase_3_books.py \
  books/tests/__init__.py books/tests/test_models.py
git add -u books/tests.py
git commit -m "Add book catalog and copy models"
```

---

### Task 2: Private Lemari and Owner-Only Copy Management

**Files:**
- Create: `books/forms.py`
- Create: `books/urls.py`
- Modify: `books/views.py`
- Modify: `config/urls.py`
- Create: `templates/books/shelf.html`
- Create: `templates/books/copy_form.html`
- Create: `templates/books/copy_confirm_delete.html`
- Modify: `templates/base.html`
- Modify: `static/css/sarangbuku.css`
- Create: `books/tests/test_shelf.py`

**Interfaces:**
- Consumes: `BookCopy`
- Produces: `BookCopyForm`
- Produces routes: `books:shelf`, `books:copy_edit`, `books:copy_delete`
- Produces views: `shelf(request)`, `copy_edit(request, pk)`, `copy_delete(request, pk)`

- [ ] **Step 1: Write failing authentication, privacy, and display tests**

Create `books/tests/test_shelf.py`. Use two users and two copies. Cover at least:

```python
class ShelfTests(TestCase):
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
```

Also assert the empty state contains `Tambah`, covers use external URLs or a placeholder, and the page shows authors, language, ISBN, and condition note.

- [ ] **Step 2: Run the shelf tests and verify they fail**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_shelf --verbosity 2
```

Expected: failures because URLs, views, forms, and templates do not exist.

- [ ] **Step 3: Add the copy form and routes**

Create `books/forms.py`:

```python
from django import forms

from .models import BookCopy


class BookCopyForm(forms.ModelForm):
    class Meta:
        model = BookCopy
        fields = ("condition", "condition_note", "is_available")
        labels = {
            "condition": "Kondisi",
            "condition_note": "Catatan kondisi",
            "is_available": "Tersedia untuk ditukar",
        }
        help_texts = {
            "condition_note": "Opsional, maksimal 140 karakter.",
        }
        widgets = {
            "condition_note": forms.Textarea(attrs={"rows": 3}),
        }
```

Create `books/urls.py`:

```python
from django.urls import path

from . import views

app_name = "books"

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("salinan/<int:pk>/ubah/", views.copy_edit, name="copy_edit"),
    path("salinan/<int:pk>/hapus/", views.copy_delete, name="copy_delete"),
]
```

Mount it in `config/urls.py`:

```python
path("buku/", include("books.urls")),
```

- [ ] **Step 4: Implement Lemari, edit, and delete views**

Add to `books/views.py`:

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import BookCopyForm
from .models import BookCopy


@login_required
def shelf(request):
    copies = BookCopy.objects.filter(owner=request.user).select_related("book")
    return render(request, "books/shelf.html", {"copies": copies})


@login_required
def copy_edit(request, pk):
    copy = get_object_or_404(BookCopy, pk=pk, owner=request.user)
    form = BookCopyForm(request.POST or None, instance=copy)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Bukumu sudah diperbarui.")
        return redirect("books:shelf")
    return render(request, "books/copy_form.html", {"copy": copy, "form": form})


@login_required
def copy_delete(request, pk):
    copy = get_object_or_404(BookCopy, pk=pk, owner=request.user)
    if request.method == "POST":
        copy.delete()
        messages.success(request, "Buku sudah dihapus dari Lemari.")
        return redirect("books:shelf")
    return render(request, "books/copy_confirm_delete.html", {"copy": copy})
```

Do not make deletion a GET mutation. The GET route renders only the confirmation page.

- [ ] **Step 5: Build minimal accessible templates**

Create `templates/books/shelf.html` extending `base.html`. It must:

- use one `<h1>Lemari</h1>`;
- provide a `Tambah` action;
- show every owned copy in a Bootstrap card grid;
- render `copy.get_condition_display`;
- render `Tersedia` or `Tidak tersedia` as text, not color alone;
- use `book.cover_url` when present and a visible placeholder otherwise;
- link only to the signed-in owner's edit/delete routes;
- show a conversational empty state.

Create `templates/books/copy_form.html` with the same accessible error-summary pattern as `templates/accounts/profile.html`. It edits only condition, note, and availability.

Create `templates/books/copy_confirm_delete.html` with a POST form, CSRF token, `Hapus dari Lemari`, and a cancel link back to `books:shelf`.

- [ ] **Step 6: Add authenticated navigation and minimal CSS**

In `templates/base.html`, add only the authenticated `Lemari` link in this task. Task 3 adds `Tambah` after `books:add` exists. Do not render a dead link.

Add only reusable presentation needed by the templates to `static/css/sarangbuku.css`, for example:

```css
.sb-book-cover {
  aspect-ratio: 2 / 3;
  object-fit: cover;
  width: 100%;
}

.sb-book-cover-placeholder {
  align-items: center;
  aspect-ratio: 2 / 3;
  display: flex;
  justify-content: center;
}
```

Use Bootstrap for grid, spacing, badges, buttons, and cards rather than custom equivalents.

- [ ] **Step 7: Add failing owner-only edit and deletion tests, then make them pass**

Test:

- another user receives 404 for edit GET, edit POST, delete GET, and delete POST;
- edit changes condition, note, and availability but cannot change `book` or `owner`;
- delete GET preserves the copy;
- delete POST removes the `BookCopy` but preserves `Book`;
- anonymous mutations redirect to login;
- navigation shows `Lemari` only when signed in.

Run:

```bash
.venv/bin/python manage.py test books.tests.test_shelf --verbosity 2
.venv/bin/python manage.py check
```

Expected: all Lemari tests and Django checks pass.

- [ ] **Step 8: Commit Lemari management**

```bash
git add books/forms.py books/urls.py books/views.py config/urls.py \
  templates/books/shelf.html templates/books/copy_form.html \
  templates/books/copy_confirm_delete.html templates/base.html \
  static/css/sarangbuku.css books/tests/test_shelf.py
git commit -m "Add private Lemari management"
```

---

### Task 3: Local Catalog Search and Existing-Book Entry

**Files:**
- Modify: `books/forms.py`
- Modify: `books/urls.py`
- Modify: `books/views.py`
- Create: `templates/books/add.html`
- Modify: `templates/books/copy_form.html`
- Modify: `templates/base.html`
- Modify: `templates/accounts/profile.html`
- Create: `books/tests/test_catalog.py`
- Modify: `accounts/tests/test_profile.py`

**Interfaces:**
- Consumes: `Book`, `BookCopy`, `BookCopyForm`
- Produces: `CatalogSearchForm`
- Produces: `_active_zone_redirect(request)`
- Produces routes: `books:add`, `books:copy_create`
- Produces views: `add(request)`, `copy_create(request, book_id)`

- [ ] **Step 1: Write failing local-search and active-Sarang tests**

Create `books/tests/test_catalog.py`. Set up an authenticated user with one active `SwapZone`, local books, and one unrelated user's copy. Test:

```python
class CatalogSearchTests(TestCase):
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
```

Also test anonymous redirects and that users without any selected active Sarang are redirected to `accounts:profile` with `Pilih setidaknya satu Sarang aktif di Profil sebelum menambahkan buku.`

- [ ] **Step 2: Run the catalog tests and verify they fail**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_catalog --verbosity 2
```

Expected: failures because add/search routes do not exist.

- [ ] **Step 3: Implement the search form**

Add to `books/forms.py`:

```python
class CatalogSearchForm(forms.Form):
    q = forms.CharField(
        label="ISBN, judul, atau penulis",
        max_length=255,
        error_messages={"required": "Masukkan ISBN, judul, atau penulis."},
    )

    def clean_q(self):
        value = self.cleaned_data["q"].strip()
        if not value:
            raise forms.ValidationError("Masukkan ISBN, judul, atau penulis.")
        return value
```

- [ ] **Step 4: Add the active-Sarang guard and local search**

Add a private helper to `books/views.py`:

```python
def _active_zone_redirect(request):
    if request.user.swap_zones.filter(is_active=True).exists():
        return None
    messages.error(
        request,
        "Pilih setidaknya satu Sarang aktif di Profil sebelum menambahkan buku.",
    )
    return redirect("accounts:profile")
```

Implement `add(request)` as GET-only application behavior:

```python
@login_required
def add(request):
    if response := _active_zone_redirect(request):
        return response

    form = CatalogSearchForm(request.GET or None)
    books = Book.objects.none()
    if form.is_valid():
        query = form.cleaned_data["q"]
        normalized = normalize_isbn(query)
        predicate = Q(title__icontains=query) | Q(authors__icontains=query)
        if normalized:
            predicate |= Q(isbn=normalized)
        books = Book.objects.filter(predicate).order_by("title", "authors", "pk")[:25]

    return render(
        request,
        "books/add.html",
        {"form": form, "books": books},
    )
```

Import `Q`, `Book`, `CatalogSearchForm`, and `normalize_isbn`. Do not call Open Library here.

- [ ] **Step 5: Add local-copy creation**

Extend `books/urls.py`:

```python
path("tambah/", views.add, name="add"),
path("tambah/<int:book_id>/", views.copy_create, name="copy_create"),
```

Implement:

```python
@login_required
def copy_create(request, book_id):
    if response := _active_zone_redirect(request):
        return response

    book = get_object_or_404(Book, pk=book_id)
    form = BookCopyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        copy = form.save(commit=False)
        copy.owner = request.user
        copy.book = book
        copy.save()
        messages.success(request, "Buku sudah ditambahkan ke Lemari.")
        return redirect("books:shelf")
    return render(
        request,
        "books/copy_form.html",
        {"book": book, "form": form},
    )
```

- [ ] **Step 6: Build the search/result page**

Create `templates/books/add.html` extending `base.html`. Include:

- `<h1>Tambah</h1>`;
- a labeled GET search form;
- local result cards with title, authors, language, ISBN, and cover/placeholder;
- a `Pilih buku ini` link to `books:copy_create`;
- a manual-entry link whose route will be added in Task 4;
- an Open Library fallback form whose route will be added in Task 5;
- no owner identity or copy count.

Do not render dead links. Add the manual and external actions in their own tasks when their routes exist.

- [ ] **Step 7: Activate profile and navigation entry points**

Update `templates/base.html` so authenticated navigation shows:

- `Lemari` -> `books:shelf`
- `Tambah` -> `books:add`
- `Profil` -> `accounts:profile`
- existing POST `Keluar`

Update `templates/accounts/profile.html` by replacing the unavailable `Tambahkan Buku` card with an active `Tambah` card linking to `books:add`. Keep the explanation that a Sarang must be selected first.

Update `accounts/tests/test_profile.py` to replace assertions for the disabled `Belum tersedia` button with assertions for the `Tambah` link and `books:add` URL.

- [ ] **Step 8: Add creation and boundary tests**

Test:

- selecting a local result creates a `BookCopy`, not a second `Book`;
- successful POST redirects to `books:shelf` and shows the success message;
- invalid condition/note preserves errors and creates nothing;
- a direct `copy_create` request without an active selected Sarang redirects without writes;
- results are capped at 25 and ordered deterministically;
- navigation and profile use exactly `Lemari` and `Tambah`;
- local search does not invoke any external client.

Run:

```bash
.venv/bin/python manage.py test \
  books.tests.test_catalog \
  accounts.tests.test_profile \
  --verbosity 2
.venv/bin/python manage.py check
```

Expected: all targeted tests and checks pass.

- [ ] **Step 9: Commit local catalog entry**

```bash
git add books/forms.py books/urls.py books/views.py \
  templates/books/add.html templates/books/copy_form.html \
  templates/base.html templates/accounts/profile.html \
  books/tests/test_catalog.py accounts/tests/test_profile.py
git commit -m "Add local catalog book entry"
```

---

### Task 4: Atomic Manual Catalog and Copy Entry

**Files:**
- Create: `books/services.py`
- Modify: `books/forms.py`
- Modify: `books/urls.py`
- Modify: `books/views.py`
- Create: `templates/books/manual_form.html`
- Modify: `templates/books/add.html`
- Create: `books/tests/test_manual_entry.py`

**Interfaces:**
- Consumes: `Book`, `BookCopy`, `normalize_isbn`, `validate_isbn`
- Produces: `ManualBookCopyForm`
- Produces: `create_book_copy(*, owner, book_data, copy_data) -> BookCopy`
- Produces route: `books:manual_create`
- Produces view: `manual_create(request)`

- [ ] **Step 1: Write failing manual-entry tests**

Create `books/tests/test_manual_entry.py` with an authenticated user who has an active selected Sarang. Define valid data:

```python
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
```

Test that a POST creates one normalized `Book`, one owned `BookCopy`, and redirects to `books:shelf`. Also test:

- invalid ISBN checksum;
- `ftp://` cover rejection;
- 141-character note rejection;
- missing title, authors, language, or condition;
- safe values remain visible after validation failure;
- users without an active Sarang create nothing;
- anonymous users are redirected.

- [ ] **Step 2: Run the manual-entry tests and verify they fail**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_manual_entry --verbosity 2
```

Expected: failures because form, service, route, view, and template do not exist.

- [ ] **Step 3: Implement the combined form**

Add to `books/forms.py`:

```python
from django.core.validators import URLValidator

from .models import Book, BookCopy, normalize_isbn, validate_isbn


class ManualBookCopyForm(forms.Form):
    title = forms.CharField(label="Judul", max_length=255)
    authors = forms.CharField(label="Penulis", max_length=500)
    isbn = forms.CharField(label="ISBN", max_length=17, required=False)
    language = forms.CharField(label="Bahasa", max_length=100)
    cover_url = forms.URLField(
        label="URL sampul",
        max_length=500,
        required=False,
        validators=(URLValidator(schemes=("http", "https")),),
    )
    condition = forms.ChoiceField(
        label="Kondisi", choices=BookCopy.Condition.choices
    )
    condition_note = forms.CharField(
        label="Catatan kondisi",
        max_length=140,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Opsional, maksimal 140 karakter.",
    )
    is_available = forms.BooleanField(
        label="Tersedia untuk ditukar", required=False, initial=True
    )

    def clean_isbn(self):
        isbn = normalize_isbn(self.cleaned_data["isbn"])
        if isbn:
            validate_isbn(isbn)
        return isbn or None

    def save(self, *, owner):
        from .services import create_book_copy

        book_fields = ("title", "authors", "isbn", "language", "cover_url")
        copy_fields = ("condition", "condition_note", "is_available")
        return create_book_copy(
            owner=owner,
            book_data={name: self.cleaned_data[name] for name in book_fields},
            copy_data={name: self.cleaned_data[name] for name in copy_fields},
        )
```

Keep the service import inside `save()` to avoid a forms/services import cycle.

- [ ] **Step 4: Implement atomic ISBN reuse**

Create `books/services.py`:

```python
from django.db import transaction

from .models import Book, BookCopy, normalize_isbn


@transaction.atomic
def create_book_copy(*, owner, book_data, copy_data):
    book_data = dict(book_data)
    isbn = normalize_isbn(book_data.pop("isbn", None)) or None

    if isbn:
        book, _ = Book.objects.get_or_create(
            isbn=isbn,
            defaults=book_data,
        )
    else:
        book = Book.objects.create(isbn=None, **book_data)

    return BookCopy.objects.create(
        owner=owner,
        book=book,
        **copy_data,
    )
```

Existing local metadata remains authoritative when an ISBN already exists. Do not overwrite it with manual or external values.

- [ ] **Step 5: Add manual route, view, and template**

Extend `books/urls.py`:

```python
path("tambah/manual/", views.manual_create, name="manual_create"),
```

Implement `manual_create(request)` with `@login_required`, `_active_zone_redirect`, `ManualBookCopyForm(request.POST or None, initial=request.GET or None)`, and this success behavior:

```python
if request.method == "POST" and form.is_valid():
    form.save(owner=request.user)
    messages.success(request, "Buku sudah ditambahkan ke Lemari.")
    return redirect("books:shelf")
```

Render `templates/books/manual_form.html` with one visible error summary, labels, help text, CSRF token, `Simpan ke Lemari`, and a cancel link to `books:add`.

Add a working `Masukkan manual` link to `templates/books/add.html`.

- [ ] **Step 6: Test ISBN reuse and transactional rollback**

Add tests proving:

```python
def test_existing_isbn_reuses_book_without_overwriting_metadata(self):
    existing = Book.objects.create(
        title="Judul lokal",
        authors="Penulis lokal",
        isbn="9780140328721",
        language="Indonesia",
    )
    # POST conflicting metadata with the formatted same ISBN.
    # Assert one Book remains, the copy uses `existing`, and metadata is unchanged.


def test_copy_failure_rolls_back_new_book(self):
    with patch("books.services.BookCopy.objects.create", side_effect=RuntimeError):
        with self.assertRaises(RuntimeError):
            self.form.save(owner=self.user)
    self.assertFalse(Book.objects.filter(title="Matilda").exists())
```

Also prove two no-ISBN submissions create distinct `Book` records.

- [ ] **Step 7: Add an independent PostgreSQL concurrency test**

Use `TransactionTestCase`, `ThreadPoolExecutor`, `Barrier`, and `close_old_connections()` in `ConcurrentIsbnCreationTests`. Two workers submit the same normalized ISBN for the same user. Each worker must obtain fresh model instances inside its own connection.

Assert after both futures finish:

```python
self.assertEqual(Book.objects.filter(isbn="9780140328721").count(), 1)
self.assertEqual(BookCopy.objects.filter(book__isbn="9780140328721").count(), 2)
```

If the first implementation exposes a unique-key race, fix it inside `create_book_copy()` with a nested `transaction.atomic()` savepoint around `Book.objects.create()` and retrieve the winning row after catching only the expected `IntegrityError`. Do not catch broad errors or continue inside a broken transaction.

- [ ] **Step 8: Run manual-entry and concurrency checks**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_manual_entry --verbosity 2
.venv/bin/python manage.py test \
  books.tests.test_manual_entry.ConcurrentIsbnCreationTests \
  --verbosity 2
.venv/bin/python manage.py check
```

Expected: all tests pass against PostgreSQL.

- [ ] **Step 9: Commit manual entry**

```bash
git add books/services.py books/forms.py books/urls.py books/views.py \
  templates/books/manual_form.html templates/books/add.html \
  books/tests/test_manual_entry.py
git commit -m "Add atomic manual book entry"
```

---

### Task 5: Explicit Open Library Fallback

**Files:**
- Create: `books/open_library.py`
- Modify: `books/forms.py`
- Modify: `books/urls.py`
- Modify: `books/views.py`
- Modify: `templates/books/add.html`
- Create: `books/tests/test_open_library.py`

**Interfaces:**
- Consumes: `normalize_isbn`, `validate_isbn`, `ManualBookCopyForm`
- Produces: `OpenLibraryError`
- Produces: `search_open_library(query: str, *, timeout: float = 5.0) -> list[dict[str, str]]`
- Produces route: `books:open_library`
- Produces view: `open_library_search(request)`

- [ ] **Step 1: Write failing Open Library client tests without live network calls**

Create `books/tests/test_open_library.py` and patch `books.open_library.urlopen`. Use a context-manager fake response containing encoded JSON. Test:

```python
class OpenLibraryClientTests(SimpleTestCase):
    @patch("books.open_library.urlopen")
    def test_text_search_maps_best_edition(self, mocked_urlopen):
        # Return one work with editions.docs containing title, author_name,
        # isbn, language, and cover_i.
        results = search_open_library("Matilda")
        self.assertEqual(results[0]["title"], "Matilda")
        self.assertEqual(results[0]["authors"], "Roald Dahl")
        self.assertEqual(results[0]["isbn"], "9780140328721")
        self.assertEqual(
            results[0]["cover_url"],
            "https://covers.openlibrary.org/b/id/123-M.jpg",
        )
```

Also inspect the generated `Request` and assert:

- URL is `https://openlibrary.org/search.json`;
- text uses `q=...`;
- a valid ISBN query uses `isbn=...` and preserves that exact ISBN;
- `limit=10` and requested `fields` are present;
- identifying `User-Agent` is present;
- `urlopen(..., timeout=5.0)` is used.

- [ ] **Step 2: Add failing malformed-response and failure tests**

Mock and assert one `OpenLibraryError` for:

- `TimeoutError`;
- `HTTPError`;
- `URLError`;
- non-200 status;
- invalid JSON;
- a root value that is not a mapping;
- `docs` that is not a list;
- a payload with no usable title.

Also test:

- result count never exceeds ten;
- ISBN-13 is preferred over ISBN-10 for text results;
- malformed optional ISBN and cover values become blank;
- missing authors become `Penulis tidak diketahui`;
- missing language becomes `Bahasa tidak diketahui`;
- strings longer than model limits are not returned as usable results.

- [ ] **Step 3: Run client tests and verify they fail**

Run:

```bash
.venv/bin/python manage.py test \
  books.tests.test_open_library.OpenLibraryClientTests \
  --verbosity 2
```

Expected: import failure because `books.open_library` does not exist.

- [ ] **Step 4: Implement the bounded standard-library client**

Create `books/open_library.py` with:

```python
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError

from .models import normalize_isbn, validate_isbn

SEARCH_URL = "https://openlibrary.org/search.json"
COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
USER_AGENT = "SarangBuku/1.0 (https://sarangbuku.id; noreply@sarangbuku.id)"
RESULT_LIMIT = 10
FIELDS = (
    "title",
    "author_name",
    "isbn",
    "language",
    "cover_i",
    "editions",
    "editions.title",
    "editions.author_name",
    "editions.isbn",
    "editions.language",
    "editions.cover_i",
)


class OpenLibraryError(Exception):
    pass
```

Implement private helpers that:

- identify a query as ISBN only when `validate_isbn(normalize_isbn(query))` succeeds;
- choose the first mapping in `editions.docs`, falling back to the work mapping;
- select a valid ISBN-13 before ISBN-10;
- join author names with `, `;
- choose the first language string;
- accept only positive integer `cover_i` values;
- skip results with no nonblank title;
- enforce model field lengths before returning data.

Implement `search_open_library()` using `Request`, `urlopen`, `json.load`, and a result slice of `RESULT_LIMIT`. Catch only `TimeoutError`, `HTTPError`, `URLError`, JSON decoding errors, Unicode errors, and malformed payload errors, then raise:

```python
OpenLibraryError(
    "Open Library sedang tidak dapat dihubungi. Coba lagi atau masukkan buku secara manual."
)
```

Do not expose exception details in the user-facing message.

- [ ] **Step 5: Run the client tests and make them pass**

Run:

```bash
.venv/bin/python manage.py test \
  books.tests.test_open_library.OpenLibraryClientTests \
  --verbosity 2
```

Expected: every test passes with `urlopen` mocked.

- [ ] **Step 6: Add failing external-search view tests**

Test:

- anonymous users redirect to login;
- users without an active Sarang redirect to Profil;
- the view calls `search_open_library()` only after explicit submission;
- results render metadata and a working `Tambah buku ini` link;
- the link points to `books:manual_create` with only `title`, `authors`, `isbn`, `language`, and `cover_url` query parameters;
- service failures show the conversational error while retaining local search and manual entry actions;
- no database row is created by rendering or selecting an external result;
- a final POST through `manual_create` revalidates tampered query-prefilled values.

- [ ] **Step 7: Add the external route and view**

Extend `books/urls.py`:

```python
path(
    "tambah/open-library/",
    views.open_library_search,
    name="open_library",
),
```

Implement a GET view using `CatalogSearchForm`, `_active_zone_redirect`, and `search_open_library`. Pass `external_results` and any `OpenLibraryError` text to `books/add.html`. Never call the client from `add()`.

Build each result's manual-entry query string with `urllib.parse.urlencode()` over the five-field whitelist. Do not pass arbitrary response keys through to the form.

- [ ] **Step 8: Add the explicit fallback UI**

Update `templates/books/add.html` so a valid current query offers:

- `Cari di Open Library`, submitting the same `q` to `books:open_library`;
- `Masukkan manual`, linking to `books:manual_create`;
- external result cards with `Tambah buku ini` links to the prefilled manual form.

The page must keep local and manual actions visible after external failure. Avoid HTMX, JavaScript fetches, or automatic requests.

- [ ] **Step 9: Run all Open Library and catalog tests**

Run:

```bash
.venv/bin/python manage.py test \
  books.tests.test_open_library \
  books.tests.test_catalog \
  books.tests.test_manual_entry \
  --verbosity 2
.venv/bin/python manage.py check
```

Expected: all HTTP calls are mocked; tests pass without internet access.

- [ ] **Step 10: Commit Open Library fallback**

```bash
git add books/open_library.py books/forms.py books/urls.py books/views.py \
  templates/books/add.html books/tests/test_open_library.py
git commit -m "Add Open Library catalog fallback"
```

---

### Task 6: Full Verification and Browser QA

**Files:**
- No implementation files should change unless verification reveals a defect.

**Interfaces:**
- Consumes: all Phase 3 behavior
- Produces: fresh evidence that Phase 3 and earlier phases work together

- [ ] **Step 1: Run the complete automated verification**

Run:

```bash
cd /Users/yosef/Projects/sarangbuku
.venv/bin/python manage.py test --verbosity 2
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python -m pip check
git diff --check
```

Expected: all tests and checks pass without migration drift, dependency errors, or whitespace errors.

- [ ] **Step 2: Run the PostgreSQL ISBN race test independently**

Run:

```bash
.venv/bin/python manage.py test \
  books.tests.test_manual_entry.ConcurrentIsbnCreationTests \
  --verbosity 2
```

Expected: one `Book`, two `BookCopy` rows, and no uncaught database error.

- [ ] **Step 3: Run one separate live Open Library smoke check**

This check is intentionally outside the deterministic test suite:

```bash
.venv/bin/python manage.py shell -c \
  'from books.open_library import search_open_library; results = search_open_library("9780140328721"); print(len(results), results[0]["title"] if results else "no result")'
```

Expected: at least one usable result. If the network or service is unavailable, record that fact without treating deterministic application tests as failed.

- [ ] **Step 4: Run browser QA at mobile and desktop widths**

Start the server:

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

At 390 px and 1280 px verify:

1. Anonymous requests to `Lemari` and `Tambah` redirect to login.
2. A signed-in user without an active selected Sarang is redirected to Profil.
3. Navigation and profile use exactly `Lemari` and `Tambah`.
4. Local title, author, and formatted ISBN searches work without an external request.
5. Existing-local, manual, and Open Library paths each create a copy and finish in `Lemari`.
6. Invalid ISBN, cover URL, and overlong condition note preserve safe values and identify their fields.
7. Multiple copies of one book appear independently.
8. Unavailable copies remain visible to their owner.
9. Another user receives 404 when guessing edit or delete URLs.
10. Deletion requires a confirmation page and POST.
11. Conditions display exactly `Seperti Baru`, `Sangat Bagus`, `Masih Bagus`, `Cukup Bagus`, and `Sudah Buruk`.
12. External covers and placeholders retain usable dimensions without horizontal overflow.
13. Labels, error summaries, keyboard navigation, focus visibility, contrast, and mobile layout remain usable.
14. No owner identity, email, copy count, discovery, wishlist, or Minat UI appears.
15. Browser console, page errors, and actionable network requests remain clean.

Use controlled Open Library responses for repeatable browser assertions when needed. Keep any live-service smoke result separate.

- [ ] **Step 5: Verify repository safety and focused commits**

Run:

```bash
git status --short
git diff --check
git log --oneline --decorate -8
```

Expected: no generated or QA files remain, and Phase 3 is represented by focused domain, Lemari, local/manual entry, and Open Library commits.

## Plan Self-Review Checklist

- `Book` and `BookCopy` remain distinct: Task 1.
- Multiple copies per owner remain valid: Task 1.
- All five canonical conditions and Indonesian labels are exact: Tasks 1 and 6.
- Local search precedes explicit external lookup: Tasks 3 and 5.
- Manual entry remains available through external failure: Tasks 4 and 5.
- Open Library data is copied locally and never required by `Lemari`: Tasks 4 and 5.
- Copy creation is atomic and reuses normalized ISBN safely: Task 4.
- Active Sarang and owner-only access are enforced server-side: Tasks 2 through 5.
- Cover uploads, wishlist, discovery, Minat, reservations, and history are absent: global constraints and every task.
- Accessibility, mobile browser QA, migration drift, PostgreSQL concurrency, and full regression checks are included: Task 6.
