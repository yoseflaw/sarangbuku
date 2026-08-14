# Phase 4 Wishlist and Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authenticated members privately maintain `Daftar Minat` and discover eligible anonymous copies from active members in a shared active Sarang.

**Architecture:** Keep the feature inside the existing `books` app. Persist only the user-to-catalog wishlist relation; compute discovery from local `BookCopy` data through one shared eligibility queryset consumed by both list and detail views. Use Django forms, ORM, pagination, templates, POST/CSRF mutations, and Bootstrap without new dependencies.

**Tech Stack:** Django 5.2, PostgreSQL, Django Templates, Bootstrap, Django test framework

## Global Constraints

- The source of truth is `references/specs/2026-08-14-phase-4-wishlist-discovery-design.md` and `references/mvp/MVP_SPEC.md`.
- Keep Phase 4 inside the existing `books` app; do not create another Django app.
- Wishlist additions use existing local `Book` records only; do not query Open Library or offer manual entry from `Daftar Minat`.
- Do not add `Minat` creation, acceptance, rejection, withdrawal, messages, handover behavior, notifications, or an inactive future CTA.
- Discovery must show only available copies owned by active users other than the viewer when owner and viewer share at least one active Sarang.
- List and detail views must both consume `discoverable_copies(*, viewer)`; do not duplicate eligibility logic.
- Never reveal owner display name, email, contact information, schedule, precise location, other copies, or a link that identifies the owner.
- The discovery UI label is exactly `Temukan`; omit `Buku` in Phase 4 copy wherever context makes the object obvious.
- User-facing copy must be natural Indonesian following EYD; project code and documentation remain English.
- All mutations are authenticated POST requests protected by Django CSRF; validate any redirect destination as same-host.
- Members without an active Sarang redirect to `Profil`.
- Preserve mobile usability, visible labels, keyboard access, focus visibility, and adequate contrast.
- Add no dependency, cache, search index, JavaScript frontend, or speculative abstraction.
- Follow test-driven development: run each named test red before production code, then green before committing.

## Locked Interfaces and Routes

```python
# books.services
def discoverable_copies(*, viewer):
    """Return a QuerySet[BookCopy] eligible for this viewer."""

# books.views
def _local_catalog_results(query: str):
    """Return at most 25 deterministically ordered local Book matches."""

def _post_redirect(request, fallback: str):
    """Redirect to a same-host POSTed next value or a named fallback route."""

# books.forms
class DiscoveryFilterForm(forms.Form):
    def __init__(self, *args, viewer, **kwargs):
        """Restrict Sarang choices to the viewer's active Sarang."""
```

```python
# books.urls
path("daftar-minat/", views.wishlist, name="wishlist")
path("daftar-minat/tambah/<int:book_id>/", views.wishlist_add, name="wishlist_add")
path("daftar-minat/hapus/<int:book_id>/", views.wishlist_remove, name="wishlist_remove")
path("temukan/", views.discover, name="discover")
path("temukan/<int:pk>/", views.discovery_detail, name="discovery_detail")
```

Discovery uses 24 results per page ordered by `book__title`, `book__authors`, then `pk`. Local catalog search remains capped at 25 results ordered by `title`, `authors`, then `pk`.

## File Responsibility Map

- `books/models.py`: `WishlistItem` persistence and uniqueness.
- `books/migrations/0002_wishlistitem.py`: schema for `WishlistItem`.
- `books/admin.py`: pilot support visibility for wishlist rows.
- `books/services.py`: shared discovery eligibility and privacy queryset.
- `books/forms.py`: viewer-scoped discovery filter validation.
- `books/views.py`: wishlist and discovery request flows plus shared local-search and redirect helpers.
- `books/urls.py`: Phase 4 routes.
- `templates/books/wishlist.html`: private list, local search, and add/remove controls.
- `templates/books/discover.html`: validated filters, anonymous result cards, and pagination.
- `templates/books/discovery_detail.html`: anonymous eligible-copy detail.
- `templates/base.html`: authenticated `Temukan` and `Daftar Minat` navigation.
- `books/tests/test_models.py`: wishlist persistence and admin checks.
- `books/tests/test_wishlist.py`: private wishlist flow and mutation security.
- `books/tests/test_discovery.py`: queryset, filter, list, pagination, detail, and privacy checks.

---

### Task 1: Persist Wishlist Items

**Files:**
- Modify: `books/models.py`
- Create: `books/migrations/0002_wishlistitem.py`
- Modify: `books/admin.py`
- Modify: `books/tests/test_models.py`

**Interfaces:**
- Consumes: existing `Book` and `settings.AUTH_USER_MODEL`.
- Produces: `WishlistItem(user, book, created_at)` with related name `wishlist_items` on both foreign keys and unique constraint `books_wishlistitem_user_book_unique`.

- [ ] **Step 1: Write failing model and admin tests**

Extend imports in `books/tests/test_models.py` and add these tests:

```python
from books.models import Book, BookCopy, WishlistItem, normalize_isbn, validate_isbn


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
```

Add to `AdminTests`:

```python
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
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python manage.py test books.tests.test_models.WishlistItemModelTests books.tests.test_models.AdminTests
```

Expected: import failure because `WishlistItem` does not exist.

- [ ] **Step 3: Add the minimal model**

Append to `books/models.py`:

```python
class WishlistItem(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wishlist_items",
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="wishlist_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "book"),
                name="books_wishlistitem_user_book_unique",
            )
        ]

    def __str__(self):
        return f"{self.book} diminati {self.user}"
```

- [ ] **Step 4: Generate and inspect the migration**

Run:

```bash
python manage.py makemigrations books
python manage.py sqlmigrate books 0002
```

Expected: `books/migrations/0002_wishlistitem.py` creates the table, both foreign keys, timestamp, ordering, and named uniqueness constraint. Do not hand-add indexes.

- [ ] **Step 5: Register the model in Admin**

Update `books/admin.py`:

```python
from .models import Book, BookCopy, WishlistItem


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "book_authors", "created_at")
    search_fields = ("user__email", "book__title", "book__authors", "book__isbn")
    list_select_related = ("user", "book")

    @admin.display(description="Penulis", ordering="book__authors")
    def book_authors(self, obj):
        return obj.book.authors
```

Keep the existing `BookAdmin` and `BookCopyAdmin` unchanged.

- [ ] **Step 6: Run focused verification and verify GREEN**

Run:

```bash
python manage.py test books.tests.test_models.WishlistItemModelTests books.tests.test_models.AdminTests
python manage.py makemigrations books --check --dry-run
python manage.py check
```

Expected: all tests pass, no migration changes, and no system-check issues.

- [ ] **Step 7: Commit**

```bash
git add books/models.py books/migrations/0002_wishlistitem.py books/admin.py books/tests/test_models.py
git commit -m "Add wishlist item model"
```

---

### Task 2: Add the Private `Daftar Minat` Flow

**Files:**
- Create: `books/tests/test_wishlist.py`
- Modify: `books/views.py`
- Modify: `books/urls.py`
- Create: `templates/books/wishlist.html`

**Interfaces:**
- Consumes: `WishlistItem`, `CatalogSearchForm`, `normalize_isbn`, and `_active_zone_redirect(request)`.
- Produces: `_local_catalog_results(query)`, `_post_redirect(request, fallback)`, `wishlist(request)`, `wishlist_add(request, book_id)`, and `wishlist_remove(request, book_id)` plus the three locked wishlist routes.

- [ ] **Step 1: Write failing wishlist tests**

Create `books/tests/test_wishlist.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python manage.py test books.tests.test_wishlist
```

Expected: URL reversal failures because the wishlist routes do not exist.

- [ ] **Step 3: Add shared local-search and safe-redirect helpers**

Update imports in `books/views.py`:

```python
from django.db.models import Exists, OuterRef, Q
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Book, BookCopy, WishlistItem, normalize_isbn
```

Add the helpers and make the existing `add()` view call `_local_catalog_results(query)` instead of repeating the query:

```python
def _local_catalog_results(query):
    normalized = normalize_isbn(query)
    predicate = Q(title__icontains=query) | Q(authors__icontains=query)
    if normalized:
        predicate |= Q(isbn=normalized)
    return Book.objects.filter(predicate).order_by("title", "authors", "pk")[:25]


def _post_redirect(request, fallback):
    destination = request.POST.get("next", "")
    if destination and url_has_allowed_host_and_scheme(
        destination,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(destination)
    return redirect(fallback)
```

Change `_active_zone_redirect()` feedback to the context-neutral message:

```python
messages.error(
    request,
    "Pilih setidaknya satu Sarang aktif di Profil untuk melanjutkan.",
)
```

- [ ] **Step 4: Add wishlist views and routes**

Add to `books/views.py`:

```python
@login_required
def wishlist(request):
    if response := _active_zone_redirect(request):
        return response

    form = CatalogSearchForm(request.GET or None)
    books = Book.objects.none()
    if form.is_valid():
        books = _local_catalog_results(form.cleaned_data["q"]).annotate(
            is_wishlisted=Exists(
                WishlistItem.objects.filter(
                    user=request.user,
                    book_id=OuterRef("pk"),
                )
            )
        )

    items = WishlistItem.objects.filter(user=request.user).select_related("book")
    return render(
        request,
        "books/wishlist.html",
        {"form": form, "books": books, "items": items},
    )


@login_required
@require_POST
def wishlist_add(request, book_id):
    if response := _active_zone_redirect(request):
        return response

    book = get_object_or_404(Book, pk=book_id)
    _, created = WishlistItem.objects.get_or_create(user=request.user, book=book)
    if created:
        messages.success(request, "Sudah ditambahkan ke Daftar Minat.")
    else:
        messages.info(request, "Sudah ada di Daftar Minat.")
    return _post_redirect(request, "books:wishlist")


@login_required
@require_POST
def wishlist_remove(request, book_id):
    if response := _active_zone_redirect(request):
        return response

    item = get_object_or_404(
        WishlistItem,
        user=request.user,
        book_id=book_id,
    )
    item.delete()
    messages.success(request, "Sudah dihapus dari Daftar Minat.")
    return _post_redirect(request, "books:wishlist")
```

Add the three locked routes to `books/urls.py` before the generic copy routes.

- [ ] **Step 5: Create the accessible wishlist template**

Create `templates/books/wishlist.html`. It must:

- Extend `base.html` and title the page `Daftar Minat | Sarang Buku`.
- Use one visible `<h1>Daftar Minat</h1>`.
- Render `form.q` with a visible label and field errors.
- Show saved `items` separately from catalog search results.
- POST add/remove controls with `{% csrf_token %}` and `<input type="hidden" name="next" value="{{ request.get_full_path }}">`.
- Show `Belum ada yang disimpan.` when `items` is empty.
- Show `Tidak ada hasil lokal.` only after a valid submitted search with no matches.
- Never render Open Library, manual-entry, owner, or contact actions.
- Use the existing Bootstrap card, responsive grid, cover placeholder, button, and focus patterns from `templates/books/add.html` and `templates/books/shelf.html` without copying business logic into the template.

Use `book.is_wishlisted` to choose between the add and remove forms for search results. Removal always posts `book.pk`, never a caller-supplied user or wishlist-item identifier.

- [ ] **Step 6: Run focused tests and existing catalog regressions**

Run:

```bash
python manage.py test books.tests.test_wishlist
python manage.py test books.tests.test_catalog books.tests.test_shelf
```

Expected: all pass; changing the neutral Sarang message does not break existing book flows.

- [ ] **Step 7: Commit**

```bash
git add books/tests/test_wishlist.py books/views.py books/urls.py templates/books/wishlist.html
git commit -m "Add private Daftar Minat flow"
```

---

### Task 3: Centralize Discovery Eligibility

**Files:**
- Modify: `books/services.py`
- Create: `books/tests/test_discovery.py`

**Interfaces:**
- Consumes: `BookCopy`, `WishlistItem`, `SwapZone`, and a persisted authenticated `viewer`.
- Produces: `discoverable_copies(*, viewer)`, returning eligible distinct copies with `book`, boolean `is_wishlisted`, and `owner.shared_active_zones` already loaded.

- [ ] **Step 1: Write failing eligibility and annotation tests**

Create `books/tests/test_discovery.py` with the shared setup and queryset tests:

```python
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
```

- [ ] **Step 2: Run the queryset tests and verify RED**

Run:

```bash
python manage.py test books.tests.test_discovery.DiscoverableCopiesTests
```

Expected: import failure because `discoverable_copies` does not exist.

- [ ] **Step 3: Implement the single eligibility queryset**

Update `books/services.py` imports and add:

```python
from django.db.models import Exists, OuterRef, Prefetch

from accounts.models import SwapZone

from .models import Book, BookCopy, WishlistItem, normalize_isbn


def discoverable_copies(*, viewer):
    shared_active_zones = SwapZone.objects.filter(
        is_active=True,
        pk__in=viewer.swap_zones.filter(is_active=True).values("pk"),
    )

    return (
        BookCopy.objects.filter(
            is_available=True,
            owner__is_active=True,
            owner__swap_zones__in=shared_active_zones,
        )
        .exclude(owner=viewer)
        .select_related("book", "owner")
        .annotate(
            is_wishlisted=Exists(
                WishlistItem.objects.filter(
                    user=viewer,
                    book_id=OuterRef("book_id"),
                )
            )
        )
        .prefetch_related(
            Prefetch(
                "owner__swap_zones",
                queryset=shared_active_zones,
                to_attr="shared_active_zones",
            )
        )
        .distinct()
    )
```

Before accepting GREEN, inspect the generated SQL with `str(discoverable_copies(viewer=self.viewer).query)` in a Django shell if the relation chain differs from the current model names. The invariant is exact: `shared_active_zones` must be the intersection of the viewer's active Sarang and each result owner's active Sarang. Do not replace this with Python filtering or a second eligibility implementation.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
python manage.py test books.tests.test_discovery.DiscoverableCopiesTests
```

Expected: all four tests pass, including one result despite two shared Sarang.

- [ ] **Step 5: Commit**

```bash
git add books/services.py books/tests/test_discovery.py
git commit -m "Define discoverable copy eligibility"
```

---

### Task 4: Add Filtered and Paginated `Temukan`

**Files:**
- Modify: `books/forms.py`
- Modify: `books/views.py`
- Modify: `books/urls.py`
- Create: `templates/books/discover.html`
- Modify: `templates/base.html`
- Modify: `books/tests/test_discovery.py`

**Interfaces:**
- Consumes: `discoverable_copies(*, viewer)`, `_active_zone_redirect()`, `normalize_isbn`, and the locked wishlist add/remove routes.
- Produces: `DiscoveryFilterForm(*args, viewer, **kwargs)` and `discover(request)` at `books:discover`.

- [ ] **Step 1: Write failing form, list, filter, pagination, and navigation tests**

Append to `books/tests/test_discovery.py` and add imports:

```python
from django.urls import reverse

from books.forms import DiscoveryFilterForm
```

Add:

```python
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
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python manage.py test books.tests.test_discovery.DiscoveryFilterFormTests books.tests.test_discovery.DiscoveryListTests
```

Expected: import or URL reversal failure because the form and route do not exist.

- [ ] **Step 3: Implement the viewer-scoped filter form**

Add `SwapZone` to `books/forms.py` imports and add:

```python
from accounts.models import SwapZone


class DiscoveryFilterForm(forms.Form):
    q = forms.CharField(
        label="Cari",
        max_length=255,
        required=False,
    )
    sarang = forms.ModelChoiceField(
        label="Sarang",
        queryset=SwapZone.objects.none(),
        required=False,
        empty_label="Semua Sarang",
    )
    condition = forms.ChoiceField(
        label="Kondisi",
        choices=(),
        required=False,
    )
    wishlist = forms.BooleanField(
        label="Daftar Minat saja",
        required=False,
    )

    def __init__(self, *args, viewer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sarang"].queryset = viewer.swap_zones.filter(is_active=True)
        self.fields["condition"].choices = [
            ("", "Semua kondisi"),
            *BookCopy.Condition.choices,
        ]

    def clean_q(self):
        return self.cleaned_data["q"].strip()
```

Apply existing Bootstrap form widget classes directly in the field declarations or `__init__`, following current form patterns; keep visible labels.

- [ ] **Step 4: Implement filtering and pagination**

Update `books/views.py` imports:

```python
from django.core.paginator import Paginator

from .forms import BookCopyForm, CatalogSearchForm, DiscoveryFilterForm, ManualBookCopyForm
from .services import discoverable_copies
```

Add:

```python
@login_required
def discover(request):
    if response := _active_zone_redirect(request):
        return response

    form = DiscoveryFilterForm(request.GET or None, viewer=request.user)
    copies = BookCopy.objects.none()
    if not form.is_bound or form.is_valid():
        copies = discoverable_copies(viewer=request.user)
        if form.is_bound:
            query = form.cleaned_data["q"]
            if query:
                normalized = normalize_isbn(query)
                predicate = Q(book__title__icontains=query) | Q(
                    book__authors__icontains=query
                )
                if normalized:
                    predicate |= Q(book__isbn=normalized)
                copies = copies.filter(predicate)
            if sarang := form.cleaned_data["sarang"]:
                copies = copies.filter(owner__swap_zones=sarang)
            if condition := form.cleaned_data["condition"]:
                copies = copies.filter(condition=condition)
            if form.cleaned_data["wishlist"]:
                copies = copies.filter(is_wishlisted=True)

    copies = copies.order_by("book__title", "book__authors", "pk").distinct()
    page_obj = Paginator(copies, 24).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "books/discover.html",
        {
            "form": form,
            "page_obj": page_obj,
            "filter_query": query_params.urlencode(),
        },
    )
```

Add the locked `temukan/` route before `temukan/<int:pk>/` and before generic copy routes.

- [ ] **Step 5: Create the results template and navigation**

Create `templates/books/discover.html`. It must:

- Use title `Temukan | Sarang Buku` and one `<h1>Temukan</h1>`.
- Render all filter labels, controls, and per-field errors in a GET form.
- Render `page_obj` as responsive cards with only approved fields.
- Iterate `copy.owner.shared_active_zones` for shared Sarang without rendering any other owner field.
- Render card content without a detail link in this task; Task 5 adds the route and links only after the real detail view exists.
- Show `Ada di Daftar Minat` when `copy.is_wishlisted` is true.
- POST add/remove forms with CSRF and same-host `next={{ request.get_full_path }}`.
- Show `Tidak ada yang cocok.` only when the bound form is valid and the page is empty; show form errors without a broad unfiltered result list when invalid.
- Render previous/next links with `page=` plus `filter_query`, omitting a dangling ampersand when no filters are active.
- Never render owner identity, owner links, Open Library, manual entry, or `Minat` actions.

Modify authenticated navigation in `templates/base.html` to this order:

```html
<a href="{% url 'books:discover' %}">Temukan</a>
<a href="{% url 'books:shelf' %}">Lemari</a>
<a href="{% url 'books:add' %}">Tambah</a>
<a href="{% url 'books:wishlist' %}">Daftar Minat</a>
<a href="{% url 'accounts:profile' %}">Profil</a>
```

- [ ] **Step 6: Run focused and navigation regressions**

Run:

```bash
python manage.py test books.tests.test_discovery.DiscoveryFilterFormTests books.tests.test_discovery.DiscoveryListTests
python manage.py test books.tests.test_wishlist books.tests.test_shelf books.tests.test_catalog
```

Expected: all pass with no privacy strings in discovery responses.

- [ ] **Step 7: Commit**

```bash
git add books/forms.py books/views.py books/urls.py templates/books/discover.html templates/base.html books/tests/test_discovery.py
git commit -m "Add filtered anonymous discovery"
```

---

### Task 5: Add Anonymous Eligible-Copy Details

**Files:**
- Modify: `books/views.py`
- Modify: `books/urls.py`
- Create: `templates/books/discovery_detail.html`
- Modify: `templates/books/discover.html`
- Modify: `books/tests/test_discovery.py`

**Interfaces:**
- Consumes: `discoverable_copies(*, viewer)`, `_active_zone_redirect()`, and locked wishlist mutations.
- Produces: `discovery_detail(request, pk)` at `books:discovery_detail` with eligibility revalidated on every request.

- [ ] **Step 1: Write failing detail and stale-link privacy tests**

Append to `books/tests/test_discovery.py`:

```python
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
```

- [ ] **Step 2: Run detail tests and verify RED**

Run:

```bash
python manage.py test books.tests.test_discovery.DiscoveryDetailTests
```

Expected: URL reversal failure because `books:discovery_detail` does not exist.

- [ ] **Step 3: Add the detail view and route**

Add to `books/views.py`:

```python
@login_required
def discovery_detail(request, pk):
    if response := _active_zone_redirect(request):
        return response

    copy = get_object_or_404(
        discoverable_copies(viewer=request.user),
        pk=pk,
    )
    return render(request, "books/discovery_detail.html", {"copy": copy})
```

Add to `books/urls.py` immediately after the list route:

```python
path("temukan/<int:pk>/", views.discovery_detail, name="discovery_detail"),
```

- [ ] **Step 4: Create the permitted detail template and link list cards**

Create `templates/books/discovery_detail.html`. It must:

- Use the catalog title in the document title and one visible `<h1>`.
- Render only `copy.book` catalog fields, `copy.get_condition_display`, `copy.condition_note`, and `copy.owner.shared_active_zones`.
- Use the external cover URL through the same safe template pattern as existing book pages, with the existing placeholder otherwise.
- Render a real wishlist add or remove POST form based on `copy.is_wishlisted`, with CSRF and `next={{ request.path }}`.
- Link back to `Temukan`.
- Never render any other owner property, owner URL, other copy query, or `Minat` control.

Update each card in `templates/books/discover.html` to link to:

```django
{% url 'books:discovery_detail' copy.pk %}
```

Keep the link text concise and avoid adding `Buku` where the object is already obvious.

- [ ] **Step 5: Run detail, list, and privacy regressions**

Run:

```bash
python manage.py test books.tests.test_discovery.DiscoveryDetailTests
python manage.py test books.tests.test_discovery
python manage.py test books.tests.test_wishlist
```

Expected: all pass; stale and ineligible detail URLs return 404.

- [ ] **Step 6: Commit**

```bash
git add books/views.py books/urls.py templates/books/discovery_detail.html templates/books/discover.html books/tests/test_discovery.py
git commit -m "Add anonymous discovery details"
```

---

### Task 6: Verify Phase 4 End to End

**Files:**
- Modify only if a demonstrated defect requires it: `static/css/sarangbuku.css`, Phase 4 templates, Phase 4 tests, or affected Python files.
- Do not add speculative CSS, JavaScript, dependencies, or unrelated refactors.

**Interfaces:**
- Consumes: all Phase 4 routes and tests from Tasks 1–5.
- Produces: verified mobile, desktop, accessibility, privacy, migration, and regression evidence.

- [ ] **Step 1: Run the complete automated verification matrix**

Run from the Phase 4 worktree:

```bash
python manage.py test books
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python -m pip check
git diff --check
```

Expected: every command exits 0, the full suite includes all pre-Phase-4 tests, no migration drift exists, and static collection has no error.

- [ ] **Step 2: Start the server with representative local data**

Create disposable users, active and inactive Sarang, local books, eligible and ineligible copies, and wishlist items through Django shell or Admin. Include:

- Two users sharing two active Sarang
- One active unshared Sarang
- One inactive Sarang shared by both users
- One inactive owner
- Available, unavailable, self-owned, and wishlist-matching copies
- At least 25 eligible copies to exercise pagination

Start the development server on an available local port. Do not use external catalog services; Phase 4 reads local data only.

- [ ] **Step 3: Verify the authenticated browser flow at mobile and desktop widths**

At 390×844 and 1280×900, verify:

1. Navigation labels and order are `Temukan`, `Lemari`, `Tambah`, `Daftar Minat`, `Profil`.
2. `Daftar Minat` local search adds one item, duplicate add remains one row, removal works, and no Open Library/manual action appears.
3. `Temukan` defaults to eligible copies and each search/filter combination preserves values.
4. Invalid Sarang and condition values show errors and no broadened results.
5. Pagination keeps active filters.
6. Wishlist badges and add/remove controls update through real POST requests.
7. Detail pages expose only approved fields and show no owner identity, contact data, owner links, other copies, or inactive `Minat` action.
8. Making a copy unavailable, deactivating its owner, or removing the shared Sarang turns its existing detail URL into 404.
9. Anonymous requests redirect to login and a user without an active Sarang redirects to `Profil`.
10. Forms have visible labels, keyboard focus is visible, controls are operable by keyboard, contrast remains adequate, navigation wraps safely, and no horizontal overflow occurs.

Check browser console and page errors at both widths. Treat actionable console, page, or network failures as defects; a benign missing development favicon is not Phase 4 behavior.

- [ ] **Step 4: Fix only demonstrated defects with a red test first**

For every defect found in Steps 1–3:

1. Add the smallest test that reproduces it.
2. Run that test and confirm the expected failure.
3. Apply the smallest fix in the shared root cause.
4. Re-run the focused test and the affected task suite.

Do not alter requirements to make a failure disappear.

- [ ] **Step 5: Re-run final verification after the last change**

Repeat:

```bash
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput
python -m pip check
git diff --check
```

Repeat both browser widths for any changed template or CSS. Remove disposable QA data and generated local artifacts. Confirm `git status --short` contains only intentional source changes.

- [ ] **Step 6: Commit demonstrated corrections, if any**

If verification required changes:

```bash
git add static/css/sarangbuku.css templates/books/wishlist.html templates/books/discover.html templates/books/discovery_detail.html books/forms.py books/services.py books/views.py books/tests/test_wishlist.py books/tests/test_discovery.py
git commit -m "Fix Phase 4 verification defects"
```

The explicit `git add` list is intentionally limited to Phase 4 surfaces; unchanged files are ignored by Git.

If no defect required a code change, do not create an empty commit.

## Completion Gate

Phase 4 is complete only when:

- Every task's focused tests passed after first demonstrating RED.
- The full Django suite and all verification commands pass from the final commit.
- Browser evidence covers both required widths and the privacy-sensitive stale-link cases.
- The working tree is clean after disposable artifacts are removed.
- No Phase 4 screen queries Open Library, offers manual wishlist entry, creates a `Minat`, or exposes owner identity.
