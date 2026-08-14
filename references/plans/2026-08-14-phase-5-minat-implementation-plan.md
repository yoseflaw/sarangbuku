# Phase 5 Minat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let eligible members create, decide, and review private one-for-one Minat, then atomically turn one accepted Minat into one reserved Tukar without leaking identity before acceptance.

**Architecture:** Keep exchange behavior in the existing `swaps` app. Models persist state, forms restrict member choices, views handle authentication/HTTP/rendering, and transactional functions in `swaps/services.py` are the only write boundary for Minat transitions, copy availability transitions involving Minat, acceptance, reservation, and account deactivation. Notifications run through `transaction.on_commit()` and a small helper that catches delivery failures and logs only the notification type and record ID.

**Tech Stack:** Django 5.2.16, PostgreSQL via psycopg 3.3.4, Django Templates, Bootstrap, Django Admin, Django test framework, native `agent_browser`

## Global Constraints

- Treat `AGENTS.md`, `references/mvp/MVP_SPEC.md`, and `references/specs/2026-08-14-phase-5-minat-design.md` at commit `97045d8` as binding.
- Keep Phase 5 in the existing `accounts`, `books`, and `swaps` apps; do not add an app, dependency, task queue, cache, JavaScript frontend, or speculative infrastructure.
- A Minat exchanges exactly one requested `BookCopy` for one offered `BookCopy`; there is no negotiation, counteroffer, or pre-acceptance message thread.
- Hide the other participant's display name, email, profile, bookshelf, and other books until acceptance; rejected, withdrawn, and automatically rejected Minat never reveal identity.
- Store only public administrator-defined Sarang; never collect precise coordinates, home addresses, schedules, phone numbers, or legal identity.
- Pending Minat do not reserve copies. One copy may appear in multiple pending Minat, but only one accepted Tukar may reserve it.
- Require both accounts active, both copies currently owned by their stated owners and `available`, different participants, different copies, and one active Sarang shared by both participants at creation and acceptance.
- Make every state-changing member route authenticated, CSRF-protected POST. Unauthorized and privacy-ineligible object access returns 404.
- Keep all state transitions in `swaps/services.py`; forms constrain choices and views remain thin.
- Run notifications only after commit. Delivery failure must not roll back product state, and logs must contain neither email addresses, exception text, provider credentials, nor message bodies.
- User-facing copy must be natural conversational Indonesian following EYD, must avoid em dashes, and must use `Lini`, `Ditunggu`, `Menunggu`, `Riwayat`, `Batal`, `Tolak`, `Terima`, and `Tukar` exactly as approved.
- Preserve visible labels, field-associated errors, keyboard operation, visible focus, WCAG 2.1 AA contrast, status meaning without color alone, and mobile usability without horizontal overflow.
- Phase 5 must not scaffold coordination messages, accepted-swap cancellation, handover confirmation, ownership transfer, problem reporting, administrative resolution, or completed swap history.
- Use `.venv/bin/python` for every Django or Python command. Do not use system Python.
- Follow TDD: demonstrate each named test RED, implement the smallest shared-root fix, demonstrate GREEN, then commit the independently reviewable task.
- Do not alter the current local catalog, Open Library fallback, manual entry behavior, condition ordering, discovery pagination, or wishlist semantics except for the required availability-field rename and Minat CTA.

## Locked State, Interfaces, Messages, Lock Order, and Routes

### Model state and relationships

```python
# books.models.BookCopy
class Availability(models.TextChoices):
    AVAILABLE = "available", "Tersedia"
    RESERVED = "reserved", "Dipesan untuk Tukar"
    UNAVAILABLE = "unavailable", "Tidak tersedia"

availability_status = models.CharField(
    max_length=11,
    choices=Availability.choices,
    default=Availability.AVAILABLE,
)
```

```python
# swaps.models.Minat
requester = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.PROTECT,
    related_name="sent_minat",
)
recipient = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.PROTECT,
    related_name="received_minat",
)
requested_copy = models.ForeignKey(
    "books.BookCopy",
    on_delete=models.PROTECT,
    related_name="requested_in_minat",
)
offered_copy = models.ForeignKey(
    "books.BookCopy",
    on_delete=models.PROTECT,
    related_name="offered_in_minat",
)
swap_zone = models.ForeignKey(
    "accounts.SwapZone",
    on_delete=models.PROTECT,
    related_name="minat",
)
status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
created_at = models.DateTimeField(auto_now_add=True)
updated_at = models.DateTimeField(auto_now=True)
resolved_at = models.DateTimeField(blank=True, null=True)
```

`Minat.Status` values are exactly `pending`, `accepted`, `rejected`, `withdrawn`, and `automatically_rejected`. Its ordering is `("-created_at", "-pk")`. Constraint names are exactly `swaps_minat_distinct_copies` and `swaps_minat_unique_pending_combination`.

```python
# swaps.models.BookSwap
minat = models.OneToOneField(
    Minat,
    on_delete=models.PROTECT,
    related_name="book_swap",
)
swap_zone = models.ForeignKey(
    "accounts.SwapZone",
    on_delete=models.PROTECT,
    related_name="book_swaps",
)
status = models.CharField(
    max_length=24,
    choices=Status.choices,
    default=Status.COORDINATING,
)
created_at = models.DateTimeField(auto_now_add=True)
updated_at = models.DateTimeField(auto_now=True)
```

`BookSwap.Status` has only `COORDINATING = "coordinating", "Koordinasi"` in Phase 5. Its ordering is `("-created_at", "-pk")`. Do not add participant, copy, confirmation, cancellation, problem, completion, message, or ownership fields; those facts remain reachable through the protected accepted `Minat`.

### Service exceptions and exact public signatures

```python
# swaps.services
class SwapServiceError(Exception):
    message = "Permintaan ini belum dapat diproses. Coba muat ulang halaman."

    def __str__(self) -> str:
        return self.message


class MinatEligibilityError(SwapServiceError):
    message = "Minat ini tidak dapat diajukan. Pilih buku dan Sarang yang masih tersedia untukmu."


class DuplicatePendingMinat(SwapServiceError):
    message = "Minat yang sama masih menunggu jawaban. Kamu dapat melihatnya di Lini."


class MinatTransitionError(SwapServiceError):
    message = "Minat ini sudah tidak dapat diproses. Buku atau Sarangnya mungkin sudah berubah."


class ReservedCopyError(SwapServiceError):
    message = "Buku ini sedang dipesan untuk Tukar dan belum dapat diubah atau dihapus."


class HistoricalCopyError(SwapServiceError):
    message = "Buku ini sudah tercatat dalam Minat, jadi tidak dapat dihapus. Kamu masih dapat membuatnya tidak tersedia."


class UnfinishedSwapError(SwapServiceError):
    message = "Akun ini masih memiliki Tukar yang belum selesai dan belum dapat dinonaktifkan."
```

Exact public callable signatures:

```text
create_minat(*, requester: User, requested_copy_id: int, offered_copy_id: int, swap_zone_id: int) -> Minat
withdraw_minat(*, minat_id: int, requester: User) -> Minat
reject_minat(*, minat_id: int, recipient: User) -> Minat
accept_minat(*, minat_id: int, recipient: User) -> BookSwap
update_book_copy(*, copy_id: int, owner: User, condition: str, condition_note: str, availability_status: str) -> BookCopy
delete_book_copy(*, copy_id: int, owner: User) -> None
deactivate_account(*, user_id: int) -> User
```

Tasks 3–6 provide executable bodies for every signature. Callers may catch only these public exceptions. `BookCopy.DoesNotExist`, `Minat.DoesNotExist`, and `User.DoesNotExist` remain programmer/internal lookup failures and are converted to 404 by views before service calls.

### Notification signatures

```text
notify_new_minat(*, minat_id: int) -> None
notify_rejected_minat(*, minat_id: int, automatic: bool) -> None
notify_accepted_minat(*, minat_id: int) -> None
```

Each function loads the committed row, builds privacy-appropriate Indonesian copy, and calls one private `_deliver()` helper. `_deliver()` catches `Exception` and logs exactly `"Notification delivery failed: type=%s record_id=%s"` with notification type and integer ID, without `exc_info` and without interpolating the exception.

### Deterministic database lock order

Every service touching shared exchange state acquires only the rows it needs, always in this order:

1. Participant `accounts.User` rows sorted by primary key.
2. Involved `books.BookCopy` rows sorted by primary key.
3. Involved `swaps.Minat` rows sorted by primary key.
4. Existing `swaps.BookSwap` rows sorted by primary key.

Creation, acceptance, copy availability changes, and deactivation all obey this order. Services may perform an unlocked ID-only seed read before locking, but must re-read and revalidate locked rows before writing. This order prevents acceptance/deactivation and competing-acceptance lock inversion. Creating a Minat locks both copies before checking availability, so no pending Minat can be inserted after acceptance has reserved a copy.

### Routes

```python
# swaps.urls
path("lini/", views.lini, name="lini")
path("minat/ajukan/<int:requested_copy_id>/", views.minat_create, name="minat_create")
path("minat/<int:pk>/", views.minat_detail, name="minat_detail")
path("minat/<int:pk>/batal/", views.minat_withdraw, name="minat_withdraw")
path("minat/<int:pk>/tolak/", views.minat_reject, name="minat_reject")
path("minat/<int:pk>/terima/", views.minat_accept, name="minat_accept")
path("tukar/", views.swap_list, name="swap_list")
path("tukar/<int:pk>/", views.swap_detail, name="swap_detail")
```

`config/urls.py` includes `path("", include("swaps.urls"))`. Route names and paths are stable inputs to templates, emails, and later phases.

### Status labels and action feedback

```python
MINAT_HISTORY_LABELS = {
    Minat.Status.ACCEPTED: "Diterima",
    Minat.Status.REJECTED: "Ditolak",
    Minat.Status.WITHDRAWN: "Dibatalkan",
    Minat.Status.AUTOMATICALLY_REJECTED: "Ditolak otomatis",
}
```

Successful member feedback is exactly:

- Creation: `"Minatmu sudah dikirim."`
- Withdrawal: `"Minat sudah dibatalkan."`
- Rejection: `"Minat sudah ditolak."`
- Acceptance: `"Minat diterima. Tukar ini siap dikoordinasikan."`
- Copy update: existing `"Bukumu sudah diperbarui."`
- Reserved copy refusal: `ReservedCopyError.message`

Creation and acceptance errors use only the exception messages above. They do not name the hidden participant or disclose whether an account, copy, ownership relation, or Sarang caused the refusal.

## File Responsibility Map

- `books/models.py`: replace Boolean availability with canonical `BookCopy.Availability` and `availability_status`.
- `books/migrations/0003_bookcopy_availability_status.py`: reversible Boolean-to-status data migration after `books.0002_wishlistitem`.
- `books/forms.py`: expose only `available` and `unavailable` to members in both copy forms; never accept `reserved` from member POST data.
- `books/services.py`: keep catalog creation and discovery; use `availability_status=available` in discovery.
- `books/views.py`: route existing shelf edits/deletes through `swaps.services` while preserving thin HTTP handling.
- `books/admin.py`: display and filter canonical availability status.
- `books/urls.py`: unchanged; existing shelf and discovery routes remain stable.
- `templates/books/copy_form.html`: render the two-choice availability field with associated errors.
- `templates/books/manual_form.html`: render the renamed availability field.
- `templates/books/shelf.html`: show `Tersedia`, `Dipesan untuk Tukar`, or `Tidak tersedia`, and suppress reserved edit/delete controls.
- `templates/books/copy_confirm_delete.html`: preserve existing confirmation for deletable copies.
- `templates/books/discovery_detail.html`: add the eligible `Ajukan Minat` link without exposing owner identity.
- `books/tests/test_migrations.py`: prove forward and reverse availability mapping.
- `books/tests/test_models.py`: canonical availability choices/default/constraint and admin regression.
- `books/tests/test_shelf.py`: renamed field, member choice restriction, transition integration, and reserved/history guards.
- `books/tests/test_discovery.py`: available-only discovery and CTA privacy regressions.
- `books/tests/test_catalog.py`, `books/tests/test_manual_entry.py`, `books/tests/test_open_library.py`: update every existing copy-creation fixture and assertion to `availability_status`.
- `swaps/models.py`: `Minat` and minimal `BookSwap` persistence only.
- `swaps/migrations/0001_initial.py`: Phase 5 exchange schema depending on accounts and the completed books availability migration.
- `swaps/forms.py`: requester-scoped offered-copy and shared-Sarang choices.
- `swaps/services.py`: all Minat, reservation, copy-transition, and account-deactivation state changes.
- `swaps/notifications.py`: committed-row email composition, failure isolation, and privacy-safe logging.
- `swaps/views.py`: thin authenticated create/detail/Lini/action/Tukar views.
- `swaps/urls.py`: locked Phase 5 routes.
- `swaps/admin.py`: inspection-only Minat and BookSwap registration.
- `swaps/tests.py`: delete the current empty generated test module when the focused test package is created.
- `swaps/tests/__init__.py`: test package marker.
- `swaps/tests/test_models.py`: statuses, constraints, protection, migration-facing model shape, and admin inspection.
- `swaps/tests/test_creation.py`: form choices, creation eligibility, duplicate race conversion, email, routes, CTA, and pre-acceptance privacy.
- `swaps/tests/test_lini.py`: grouping, ordering, labels, empty states, authorization, withdrawal, rejection, and rejection email.
- `swaps/tests/test_acceptance.py`: atomic acceptance, deterministic conflicts, notification timing/failure, stale validation, and PostgreSQL thread races.
- `swaps/tests/test_shelf_integration.py`: automatic rejection on available-to-unavailable transitions and reserved/historical shelf guards.
- `swaps/tests/test_deactivation.py`: service and Django Admin deactivation path, pending rejection, and unfinished-Tukar refusal.
- `swaps/tests/test_tukar.py`: participant-only list/detail and accepted identity reveal.
- `templates/swaps/minat_form.html`: fixed requested copy, constrained offered copy/Sarang fields, and field-associated errors.
- `templates/swaps/minat_detail.html`: private books/conditions/Sarang/status/timestamps with role- and state-specific POST actions.
- `templates/swaps/lini.html`: responsive `Ditunggu`, `Menunggu`, and `Riwayat` sections with useful empty states.
- `templates/swaps/swap_list.html`: participant-only accepted Tukar cards.
- `templates/swaps/swap_detail.html`: accepted participants, both books, conditions, and accepted Sarang without future controls.
- `templates/swaps/emails/new_minat.txt`, `rejected_minat.txt`, `accepted_minat.txt`: privacy-scoped plain-text notification bodies.
- `templates/base.html`: authenticated `Lini` and `Tukar` navigation.
- `accounts/admin.py`: make existing-account `is_active` read-only and route administrative deactivation through `deactivate_account()`.
- `config/urls.py`: include `swaps.urls` at the root.
- `config/settings.py`: no change; existing PostgreSQL, email, template, and installed-app settings are sufficient.
- `static/css/sarangbuku.css`: change only when Task 7 browser evidence demonstrates a focus, contrast, or overflow defect not solved by existing Bootstrap/layout classes.

---

### Task 1: Migrate BookCopy Availability to Canonical Status

**Files:**
- Modify: `books/models.py`
- Create: `books/migrations/0003_bookcopy_availability_status.py`
- Modify: `books/forms.py`
- Modify: `books/services.py`
- Modify: `books/admin.py`
- Modify: `templates/books/copy_form.html`
- Modify: `templates/books/manual_form.html`
- Modify: `templates/books/shelf.html`
- Create: `books/tests/test_migrations.py`
- Modify: `books/tests/test_models.py`
- Modify: `books/tests/test_shelf.py`
- Modify: `books/tests/test_discovery.py`
- Modify: `books/tests/test_catalog.py`
- Modify: `books/tests/test_manual_entry.py`
- Modify: `books/tests/test_open_library.py`

**Interfaces:**
- Consumes: `books.0002_wishlistitem`, existing `BookCopy.Condition`, existing shelf/discovery/catalog interfaces.
- Produces: `BookCopy.Availability`, `BookCopy.availability_status`, migration `books.0003_bookcopy_availability_status`, and member forms that accept only `available` or `unavailable`.

- [ ] **Step 1: Write the failing model, form, discovery, admin, and migration tests**

Create `books/tests/test_migrations.py` with a reversible migration test. The `tearDown()` migration back to leaf nodes prevents later tests from running against the historical schema:

```python
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class BookCopyAvailabilityMigrationTests(TransactionTestCase):
    migrate_from = ("books", "0002_wishlistitem")
    migrate_to = ("books", "0003_bookcopy_availability_status")

    def tearDown(self):
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
        super().tearDown()

    def test_forward_and_reverse_values_are_preserved(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        User = old_apps.get_model("accounts", "User")
        Book = old_apps.get_model("books", "Book")
        BookCopy = old_apps.get_model("books", "BookCopy")
        owner = User.objects.create(email="migration@example.com", display_name="Migrasi")
        book = Book.objects.create(title="Migrasi", authors="Penulis", language="Indonesia")
        available = BookCopy.objects.create(
            owner=owner, book=book, condition="good", is_available=True
        )
        unavailable = BookCopy.objects.create(
            owner=owner, book=book, condition="fair", is_available=False
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        new_apps = executor.loader.project_state([self.migrate_to]).apps
        MigratedCopy = new_apps.get_model("books", "BookCopy")
        self.assertEqual(
            MigratedCopy.objects.get(pk=available.pk).availability_status,
            "available",
        )
        self.assertEqual(
            MigratedCopy.objects.get(pk=unavailable.pk).availability_status,
            "unavailable",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        restored_apps = executor.loader.project_state([self.migrate_from]).apps
        RestoredCopy = restored_apps.get_model("books", "BookCopy")
        self.assertTrue(RestoredCopy.objects.get(pk=available.pk).is_available)
        self.assertFalse(RestoredCopy.objects.get(pk=unavailable.pk).is_available)
```

Add the model class below to `books/tests/test_models.py`. In `books/tests/test_shelf.py`, import `BookCopyForm` and `ManualBookCopyForm` from `books.forms`, then add the second method below to the existing `ShelfTests` class:

```python
class BookCopyAvailabilityTests(TestCase):
    def test_availability_values_labels_and_default_are_canonical(self):
        field = BookCopy._meta.get_field("availability_status")
        self.assertEqual(
            list(BookCopy.Availability.choices),
            [
                ("available", "Tersedia"),
                ("reserved", "Dipesan untuk Tukar"),
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
```

```python
    def test_member_forms_never_offer_reserved(self):
        edit_form = BookCopyForm(instance=self.copy)
        manual_form = ManualBookCopyForm()

        expected = {
            BookCopy.Availability.AVAILABLE,
            BookCopy.Availability.UNAVAILABLE,
        }
        self.assertEqual(set(dict(edit_form.fields["availability_status"].choices)), expected)
        self.assertEqual(set(dict(manual_form.fields["availability_status"].choices)), expected)
```

Update `AdminTests.test_bookcopy_admin_is_registered` to expect `availability_status`. Update discovery expectations so `reserved` and `unavailable` are excluded while `available` remains included.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_models.BookCopyAvailabilityTests books.tests.test_shelf.ShelfTests.test_member_forms_never_offer_reserved books.tests.test_migrations.BookCopyAvailabilityMigrationTests --verbosity 2
```

Expected: failures because `BookCopy.Availability`, `availability_status`, and migration node `0003_bookcopy_availability_status` do not exist.

- [ ] **Step 3: Add the canonical model field and reversible migration without a runtime/schema mismatch**

Replace `is_available` in `books/models.py` with the locked `Availability` class and field, and add a database check beside the existing condition check:

```python
            models.CheckConstraint(
                condition=Q(
                    availability_status__in=[
                        "available",
                        "reserved",
                        "unavailable",
                    ]
                ),
                name="books_bookcopy_availability_valid",
            ),
```

Create `books/migrations/0003_bookcopy_availability_status.py` exactly in this operation order:

```python
from django.db import migrations, models


def forwards(apps, schema_editor):
    BookCopy = apps.get_model("books", "BookCopy")
    BookCopy.objects.filter(is_available=True).update(availability_status="available")
    BookCopy.objects.filter(is_available=False).update(availability_status="unavailable")


def backwards(apps, schema_editor):
    BookCopy = apps.get_model("books", "BookCopy")
    BookCopy.objects.filter(availability_status="available").update(is_available=True)
    BookCopy.objects.exclude(availability_status="available").update(is_available=False)


class Migration(migrations.Migration):
    dependencies = [("books", "0002_wishlistitem")]

    operations = [
        migrations.AddField(
            model_name="bookcopy",
            name="availability_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("available", "Tersedia"),
                    ("reserved", "Dipesan untuk Tukar"),
                    ("unavailable", "Tidak tersedia"),
                ],
                max_length=11,
                null=True,
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="bookcopy", name="is_available"),
        migrations.AlterField(
            model_name="bookcopy",
            name="availability_status",
            field=models.CharField(
                choices=[
                    ("available", "Tersedia"),
                    ("reserved", "Dipesan untuk Tukar"),
                    ("unavailable", "Tidak tersedia"),
                ],
                default="available",
                max_length=11,
            ),
        ),
        migrations.AddConstraint(
            model_name="bookcopy",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    availability_status__in=["available", "reserved", "unavailable"]
                ),
                name="books_bookcopy_availability_valid",
            ),
        ),
    ]
```

The nullable temporary field, data copy, old-field removal, and final non-null alteration remain in one migration and one commit. Do not deploy a runtime model that expects `availability_status` before this migration exists, and do not split the old-field removal into another commit.

- [ ] **Step 4: Replace every runtime and test reference**

In both `BookCopyForm` and `ManualBookCopyForm`, use this field definition and rename `copy_fields` accordingly:

```python
MEMBER_AVAILABILITY_CHOICES = (
    (BookCopy.Availability.AVAILABLE, "Tersedia untuk ditukar"),
    (BookCopy.Availability.UNAVAILABLE, "Tidak tersedia"),
)

availability_status = forms.ChoiceField(
    label="Ketersediaan",
    choices=MEMBER_AVAILABILITY_CHOICES,
    widget=forms.Select(attrs={"class": "form-select"}),
)
```

`BookCopyForm.Meta.fields` becomes `("condition", "condition_note", "availability_status")`. `ManualBookCopyForm.save()` passes `availability_status`. `discoverable_copies()` filters `availability_status=BookCopy.Availability.AVAILABLE`. `BookCopyAdmin.list_display` and `list_filter` use `availability_status`.

Replace every existing test fixture and assertion as follows:

```python
availability_status=BookCopy.Availability.AVAILABLE
availability_status=BookCopy.Availability.UNAVAILABLE
self.assertEqual(copy.availability_status, BookCopy.Availability.AVAILABLE)
```

Update POST data in `test_catalog.py`, `test_manual_entry.py`, `test_open_library.py`, and `test_shelf.py` to send `"availability_status": "available"` or `"unavailable"`. Do not retain a compatibility property named `is_available`; the repository-wide search must become empty outside historical migration code and the migration test.

Render `form.availability_status` as a labeled `<select>` with `is-invalid`, `aria-invalid`, `aria-describedby`, and an error element ID when invalid. In `shelf.html`, branch explicitly across all three statuses and render text for each; do not rely on badge color alone.

- [ ] **Step 5: Run migration and complete books regression verification; verify GREEN**

Run:

```bash
.venv/bin/python manage.py test books.tests.test_migrations books.tests.test_models books.tests.test_shelf books.tests.test_discovery books.tests.test_catalog books.tests.test_manual_entry books.tests.test_open_library --verbosity 2
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py shell -c "from pathlib import Path; hits=[str(p) for p in Path('.').rglob('*') if p.suffix in {'.py','.html'} and 'is_available' in p.read_text() and p.name not in {'0001_phase_3_books.py','0003_bookcopy_availability_status.py','test_migrations.py'}]; assert not hits, hits"
```

Expected: all tests pass, migrations apply, Django reports `No changes detected`, and the shell assertion exits 0 with no stale runtime references.

- [ ] **Step 6: Commit Task 1**

```bash
git add books/models.py books/migrations/0003_bookcopy_availability_status.py books/forms.py books/services.py books/admin.py templates/books/copy_form.html templates/books/manual_form.html templates/books/shelf.html books/tests/test_migrations.py books/tests/test_models.py books/tests/test_shelf.py books/tests/test_discovery.py books/tests/test_catalog.py books/tests/test_manual_entry.py books/tests/test_open_library.py
git commit -m "Migrate book availability to statuses"
```

---

### Task 2: Persist Minat and Minimal BookSwap Safely

**Files:**
- Modify: `swaps/models.py`
- Create: `swaps/migrations/0001_initial.py`
- Modify: `swaps/admin.py`
- Delete: `swaps/tests.py`
- Create: `swaps/tests/__init__.py`
- Create: `swaps/tests/test_models.py`

**Interfaces:**
- Consumes: `accounts.User`, `accounts.SwapZone`, `books.BookCopy`, and migration `books.0003_bookcopy_availability_status`.
- Produces: the locked `Minat` and `BookSwap` models, protected historical relationships, exact constraints, and inspection-only Admin registrations.

- [ ] **Step 1: Write failing model, constraint, protection, and admin tests**

Create the test package, then add representative tests to `swaps/tests/test_models.py`:

```python
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
        self.zone = SwapZone.objects.create(name="Blok M", description="Bertemu di lobi.")
        book = Book.objects.create(title="Matilda", authors="Roald Dahl", language="English")
        other = Book.objects.create(title="Laskar Pelangi", authors="Andrea Hirata", language="Indonesia")
        self.requested = BookCopy.objects.create(
            owner=self.recipient, book=book, condition=BookCopy.Condition.GOOD
        )
        self.offered = BookCopy.objects.create(
            owner=self.requester, book=other, condition=BookCopy.Condition.VERY_GOOD
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
```

Also test different offered copy, requested copy, requester, or Sarang combinations remain allowed while an exact pending row exists; test `resolved_at` is nullable and ordering is newest first.

- [ ] **Step 2: Run model tests and verify RED**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_models --verbosity 2
```

Expected: import failures because `Minat`, `BookSwap`, and their Admin classes do not exist.

- [ ] **Step 3: Implement the exact models**

Replace `swaps/models.py` with:

```python
from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Minat(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Menunggu"
        ACCEPTED = "accepted", "Diterima"
        REJECTED = "rejected", "Ditolak"
        WITHDRAWN = "withdrawn", "Dibatalkan"
        AUTOMATICALLY_REJECTED = "automatically_rejected", "Ditolak otomatis"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_minat"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_minat"
    )
    requested_copy = models.ForeignKey(
        "books.BookCopy", on_delete=models.PROTECT, related_name="requested_in_minat"
    )
    offered_copy = models.ForeignKey(
        "books.BookCopy", on_delete=models.PROTECT, related_name="offered_in_minat"
    )
    swap_zone = models.ForeignKey(
        "accounts.SwapZone", on_delete=models.PROTECT, related_name="minat"
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=~Q(requested_copy=F("offered_copy")),
                name="swaps_minat_distinct_copies",
            ),
            models.UniqueConstraint(
                fields=("requester", "requested_copy", "offered_copy", "swap_zone"),
                condition=Q(status="pending"),
                name="swaps_minat_unique_pending_combination",
            ),
        ]

    def __str__(self):
        return f"Minat {self.pk or 'baru'}"


class BookSwap(models.Model):
    class Status(models.TextChoices):
        COORDINATING = "coordinating", "Koordinasi"

    minat = models.OneToOneField(
        Minat, on_delete=models.PROTECT, related_name="book_swap"
    )
    swap_zone = models.ForeignKey(
        "accounts.SwapZone", on_delete=models.PROTECT, related_name="book_swaps"
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.COORDINATING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"Tukar {self.pk or 'baru'}"
```

- [ ] **Step 4: Generate and inspect the initial swaps migration**

Run:

```bash
.venv/bin/python manage.py makemigrations swaps
.venv/bin/python manage.py sqlmigrate swaps 0001
```

Expected: `swaps/migrations/0001_initial.py` has exactly these dependencies because it references both the swappable user and `SwapZone`: `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`, `("accounts", "0002_phase_2_accounts")`, and `("books", "0003_bookcopy_availability_status")`. It creates `Minat` before `BookSwap`, uses `PROTECT` on every historical relation, creates the one-to-one unique relation, and creates both named Minat constraints. It must not depend on a future migration.

- [ ] **Step 5: Register inspection-only Admin classes**

Use read-only fields and no add/delete actions:

```python
from django.contrib import admin

from .models import BookSwap, Minat


@admin.register(Minat)
class MinatAdmin(admin.ModelAdmin):
    list_display = (
        "id", "requester", "recipient", "requested_copy", "offered_copy",
        "swap_zone", "status", "created_at", "resolved_at",
    )
    list_filter = ("status", "swap_zone")
    search_fields = (
        "requester__email", "recipient__email", "requested_copy__book__title",
        "offered_copy__book__title",
    )
    list_select_related = (
        "requester", "recipient", "requested_copy__book", "offered_copy__book", "swap_zone",
    )
    readonly_fields = (
        "requester", "recipient", "requested_copy", "offered_copy", "swap_zone",
        "status", "created_at", "updated_at", "resolved_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BookSwap)
class BookSwapAdmin(admin.ModelAdmin):
    list_display = ("id", "minat", "swap_zone", "status", "created_at")
    list_filter = ("status", "swap_zone")
    search_fields = (
        "minat__requester__email", "minat__recipient__email",
        "minat__requested_copy__book__title", "minat__offered_copy__book__title",
    )
    list_select_related = ("minat", "swap_zone")
    readonly_fields = ("minat", "swap_zone", "status", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

Do not add Admin transition actions or editable status fields.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_models --verbosity 2
.venv/bin/python manage.py makemigrations --check --dry-run
```

Expected: all model/Admin tests pass and Django reports `No changes detected`.

- [ ] **Step 7: Commit Task 2**

```bash
git add swaps/models.py swaps/migrations/0001_initial.py swaps/admin.py swaps/tests.py swaps/tests/__init__.py swaps/tests/test_models.py
git commit -m "Add Minat and Tukar persistence"
```

---

### Task 3: Create Private Minat with Constrained Choices and Safe Notification

**Files:**
- Create: `swaps/forms.py`
- Create: `swaps/services.py`
- Create: `swaps/notifications.py`
- Modify: `swaps/views.py`
- Create: `swaps/urls.py`
- Modify: `config/urls.py`
- Modify: `templates/books/discovery_detail.html`
- Create: `templates/swaps/minat_form.html`
- Create: `templates/swaps/minat_detail.html`
- Create: `templates/swaps/emails/new_minat.txt`
- Create: `templates/swaps/emails/rejected_minat.txt`
- Create: `templates/swaps/emails/accepted_minat.txt`
- Create: `swaps/tests/test_creation.py`
- Modify: `books/tests/test_discovery.py`

**Interfaces:**
- Consumes: `discoverable_copies(*, viewer)`, Task 2 models, locked exception/messages/routes.
- Produces: `MinatCreateForm`, `create_minat()`, notification helper functions, private create/detail routes, eligible `Ajukan Minat` CTA, and pre-acceptance anonymity.

- [ ] **Step 1: Write failing form, service, route, privacy, duplicate, and notification tests**

Create `swaps/tests/test_creation.py`. Cover all eligibility bullets separately: inactive requester, inactive recipient, own requested copy, requested copy not owned by recipient, unavailable/reserved requested or offered copy, offered copy not owned by requester, same copy, inactive/unshared Sarang, and exact duplicate. Include this representative happy-path/privacy test:

```python
    def test_create_revalidates_and_keeps_both_sides_anonymous(self):
        self.client.force_login(self.requester)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("swaps:minat_create", args=[self.requested.pk]),
                {"offered_copy": self.offered.pk, "swap_zone": self.shared.pk},
            )

        minat = Minat.objects.get()
        self.assertRedirects(response, reverse("swaps:minat_detail", args=[minat.pk]))
        self.assertEqual(minat.recipient, self.recipient)
        self.assertEqual(minat.status, Minat.Status.PENDING)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.requester.display_name, mail.outbox[0].body)
        self.assertNotIn(self.requester.email, mail.outbox[0].body)

        requester_detail = self.client.get(reverse("swaps:minat_detail", args=[minat.pk]))
        self.assertNotContains(requester_detail, self.recipient.display_name)
        self.assertNotContains(requester_detail, self.recipient.email)
        self.client.force_login(self.recipient)
        recipient_detail = self.client.get(reverse("swaps:minat_detail", args=[minat.pk]))
        self.assertNotContains(recipient_detail, self.requester.display_name)
        self.assertNotContains(recipient_detail, self.requester.email)
```

Test choice querysets exactly:

```python
    def test_form_offers_only_requesters_available_copies_and_shared_active_sarang(self):
        form = MinatCreateForm(requester=self.requester, requested_copy=self.requested)

        self.assertQuerySetEqual(form.fields["offered_copy"].queryset, [self.offered])
        self.assertQuerySetEqual(form.fields["swap_zone"].queryset, [self.shared])
```

Test member POST tampering returns field errors, duplicate normal validation uses `DuplicatePendingMinat.message`, and a patched `Minat.objects.create` raising an `IntegrityError` whose PostgreSQL constraint name is `swaps_minat_unique_pending_combination` is converted to `DuplicatePendingMinat`. Test unrelated `IntegrityError` is re-raised.

Use `captureOnCommitCallbacks(execute=False)` to assert no email helper runs before commit. Patch `swaps.notifications.send_mail` to raise `SMTPException("address requester@example.com credential secret")`; assert the Minat remains committed and `assertLogs("swaps.notifications")` contains the notification type/record ID but none of `requester@example.com`, `recipient@example.com`, `credential`, `secret`, or `SMTPException`.

- [ ] **Step 2: Run creation tests and verify RED**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_creation --verbosity 2
```

Expected: import and URL reversal failures because the form, service, notifications, and routes do not exist.

- [ ] **Step 3: Implement exact exceptions, lock helpers, and create service**

Start `swaps/services.py` with the locked exception classes and these helpers:

```python
from django.db import IntegrityError, transaction
from django.db.models import Q

from accounts.models import SwapZone, User
from books.models import BookCopy

from .models import BookSwap, Minat
from .notifications import (
    notify_accepted_minat,
    notify_new_minat,
    notify_rejected_minat,
)

PENDING_DUPLICATE_CONSTRAINT = "swaps_minat_unique_pending_combination"


def _lock_users(*user_ids: int) -> dict[int, User]:
    return {
        user.pk: user
        for user in User.objects.select_for_update()
        .filter(pk__in=set(user_ids))
        .order_by("pk")
    }


def _lock_copies(*copy_ids: int) -> dict[int, BookCopy]:
    return {
        copy.pk: copy
        for copy in BookCopy.objects.select_for_update()
        .select_related("owner", "book")
        .filter(pk__in=set(copy_ids))
        .order_by("pk")
    }


def _zone_is_shared(*, swap_zone_id: int, first_user_id: int, second_user_id: int) -> bool:
    return (
        SwapZone.objects.filter(pk=swap_zone_id, is_active=True, users=first_user_id)
        .filter(users=second_user_id)
        .exists()
    )


def _constraint_name(error: IntegrityError) -> str | None:
    cause = getattr(error, "__cause__", None)
    diag = getattr(cause, "diag", None)
    return getattr(diag, "constraint_name", None)
```

Implement creation with user-then-copy lock order and a nested savepoint around the race-prone insert:

```python
@transaction.atomic
def create_minat(
    *, requester: User, requested_copy_id: int, offered_copy_id: int, swap_zone_id: int
) -> Minat:
    seed = list(
        BookCopy.objects.filter(pk__in={requested_copy_id, offered_copy_id})
        .only("pk", "owner_id")
        .order_by("pk")
    )
    if len(seed) != 2:
        raise MinatEligibilityError
    owner_by_copy = {copy.pk: copy.owner_id for copy in seed}
    recipient_id = owner_by_copy[requested_copy_id]
    users = _lock_users(requester.pk, recipient_id)
    copies = _lock_copies(requested_copy_id, offered_copy_id)
    requester = users.get(requester.pk)
    recipient = users.get(recipient_id)
    requested = copies.get(requested_copy_id)
    offered = copies.get(offered_copy_id)

    if (
        requester is None
        or recipient is None
        or requested is None
        or offered is None
        or not requester.is_active
        or not recipient.is_active
        or requester.pk == recipient.pk
        or requested.pk == offered.pk
        or requested.owner_id != recipient.pk
        or offered.owner_id != requester.pk
        or requested.availability_status != BookCopy.Availability.AVAILABLE
        or offered.availability_status != BookCopy.Availability.AVAILABLE
        or not _zone_is_shared(
            swap_zone_id=swap_zone_id,
            first_user_id=requester.pk,
            second_user_id=recipient.pk,
        )
    ):
        raise MinatEligibilityError

    duplicate = Minat.objects.filter(
        requester=requester,
        requested_copy=requested,
        offered_copy=offered,
        swap_zone_id=swap_zone_id,
        status=Minat.Status.PENDING,
    ).exists()
    if duplicate:
        raise DuplicatePendingMinat

    try:
        with transaction.atomic():
            minat = Minat.objects.create(
                requester=requester,
                recipient=recipient,
                requested_copy=requested,
                offered_copy=offered,
                swap_zone_id=swap_zone_id,
            )
    except IntegrityError as error:
        if _constraint_name(error) == PENDING_DUPLICATE_CONSTRAINT:
            raise DuplicatePendingMinat from error
        raise

    transaction.on_commit(lambda: notify_new_minat(minat_id=minat.pk))
    return minat
```

- [ ] **Step 4: Implement constrained form and privacy-safe notification delivery**

Create `swaps/forms.py`:

```python
from django import forms

from accounts.models import SwapZone, User
from books.models import BookCopy


class MinatCreateForm(forms.Form):
    offered_copy = forms.ModelChoiceField(
        label="Buku yang kamu tawarkan",
        queryset=BookCopy.objects.none(),
        error_messages={"invalid_choice": "Pilih buku yang masih tersedia di Lemarimu."},
    )
    swap_zone = forms.ModelChoiceField(
        label="Sarang",
        queryset=SwapZone.objects.none(),
        error_messages={"invalid_choice": "Pilih Sarang aktif yang kalian gunakan bersama."},
    )

    def __init__(
        self, *args, requester: User, requested_copy: BookCopy, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.fields["offered_copy"].queryset = (
            BookCopy.objects.filter(
                owner=requester,
                availability_status=BookCopy.Availability.AVAILABLE,
            )
            .select_related("book")
            .order_by("book__title", "pk")
        )
        self.fields["swap_zone"].queryset = (
            requester.swap_zones.filter(
                is_active=True,
                users=requested_copy.owner_id,
            )
            .order_by("name")
            .distinct()
        )
```

Create `swaps/notifications.py` with a private delivery helper and three public functions. Send one email per participant after acceptance so recipient addresses are never exposed to each other:

```python
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import Minat

logger = logging.getLogger(__name__)


def _deliver(*, notification_type: str, record_id: int, subject: str, body: str, recipient: str) -> None:
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient])
    except Exception:
        logger.error(
            "Notification delivery failed: type=%s record_id=%s",
            notification_type,
            record_id,
        )


def _exchange_context(minat: Minat) -> dict[str, str]:
    return {
        "requested_title": minat.requested_copy.book.title,
        "requested_condition": minat.requested_copy.get_condition_display(),
        "offered_title": minat.offered_copy.book.title,
        "offered_condition": minat.offered_copy.get_condition_display(),
        "swap_zone_name": minat.swap_zone.name,
    }


def notify_new_minat(*, minat_id: int) -> None:
    minat = Minat.objects.select_related(
        "recipient", "requested_copy__book", "offered_copy__book", "swap_zone"
    ).get(pk=minat_id)
    _deliver(
        notification_type="new_minat",
        record_id=minat.pk,
        subject="Ada Minat baru di Sarang Buku",
        body=render_to_string(
            "swaps/emails/new_minat.txt", _exchange_context(minat)
        ),
        recipient=minat.recipient.email,
    )


def notify_rejected_minat(*, minat_id: int, automatic: bool) -> None:
    minat = Minat.objects.select_related(
        "requester", "requested_copy__book", "offered_copy__book", "swap_zone"
    ).get(pk=minat_id)
    context = {**_exchange_context(minat), "automatic": automatic}
    _deliver(
        notification_type=("automatically_rejected" if automatic else "rejected"),
        record_id=minat.pk,
        subject=("Minatmu tidak dapat dilanjutkan" if automatic else "Minatmu ditolak"),
        body=render_to_string("swaps/emails/rejected_minat.txt", context),
        recipient=minat.requester.email,
    )


def notify_accepted_minat(*, minat_id: int) -> None:
    minat = Minat.objects.select_related(
        "requester", "recipient", "requested_copy__book", "offered_copy__book", "swap_zone"
    ).get(pk=minat_id)
    exchange = _exchange_context(minat)
    for recipient, other_name in (
        (minat.requester, minat.recipient.display_name),
        (minat.recipient, minat.requester.display_name),
    ):
        _deliver(
            notification_type="accepted",
            record_id=minat.pk,
            subject="Minat diterima",
            body=render_to_string(
                "swaps/emails/accepted_minat.txt",
                {**exchange, "other_name": other_name},
            ),
            recipient=recipient.email,
        )
```

The new and rejection templates receive only primitive book/condition/Sarang values and cannot access either hidden participant. Create their exact bodies as follows:

```django
{# templates/swaps/emails/new_minat.txt #}
Ada Minat baru untuk {{ requested_title }}.

Buku yang ditawarkan: {{ offered_title }} ({{ offered_condition }})
Kondisi buku yang diminta: {{ requested_condition }}
Sarang: {{ swap_zone_name }}

Masuk ke Sarang Buku dan buka Lini untuk menjawabnya.
```

```django
{# templates/swaps/emails/rejected_minat.txt #}
{% if automatic %}Minatmu untuk {{ requested_title }} tidak dapat dilanjutkan karena salah satu bukunya sudah tidak tersedia.{% else %}Minatmu untuk {{ requested_title }} ditolak.{% endif %}

Buku yang kamu tawarkan: {{ offered_title }}
Sarang: {{ swap_zone_name }}

Kamu dapat membuka Lini untuk melihat statusnya.
```

```django
{# templates/swaps/emails/accepted_minat.txt #}
Minatmu diterima.

Kamu akan bertukar dengan {{ other_name }}.
Buku yang diminta: {{ requested_title }}
Buku yang ditawarkan: {{ offered_title }}
Sarang: {{ swap_zone_name }}

Buka Tukar di Sarang Buku untuk melihat kesepakatannya.
```

`accepted_minat.txt` may render `other_name` because acceptance has completed; `_deliver()` sends each participant a separate message so addresses are never shared.

- [ ] **Step 5: Add thin create/detail views, routes, templates, and CTA**

In `swaps/views.py`, scope the requested copy through discovery before displaying or submitting the form, catch only public service exceptions, and attach errors to the form:

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from books.services import discoverable_copies

from .forms import MinatCreateForm
from .models import Minat
from .services import DuplicatePendingMinat, MinatEligibilityError, create_minat


@login_required
def minat_create(request, requested_copy_id):
    requested_copy = get_object_or_404(
        discoverable_copies(viewer=request.user), pk=requested_copy_id
    )
    form = MinatCreateForm(
        request.POST or None,
        requester=request.user,
        requested_copy=requested_copy,
    )
    if request.method == "POST" and form.is_valid():
        try:
            minat = create_minat(
                requester=request.user,
                requested_copy_id=requested_copy.pk,
                offered_copy_id=form.cleaned_data["offered_copy"].pk,
                swap_zone_id=form.cleaned_data["swap_zone"].pk,
            )
        except DuplicatePendingMinat as error:
            form.add_error(None, str(error))
        except MinatEligibilityError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Minatmu sudah dikirim.")
            return redirect("swaps:minat_detail", pk=minat.pk)
    return render(
        request,
        "swaps/minat_form.html",
        {"form": form, "requested_copy": requested_copy},
    )


@login_required
def minat_detail(request, pk):
    minat = get_object_or_404(
        Minat.objects.filter(Q(requester=request.user) | Q(recipient=request.user))
        .select_related("requested_copy__book", "offered_copy__book", "swap_zone"),
        pk=pk,
    )
    return render(
        request,
        "swaps/minat_detail.html",
        {"minat": minat, "is_requester": minat.requester_id == request.user.pk},
    )
```

Create only the `minat_create` and `minat_detail` routes in this task, then include `swaps.urls` from `config/urls.py`; later tasks add their routes with their destination views in the same commit. The form/detail templates render only approved book, condition, condition-note, Sarang, status, and timestamp fields. They must not dereference `requester`, `recipient`, or `owner` for names/contact information. Add this CTA to the existing eligible discovery detail:

```django
<a class="btn btn-primary" href="{% url 'swaps:minat_create' copy.pk %}">Ajukan Minat</a>
```

The CTA appears only because `books:discovery_detail` already scopes `copy` through `discoverable_copies()`.

- [ ] **Step 6: Run creation, discovery, privacy, and notification tests; verify GREEN**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_creation books.tests.test_discovery --verbosity 2
```

Expected: all pass; ineligible/unauthorized routes return 404; duplicate races show the approved form-level message; the recipient's new-MinAT email contains no requester identity; delivery failure leaves the Minat committed.

- [ ] **Step 7: Commit Task 3**

```bash
git add swaps/forms.py swaps/services.py swaps/notifications.py swaps/views.py swaps/urls.py config/urls.py templates/books/discovery_detail.html templates/swaps/minat_form.html templates/swaps/minat_detail.html templates/swaps/emails/new_minat.txt templates/swaps/emails/rejected_minat.txt templates/swaps/emails/accepted_minat.txt swaps/tests/test_creation.py books/tests/test_discovery.py
git commit -m "Add private Minat creation"
```

---

### Task 4: Add Lini, Withdrawal, and Rejection

**Files:**
- Modify: `swaps/services.py`
- Modify: `swaps/views.py`
- Modify: `swaps/urls.py`
- Modify: `templates/swaps/minat_detail.html`
- Create: `templates/swaps/lini.html`
- Create: `swaps/tests/test_lini.py`

**Interfaces:**
- Consumes: `Minat`, participant-private detail, `notify_rejected_minat()`.
- Produces: `withdraw_minat()`, `reject_minat()`, `swaps:lini`, `swaps:minat_withdraw`, `swaps:minat_reject`, and resolved-label rendering.

- [ ] **Step 1: Write failing Lini grouping, action, authorization, and notification tests**

Create `swaps/tests/test_lini.py`. Use explicit timestamps to prove newest-first ordering. Assert:

- Received pending rows appear only under `Ditunggu` with `Tolak`; Task 5 adds `Terima` in the same commit as acceptance.
- Sent pending rows appear only under `Menunggu` with `Batal`.
- Accepted, rejected, withdrawn, and automatically rejected rows appear under `Riwayat` with exact approved labels.
- Empty sections explain the next useful action; empty `Menunggu` links to `Temukan`.
- Anonymous requests redirect to login.
- Non-participants get 404 from detail and every mutation.
- Requester cannot reject; recipient cannot withdraw; both get 404.
- GET on action routes returns 405.
- Resolved Minat cannot be acted on and remain unchanged.
- Withdrawal sets `resolved_at`, changes no availability, and sends no email.
- Rejection sets `resolved_at`, changes no availability, and schedules one privacy-safe requester email after commit.

Representative service test:

```python
    def test_rejection_changes_only_the_minat_and_notifies_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            rejected = reject_minat(minat_id=self.minat.pk, recipient=self.recipient)

        self.requested.refresh_from_db()
        self.offered.refresh_from_db()
        self.assertEqual(rejected.status, Minat.Status.REJECTED)
        self.assertIsNotNone(rejected.resolved_at)
        self.assertEqual(self.requested.availability_status, BookCopy.Availability.AVAILABLE)
        self.assertEqual(self.offered.availability_status, BookCopy.Availability.AVAILABLE)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.recipient.display_name, mail.outbox[0].body)
        self.assertNotIn(self.recipient.email, mail.outbox[0].body)
```

- [ ] **Step 2: Run Lini tests and verify RED**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_lini --verbosity 2
```

Expected: failures because Lini/action routes and transition functions do not exist.

- [ ] **Step 3: Implement locked withdrawal and rejection transitions**

Add to `swaps/services.py`:

```python
from django.utils import timezone


@transaction.atomic
def withdraw_minat(*, minat_id: int, requester: User) -> Minat:
    minat = (
        Minat.objects.select_for_update().filter(pk=minat_id, requester=requester).first()
    )
    if minat is None or minat.status != Minat.Status.PENDING:
        raise MinatTransitionError
    minat.status = Minat.Status.WITHDRAWN
    minat.resolved_at = timezone.now()
    minat.save(update_fields=["status", "resolved_at", "updated_at"])
    return minat


@transaction.atomic
def reject_minat(*, minat_id: int, recipient: User) -> Minat:
    minat = (
        Minat.objects.select_for_update().filter(pk=minat_id, recipient=recipient).first()
    )
    if minat is None or minat.status != Minat.Status.PENDING:
        raise MinatTransitionError
    minat.status = Minat.Status.REJECTED
    minat.resolved_at = timezone.now()
    minat.save(update_fields=["status", "resolved_at", "updated_at"])
    transaction.on_commit(
        lambda: notify_rejected_minat(minat_id=minat.pk, automatic=False)
    )
    return minat
```

Views pre-scope the row to the authorized role with `get_object_or_404()` before calling these services; therefore a wrong participant receives 404, while a stale authorized transition receives `MinatTransitionError.message` and redirects to the private detail.

- [ ] **Step 4: Add thin Lini and POST action views**

Implement Lini with three explicit querysets:

```python
@login_required
def lini(request):
    received = Minat.objects.filter(
        recipient=request.user, status=Minat.Status.PENDING
    ).select_related("requested_copy__book", "offered_copy__book", "swap_zone")
    sent = Minat.objects.filter(
        requester=request.user, status=Minat.Status.PENDING
    ).select_related("requested_copy__book", "offered_copy__book", "swap_zone")
    history = (
        Minat.objects.filter(Q(requester=request.user) | Q(recipient=request.user))
        .exclude(status=Minat.Status.PENDING)
        .select_related("requested_copy__book", "offered_copy__book", "swap_zone")
        .distinct()
    )
    return render(
        request,
        "swaps/lini.html",
        {"received": received, "sent": sent, "history": history},
    )
```

Add `@require_POST` withdrawal and rejection views. Each obtains an authorized row with role-specific filters, calls the matching service, catches `MinatTransitionError`, emits exact success/error feedback, and redirects to `swaps:minat_detail`. Do not put transition logic in the views.

- [ ] **Step 5: Render responsive Lini sections and authorized actions**

Create one `<h1>Lini</h1>` and logical `<h2>` headings in this order: `Ditunggu`, `Menunggu`, `Riwayat`. Use Bootstrap cards or a responsive list, not a wide table. Each item links to private detail and shows both books, conditions, Sarang, timestamp, and text status. Render action forms only with these guards:

```django
{% if minat.status == "pending" and not is_requester %}
  <form method="post" action="{% url 'swaps:minat_reject' minat.pk %}">{% csrf_token %}<button type="submit" class="btn btn-outline-danger">Tolak</button></form>
{% elif minat.status == "pending" and is_requester %}
  <form method="post" action="{% url 'swaps:minat_withdraw' minat.pk %}">{% csrf_token %}<button type="submit" class="btn btn-outline-danger">Batal</button></form>
{% endif %}
```

Keep role handling structural: the `received` loop renders recipient actions, the `sent` loop renders requester actions, and the `history` loop renders no transition action. On private detail, use the existing `is_requester` Boolean. Do not render either hidden participant object, and do not add pagination or HTMX.

- [ ] **Step 6: Run Lini and creation regressions; verify GREEN**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_lini swaps.tests.test_creation --verbosity 2
```

Expected: all pass, including 404/405 authorization, ordering, labels, post-commit rejection email, no withdrawal email, and unchanged copy availability.

- [ ] **Step 7: Commit Task 4**

```bash
git add swaps/services.py swaps/views.py swaps/urls.py templates/swaps/minat_detail.html templates/swaps/lini.html swaps/tests/test_lini.py
git commit -m "Add Lini decisions"
```

---

### Task 5: Accept Atomically Under PostgreSQL Concurrency

**Files:**
- Modify: `swaps/services.py`
- Modify: `swaps/views.py`
- Modify: `swaps/urls.py`
- Modify: `templates/swaps/minat_detail.html`
- Modify: `templates/swaps/lini.html`
- Create: `swaps/tests/test_acceptance.py`

**Interfaces:**
- Consumes: Task 3 lock helpers/notifications, Task 4 Lini/detail, canonical availability states.
- Produces: `accept_minat()`, `swaps:minat_accept`, exactly one `BookSwap`, two reserved copies, all-conflict automatic rejection, and post-commit acceptance/automatic-rejection notifications.

- [ ] **Step 1: Write failing atomicity, stale-state, conflict, email, and thread-race tests**

Create `swaps/tests/test_acceptance.py`. The ordinary `TestCase` matrix must prove:

- Only the recipient may accept and the route is POST-only.
- Pending status, active accounts, current ownership, available copies, active Sarang, and shared membership are each revalidated under lock.
- Each failed validation leaves Minat, BookSwap, copies, and all other Minat unchanged and displays `MinatTransitionError.message` without identity details.
- Success creates exactly one `BookSwap` with `status=coordinating` and the accepted Minat's Sarang, marks accepted Minat/resolution time, and reserves both copies.
- Every other pending Minat with either copy in either requested/offered role becomes `automatically_rejected` with one shared resolution time.
- Unrelated pending Minat remain pending.
- Acceptance notifications go separately to both accepted participants; one notification is attempted per automatically rejected Minat after commit.
- A patched delivery failure cannot undo acceptance/reservation/rejection.
- Repeating acceptance creates no second Tukar.

Use PostgreSQL `TransactionTestCase`, a `Barrier`, and per-thread connection cleanup for the race:

```python
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connection
from django.test import TransactionTestCase


class ConcurrentAcceptanceTests(TransactionTestCase):
    reset_sequences = True

    def worker(self, minat_id, barrier):
        close_old_connections()
        try:
            recipient = get_user_model().objects.get(pk=self.recipient.pk)
            barrier.wait()
            try:
                swap = accept_minat(minat_id=minat_id, recipient=recipient)
                return ("accepted", swap.pk)
            except MinatTransitionError:
                return ("refused", None)
        finally:
            close_old_connections()

    def test_same_copy_can_be_reserved_by_only_one_concurrent_acceptance(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda minat_id: self.worker(minat_id, barrier),
                    [self.first.pk, self.second.pk],
                )
            )

        self.assertCountEqual([result[0] for result in results], ["accepted", "refused"])
        self.assertEqual(BookSwap.objects.count(), 1)
        self.shared_copy.refresh_from_db()
        self.assertEqual(
            self.shared_copy.availability_status,
            BookCopy.Availability.RESERVED,
        )
        self.assertCountEqual(
            Minat.objects.values_list("status", flat=True),
            [Minat.Status.ACCEPTED, Minat.Status.AUTOMATICALLY_REJECTED],
        )
```

`setUp()` creates two pending Minat sharing one copy and distinct other copies. Assert `connection.vendor == "postgresql"` at test start so this test cannot silently run with weaker SQLite locking.

- [ ] **Step 2: Run acceptance tests and verify RED**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_acceptance --verbosity 2
```

Expected: failures because `accept_minat()` and `swaps:minat_accept` do not exist.

- [ ] **Step 3: Implement acceptance with deterministic locks and complete revalidation**

Add this service body, using the Task 3 helpers and locked exception classes:

```python
@transaction.atomic
def accept_minat(*, minat_id: int, recipient: User) -> BookSwap:
    seed = (
        Minat.objects.filter(pk=minat_id, recipient=recipient)
        .values(
            "requester_id", "recipient_id", "requested_copy_id",
            "offered_copy_id", "swap_zone_id",
        )
        .first()
    )
    if seed is None:
        raise MinatTransitionError

    users = _lock_users(seed["requester_id"], seed["recipient_id"])
    copies = _lock_copies(seed["requested_copy_id"], seed["offered_copy_id"])
    copy_ids = sorted(copies)
    conflict = Q(requested_copy_id__in=copy_ids) | Q(offered_copy_id__in=copy_ids)
    locked_minat = {
        item.pk: item
        for item in Minat.objects.select_for_update()
        .filter(Q(pk=minat_id) | (Q(status=Minat.Status.PENDING) & conflict))
        .order_by("pk")
    }

    minat = locked_minat.get(minat_id)
    requester = users.get(seed["requester_id"])
    recipient = users.get(seed["recipient_id"])
    requested = copies.get(seed["requested_copy_id"])
    offered = copies.get(seed["offered_copy_id"])
    if (
        minat is None
        or minat.status != Minat.Status.PENDING
        or requester is None
        or recipient is None
        or not requester.is_active
        or not recipient.is_active
        or requested is None
        or offered is None
        or requested.owner_id != recipient.pk
        or offered.owner_id != requester.pk
        or requested.availability_status != BookCopy.Availability.AVAILABLE
        or offered.availability_status != BookCopy.Availability.AVAILABLE
        or not _zone_is_shared(
            swap_zone_id=minat.swap_zone_id,
            first_user_id=requester.pk,
            second_user_id=recipient.pk,
        )
    ):
        raise MinatTransitionError

    resolved_at = timezone.now()
    minat.status = Minat.Status.ACCEPTED
    minat.resolved_at = resolved_at
    minat.save(update_fields=["status", "resolved_at", "updated_at"])
    swap = BookSwap.objects.create(
        minat=minat,
        swap_zone_id=minat.swap_zone_id,
        status=BookSwap.Status.COORDINATING,
    )
    for copy in (requested, offered):
        copy.availability_status = BookCopy.Availability.RESERVED
        copy.save(update_fields=["availability_status", "updated_at"])

    automatically_rejected_ids = []
    for other in locked_minat.values():
        if other.pk != minat.pk and other.status == Minat.Status.PENDING:
            other.status = Minat.Status.AUTOMATICALLY_REJECTED
            other.resolved_at = resolved_at
            other.save(update_fields=["status", "resolved_at", "updated_at"])
            automatically_rejected_ids.append(other.pk)

    transaction.on_commit(lambda: notify_accepted_minat(minat_id=minat.pk))
    for rejected_id in automatically_rejected_ids:
        transaction.on_commit(
            lambda rejected_id=rejected_id: notify_rejected_minat(
                minat_id=rejected_id, automatic=True
            )
        )
    return swap
```

The default-argument capture on the automatic-rejection lambda is required; without it, every callback would notify the final ID.

- [ ] **Step 4: Add the authorized POST view and accepted Lini link**

The view first scopes `Minat(pk, recipient=request.user)` with `get_object_or_404()`, then calls `accept_minat()`. On success it emits `"Minat diterima. Tukar ini siap dikoordinasikan."` and redirects to `swaps:minat_detail` for the accepted Minat. Task 7 changes that redirect to `swaps:swap_detail` in the same commit that adds the Tukar view and route.

Add the `minat_accept` route and render `Terima` only to the recipient while pending in the same commit. In `Riwayat`, accepted rows render `Diterima`; Task 7 adds the live Tukar link.

- [ ] **Step 5: Run acceptance and related regression tests; verify GREEN**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_acceptance swaps.tests.test_creation swaps.tests.test_lini --verbosity 2
```

Expected: all pass on PostgreSQL; exactly one thread accepts; no deadlock occurs; one Tukar exists; both accepted copies are reserved; every conflict is automatically rejected; callbacks run only after commit.

- [ ] **Step 6: Commit Task 5**

```bash
git add swaps/services.py swaps/views.py swaps/urls.py templates/swaps/minat_detail.html templates/swaps/lini.html swaps/tests/test_acceptance.py
git commit -m "Accept Minat atomically"
```

---

### Task 6: Integrate Shelf Transitions and Administrative Deactivation

**Files:**
- Modify: `swaps/services.py`
- Modify: `books/views.py`
- Modify: `templates/books/shelf.html`
- Modify: `accounts/admin.py`
- Create: `swaps/tests/test_shelf_integration.py`
- Create: `swaps/tests/test_deactivation.py`
- Modify: `books/tests/test_shelf.py`

**Interfaces:**
- Consumes: Task 5 lock order and automatic-rejection notification behavior, existing shelf routes, existing `AccountUserAdmin`.
- Produces: `update_book_copy()`, `delete_book_copy()`, `deactivate_account()`, reserved/history guards, and service-routed Admin deactivation with no member deactivation page.

- [ ] **Step 1: Write failing shelf-transition and deactivation tests**

Create `swaps/tests/test_shelf_integration.py` to prove:

- `available -> unavailable` rejects every pending Minat involving the copy in either role, records `resolved_at`, and schedules one automatic-rejection email per Minat.
- `unavailable -> available` changes no Minat.
- A reserved copy cannot be edited, hidden, or deleted by GET or POST member flows.
- A copy with any historical Minat cannot be deleted because protected history must remain.
- A copy with no Minat remains deletable.
- A member cannot POST `reserved` because both forms reject that choice before service invocation.
- Notification failure leaves the copy unavailable and Minat automatically rejected.

Create `swaps/tests/test_deactivation.py` to prove:

- Deactivation sets `is_active=False` and automatically rejects all pending sent and received Minat.
- Deactivation leaves resolved Minat and historical Tukar intact.
- Deactivation is refused while the user is requester or recipient in a coordinating BookSwap, leaving account and Minat unchanged.
- The Django Admin change form renders existing `is_active` as read-only.
- The `deactivate_accounts` Admin action calls `swaps.services.deactivate_account()` and never performs `queryset.update(is_active=False)`.
- The Admin action reports refused unfinished accounts without deactivating them.
- No account deactivation URL exists in `accounts.urls`.

Representative Admin assertion:

```python
    @patch("accounts.admin.deactivate_account")
    def test_admin_deactivation_action_routes_every_account_through_service(self, deactivate):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "deactivate_accounts",
                "_selected_action": [self.member.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        deactivate.assert_called_once_with(user_id=self.member.pk)
```

- [ ] **Step 2: Run integration tests and verify RED**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_shelf_integration swaps.tests.test_deactivation books.tests.test_shelf --verbosity 2
```

Expected: failures because service-owned copy transitions, reserved/history guards, and service-routed Admin deactivation do not exist.

- [ ] **Step 3: Implement shared automatic rejection and copy services**

Add a private helper that assumes involved Minat rows are already locked in primary-key order:

```python
def _automatically_reject_locked(minat_rows, *, resolved_at):
    rejected_ids = []
    for minat in minat_rows:
        if minat.status == Minat.Status.PENDING:
            minat.status = Minat.Status.AUTOMATICALLY_REJECTED
            minat.resolved_at = resolved_at
            minat.save(update_fields=["status", "resolved_at", "updated_at"])
            rejected_ids.append(minat.pk)
    return rejected_ids


def _schedule_automatic_rejections(minat_ids):
    for minat_id in minat_ids:
        transaction.on_commit(
            lambda minat_id=minat_id: notify_rejected_minat(
                minat_id=minat_id, automatic=True
            )
        )
```

Refactor Task 5 acceptance to call these helpers, preserving behavior. Implement copy update/delete:

```python
@transaction.atomic
def update_book_copy(
    *, copy_id: int, owner: User, condition: str, condition_note: str,
    availability_status: str,
) -> BookCopy:
    users = _lock_users(owner.pk)
    copies = _lock_copies(copy_id)
    locked_owner = users.get(owner.pk)
    copy = copies.get(copy_id)
    if locked_owner is None or copy is None or copy.owner_id != locked_owner.pk:
        raise BookCopy.DoesNotExist
    if copy.availability_status == BookCopy.Availability.RESERVED:
        raise ReservedCopyError
    if availability_status not in {
        BookCopy.Availability.AVAILABLE,
        BookCopy.Availability.UNAVAILABLE,
    }:
        raise ReservedCopyError

    reject_ids = []
    if (
        copy.availability_status == BookCopy.Availability.AVAILABLE
        and availability_status == BookCopy.Availability.UNAVAILABLE
    ):
        pending = list(
            Minat.objects.select_for_update()
            .filter(
                Q(requested_copy=copy) | Q(offered_copy=copy),
                status=Minat.Status.PENDING,
            )
            .order_by("pk")
        )
        reject_ids = _automatically_reject_locked(
            pending, resolved_at=timezone.now()
        )

    copy.condition = condition
    copy.condition_note = condition_note
    copy.availability_status = availability_status
    copy.save(
        update_fields=[
            "condition", "condition_note", "availability_status", "updated_at"
        ]
    )
    _schedule_automatic_rejections(reject_ids)
    return copy


@transaction.atomic
def delete_book_copy(*, copy_id: int, owner: User) -> None:
    users = _lock_users(owner.pk)
    copies = _lock_copies(copy_id)
    copy = copies.get(copy_id)
    if users.get(owner.pk) is None or copy is None or copy.owner_id != owner.pk:
        raise BookCopy.DoesNotExist
    if copy.availability_status == BookCopy.Availability.RESERVED:
        raise ReservedCopyError
    if copy.requested_in_minat.exists() or copy.offered_in_minat.exists():
        raise HistoricalCopyError
    copy.delete()
```

- [ ] **Step 4: Route shelf edit/delete through services and guard reserved GET pages**

Keep `BookCopyForm` responsible for field validation. In `copy_edit`, redirect an owner away from the GET form when reserved; on valid POST call `update_book_copy()` with cleaned scalar values and catch `ReservedCopyError`. In `copy_delete`, do the same GET guard and call `delete_book_copy()` on POST, catching `ReservedCopyError` and `HistoricalCopyError`. Error messages redirect to `books:shelf`; no raw `ProtectedError` reaches the member.

In `shelf.html`, show `Dipesan untuk Tukar` as text and do not render `Ubah` or `Hapus` links when `availability_status == "reserved"`. This UI guard supplements, but never replaces, service enforcement.

- [ ] **Step 5: Implement transactional account deactivation**

Add to `swaps/services.py`:

```python
@transaction.atomic
def deactivate_account(*, user_id: int) -> User:
    user = User.objects.select_for_update().get(pk=user_id)
    related_minat = list(
        Minat.objects.select_for_update()
        .filter(Q(requester=user) | Q(recipient=user))
        .order_by("pk")
    )
    pending = [
        minat for minat in related_minat if minat.status == Minat.Status.PENDING
    ]
    unfinished = list(
        BookSwap.objects.select_for_update()
        .filter(
            Q(minat__requester=user) | Q(minat__recipient=user),
            status=BookSwap.Status.COORDINATING,
        )
        .order_by("pk")
    )
    if unfinished:
        raise UnfinishedSwapError

    rejected_ids = _automatically_reject_locked(
        pending, resolved_at=timezone.now()
    )
    user.is_active = False
    user.save(update_fields=["is_active"])
    _schedule_automatic_rejections(rejected_ids)
    return user
```

Acceptance locks both participant users before copies, so the deactivation race resolves safely: deactivation first makes acceptance fail revalidation; acceptance first creates a coordinating BookSwap that makes deactivation refuse.

- [ ] **Step 6: Route Django Admin deactivation through the service**

In `accounts/admin.py`, import `deactivate_account` and `UnfinishedSwapError`. Set `readonly_fields = (*UserAdmin.readonly_fields, "is_active")` on `AccountUserAdmin` so inherited read-only `last_login` and `date_joined` remain protected, keep `is_active` visible in the existing fieldset, and define these actions:

```python
@admin.action(description="Nonaktifkan akun terpilih")
def deactivate_accounts(self, request, queryset):
    deactivated = 0
    refused = 0
    for user_id in queryset.order_by("pk").values_list("pk", flat=True):
        try:
            deactivate_account(user_id=user_id)
        except UnfinishedSwapError:
            refused += 1
        else:
            deactivated += 1
    if deactivated:
        self.message_user(request, f"{deactivated} akun dinonaktifkan.", messages.SUCCESS)
    if refused:
        self.message_user(
            request,
            f"{refused} akun masih memiliki Tukar yang belum selesai.",
            messages.ERROR,
        )


@admin.action(description="Aktifkan akun terpilih")
def activate_accounts(self, request, queryset):
    activated = queryset.filter(is_active=False).update(is_active=True)
    if activated:
        self.message_user(request, f"{activated} akun diaktifkan.", messages.SUCCESS)
```

Set `actions = ("deactivate_accounts", "activate_accounts")`. Add a test proving activation remains available through this explicit safe action. Do not call `queryset.update(is_active=False)`, do not save a changed `is_active=False` form value, and do not add a member-facing route. Existing-account `is_active` is read-only specifically so the unsafe direct checkbox path cannot bypass Minat cleanup or the unfinished-Tukar guard.

- [ ] **Step 7: Run integration, Admin, acceptance, and shelf tests; verify GREEN**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_shelf_integration swaps.tests.test_deactivation swaps.tests.test_acceptance books.tests.test_shelf --verbosity 2
```

Expected: all pass; automatic rejection is complete and post-commit; reserved/history protections are enforced server-side; Admin deactivation goes only through the service; coordinating Tukar blocks deactivation.

- [ ] **Step 8: Commit Task 6**

```bash
git add swaps/services.py books/views.py templates/books/shelf.html accounts/admin.py swaps/tests/test_shelf_integration.py swaps/tests/test_deactivation.py books/tests/test_shelf.py
git commit -m "Protect shelf and account transitions"
```

---

### Task 7: Add Participant-Only Tukar UI and Complete Phase 5 Verification

**Files:**
- Modify: `swaps/views.py`
- Modify: `swaps/urls.py`
- Modify: `templates/swaps/lini.html`
- Create: `templates/swaps/swap_list.html`
- Create: `templates/swaps/swap_detail.html`
- Modify: `templates/base.html`
- Create: `swaps/tests/test_tukar.py`
- Modify: `swaps/tests/test_creation.py`
- Modify: `swaps/tests/test_lini.py`
- Modify: `swaps/tests/test_acceptance.py`
- Modify only for a demonstrated browser defect with a new failing test: `static/css/sarangbuku.css`, Phase 5 templates, or affected Phase 5 Python files.

**Interfaces:**
- Consumes: accepted `BookSwap` rows and all previous task routes/services.
- Produces: `swaps:swap_list`, `swaps:swap_detail`, accepted-only participant identity reveal, Lini-to-Tukar link, navigation, and complete automated/browser evidence.

- [ ] **Step 1: Write failing Tukar privacy, content, navigation, and accepted-link tests**

Create `swaps/tests/test_tukar.py`. Assert:

- Anonymous list/detail requests redirect to login.
- Only requester and recipient can list/open a BookSwap; another active member gets 404.
- The list contains only accepted Tukar involving the signed-in member, newest first.
- Detail reveals both display names, both book titles/authors/conditions/notes, and the stored `BookSwap.swap_zone`.
- Detail never reveals either email address, owner profile link, other copy, phone/address/schedule data, or precise location.
- Changing either participant's current `swap_zones` does not change the displayed accepted Sarang.
- Detail has no coordination, cancellation, handover, confirmation, problem, message, or disabled future control.
- Accepted Minat in `Riwayat` links to exactly its `BookSwap`; other resolved states do not.
- Authenticated navigation contains `Temukan`, `Lemari`, `Tambah`, `Daftar Minat`, `Lini`, `Tukar`, `Profil` and uses real links.
- Main Phase 5 templates have one `<h1>`, logical section headings, visible form labels, CSRF forms, and no wide-table overflow pattern.

Representative privacy test:

```python
    def test_participants_see_names_but_never_contact_data(self):
        for participant in (self.requester, self.recipient):
            with self.subTest(participant=participant.pk):
                self.client.force_login(participant)
                response = self.client.get(
                    reverse("swaps:swap_detail", args=[self.swap.pk])
                )
                self.assertContains(response, self.requester.display_name)
                self.assertContains(response, self.recipient.display_name)
                self.assertNotContains(response, self.requester.email)
                self.assertNotContains(response, self.recipient.email)

        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(reverse("swaps:swap_detail", args=[self.swap.pk])).status_code,
            404,
        )
```

- [ ] **Step 2: Run Tukar tests and verify RED**

Run:

```bash
.venv/bin/python manage.py test swaps.tests.test_tukar --verbosity 2
```

Expected: URL reversal/template failures because Tukar list/detail are not implemented.

- [ ] **Step 3: Implement participant-scoped Tukar views and routes**

Add one shared read queryset and two thin views:

```python
def _participant_swaps(user):
    return (
        BookSwap.objects.filter(
            Q(minat__requester=user) | Q(minat__recipient=user),
            minat__status=Minat.Status.ACCEPTED,
        )
        .select_related(
            "minat__requester",
            "minat__recipient",
            "minat__requested_copy__book",
            "minat__offered_copy__book",
            "swap_zone",
        )
        .distinct()
    )


@login_required
def swap_list(request):
    return render(
        request,
        "swaps/swap_list.html",
        {"swaps": _participant_swaps(request.user)},
    )


@login_required
def swap_detail(request, pk):
    swap = get_object_or_404(_participant_swaps(request.user), pk=pk)
    return render(request, "swaps/swap_detail.html", {"swap": swap})
```

Declare both locked routes. Change successful acceptance to redirect directly to `swaps:swap_detail`.

- [ ] **Step 4: Render Tukar pages, accepted Lini link, and navigation**

Use one `<h1>Tukar</h1>` on the list and one book-specific `<h1>` on detail. Show the two participant display names only through `swap.minat.requester.display_name` and `swap.minat.recipient.display_name`. Show both books, condition text, optional notes, and `swap.swap_zone.name/description`. Do not render emails or links to profiles/shelves.

In `Riwayat`, use the one-to-one relation only for accepted rows:

```django
{% if minat.status == "accepted" %}
  <a class="btn btn-sm btn-outline-primary" href="{% url 'swaps:swap_detail' minat.book_swap.pk %}">Lihat Tukar</a>
{% endif %}
```

Add `Lini` and `Tukar` links to the authenticated block in `templates/base.html` after `Daftar Minat` and before `Profil`. Keep the existing wrapping flex navigation and existing skip link.

- [ ] **Step 5: Run the complete automated matrix and verify GREEN**

Run from the repository root:

```bash
.venv/bin/python manage.py test books accounts swaps config --verbosity 2
.venv/bin/python manage.py test --verbosity 2
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python -m pip check
git diff --check
```

Expected: every command exits 0; PostgreSQL concurrency tests execute rather than skip; no migration drift or dependency error exists; static collection succeeds; the full pre-Phase-5 suite remains green.

- [ ] **Step 6: Seed disposable QA data and start a disposable server**

Use a unique email prefix so cleanup is exact:

```bash
.venv/bin/python manage.py shell <<'PY'
from django.db.models import Q

from accounts.models import SwapZone, User
from books.models import Book, BookCopy
from swaps.models import BookSwap, Minat
from swaps.services import accept_minat, create_minat

prefix = "phase5qa-"
old_user_ids = list(
    User.objects.filter(email__startswith=prefix).values_list("pk", flat=True)
)
BookSwap.objects.filter(
    Q(minat__requester_id__in=old_user_ids) | Q(minat__recipient_id__in=old_user_ids)
).delete()
Minat.objects.filter(
    Q(requester_id__in=old_user_ids) | Q(recipient_id__in=old_user_ids)
).delete()
BookCopy.objects.filter(owner_id__in=old_user_ids).delete()
User.objects.filter(pk__in=old_user_ids).delete()
Book.objects.filter(title__startswith="Phase 5 QA ").delete()
SwapZone.objects.filter(name="Phase 5 QA Blok M").delete()

zone = SwapZone.objects.create(
    name="Phase 5 QA Blok M",
    description="Bertemu di lobi utama.",
    is_active=True,
)
requester = User.objects.create_user(
    email=f"{prefix}requester@example.com",
    password="Phase5-QA-password",
    display_name="QA Peminta",
)
recipient = User.objects.create_user(
    email=f"{prefix}recipient@example.com",
    password="Phase5-QA-password",
    display_name="QA Penerima",
)
outsider = User.objects.create_user(
    email=f"{prefix}outsider@example.com",
    password="Phase5-QA-password",
    display_name="QA Orang Lain",
)
requester.swap_zones.add(zone)
recipient.swap_zones.add(zone)
outsider.swap_zones.add(zone)
requested_book = Book.objects.create(
    title="Phase 5 QA Diminta", authors="Penulis Penerima", language="Indonesia"
)
offered_book = Book.objects.create(
    title="Phase 5 QA Ditawarkan", authors="Penulis Peminta", language="Indonesia"
)
second_book = Book.objects.create(
    title="Phase 5 QA Cadangan", authors="Penulis Cadangan", language="Indonesia"
)
available_requested_book = Book.objects.create(
    title="Phase 5 QA Masih Tersedia", authors="Penulis Penerima", language="Indonesia"
)
requested = BookCopy.objects.create(
    owner=recipient, book=requested_book, condition=BookCopy.Condition.GOOD,
    condition_note="Sampul sedikit terlipat.",
)
offered = BookCopy.objects.create(
    owner=requester, book=offered_book, condition=BookCopy.Condition.VERY_GOOD,
)
second = BookCopy.objects.create(
    owner=requester, book=second_book, condition=BookCopy.Condition.FAIR,
)
available_requested = BookCopy.objects.create(
    owner=recipient,
    book=available_requested_book,
    condition=BookCopy.Condition.LIKE_NEW,
)
pending = create_minat(
    requester=requester,
    requested_copy_id=requested.pk,
    offered_copy_id=offered.pk,
    swap_zone_id=zone.pk,
)
accepted = create_minat(
    requester=requester,
    requested_copy_id=requested.pk,
    offered_copy_id=second.pk,
    swap_zone_id=zone.pk,
)
accept_minat(minat_id=accepted.pk, recipient=recipient)
print(
    {
        "automatically_rejected": pending.pk,
        "accepted": accepted.pk,
        "available_requested": available_requested.pk,
        "available_offered": offered.pk,
    }
)
PY

.venv/bin/python manage.py runserver 127.0.0.1:8000 >/tmp/sarangbuku-phase5-server.log 2>&1 & echo $! >/tmp/sarangbuku-phase5-server.pid
```

Expected: the shell prints integer IDs and the server responds at `http://127.0.0.1:8000/`. The accepted QA action automatically rejects the conflicting pending row. Through `Temukan`, use `available_requested` and offer `available_offered` to create one non-conflicting pending Minat that exercises `Ditunggu` and `Menunggu`.

- [ ] **Step 7: Run mobile and desktop browser QA with diagnostics**

Use native `agent_browser`, not direct shell browser commands. Log in as each QA participant through the real form. For each viewport, run:

```json
{"args":["set","viewport","390","844"]}
{"qa":{"url":"http://127.0.0.1:8000/lini/","expectedText":["Lini","Ditunggu","Menunggu","Riwayat"],"screenshotPath":"/tmp/sarangbuku-phase5-mobile.png","checkConsole":true,"checkErrors":true,"checkNetwork":true}}
{"args":["a11y","--tags","wcag2a,wcag2aa"]}
{"args":["snapshot","-i","--viewport"]}
```

```json
{"args":["set","viewport","1280","900"]}
{"qa":{"url":"http://127.0.0.1:8000/tukar/","expectedText":"Tukar","screenshotPath":"/tmp/sarangbuku-phase5-desktop.png","checkConsole":true,"checkErrors":true,"checkNetwork":true}}
{"args":["a11y","--tags","wcag2a,wcag2aa"]}
{"args":["snapshot","-i","--viewport"]}
```

At both 390×844 and 1280×900, verify with real GET/POST interactions:

1. Navigation wraps without clipping and real links reach `Temukan`, `Lini`, and `Tukar`.
2. Eligible discovery detail shows `Ajukan Minat` and still shows no owner name, email, profile, other copy, contact data, schedule, address, or precise location.
3. The create form fixes the requested copy, offers only the requester's available copies, omits reserved copies, and offers only active shared Sarang.
4. Tampered copy/Sarang values show field-associated Indonesian errors; stale creation shows the privacy-safe service message.
5. A new request appears for the requester under `Menunggu` and recipient under `Ditunggu`; neither side sees the other's identity.
6. `Batal` exists only for the requester; `Tolak` and `Terima` exist only for the recipient; each mutation uses POST and CSRF.
7. Rejected, withdrawn, and automatically rejected rows remain under `Riwayat` with exact labels and no identity reveal.
8. Acceptance creates one Tukar, reserves both copies, automatically rejects all conflicts, and reveals both display names only on participant-authorized Tukar pages.
9. The outsider receives 404 for Minat and Tukar detail URLs and sees no rows in Lini/Tukar lists.
10. A reserved copy shows `Dipesan untuk Tukar`, has no edit/delete controls, and direct edit/delete GET/POST attempts cannot mutate it.
11. Tukar pages show both books, conditions, accepted Sarang, and no coordination/message/cancel/handover/problem/future controls.
12. Use repeated `press Tab` and `press Shift+Tab` to reach every interactive control in logical order. Confirm visible focus with:

```json
{"args":["eval","--stdin"],"stdin":"(() => { const e = document.activeElement; const s = getComputedStyle(e); return { tag: e.tagName, text: (e.innerText || e.getAttribute('aria-label') || '').trim(), outlineStyle: s.outlineStyle, outlineWidth: s.outlineWidth }; })()"}
```

13. Confirm no horizontal overflow with:

```json
{"args":["eval","--stdin"],"stdin":"({ innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth, overflow: document.documentElement.scrollWidth > window.innerWidth })"}
```

14. Treat every actionable console error, page error, failed document/script request, WCAG A/AA violation, invisible focus, contrast failure, or overflow as a defect. A missing development favicon may be recorded as benign only when diagnostics classify it as a low-impact icon request.

Re-snapshot after every navigation or state mutation. Save both screenshots and verify `details.artifactVerification` before claiming evidence exists.

- [ ] **Step 8: Fix only demonstrated defects with a RED test, then re-run all evidence**

For each defect from Steps 5–7:

1. Add one focused automated test that reproduces the shared root cause.
2. Run its exact test label with `.venv/bin/python manage.py test` and record the expected failure.
3. Apply the smallest fix in the responsible file from the responsibility map.
4. Re-run the focused test, its task module, the full suite, both viewport checks, diagnostics, and accessibility audit.

Do not add CSS, JavaScript, fields, routes, or abstractions for hypothetical defects.

- [ ] **Step 9: Clean QA state, server, and artifacts**

Run:

```bash
kill "$(cat /tmp/sarangbuku-phase5-server.pid)"
.venv/bin/python manage.py shell <<'PY'
from django.db.models import Q

from accounts.models import SwapZone, User
from books.models import Book, BookCopy
from swaps.models import BookSwap, Minat

user_ids = list(
    User.objects.filter(email__startswith="phase5qa-").values_list("pk", flat=True)
)
BookSwap.objects.filter(
    Q(minat__requester_id__in=user_ids) | Q(minat__recipient_id__in=user_ids)
).delete()
Minat.objects.filter(
    Q(requester_id__in=user_ids) | Q(recipient_id__in=user_ids)
).delete()
BookCopy.objects.filter(owner_id__in=user_ids).delete()
User.objects.filter(pk__in=user_ids).delete()
Book.objects.filter(title__startswith="Phase 5 QA ").delete()
SwapZone.objects.filter(name="Phase 5 QA Blok M").delete()
assert not User.objects.filter(email__startswith="phase5qa-").exists()
assert not Book.objects.filter(title__startswith="Phase 5 QA ").exists()
assert not SwapZone.objects.filter(name="Phase 5 QA Blok M").exists()
PY
rm -f /tmp/sarangbuku-phase5-server.pid /tmp/sarangbuku-phase5-server.log /tmp/sarangbuku-phase5-mobile.png /tmp/sarangbuku-phase5-desktop.png
```

The cleanup order is mandatory because protected exchange history must be removed before QA copies, users, books, and Sarang. Close the native browser session after artifact verification. Confirm no QA rows remain and `git status --short` lists only intentional source changes.

- [ ] **Step 10: Run the final completion gate and commit demonstrated corrections**

Run:

```bash
.venv/bin/python manage.py test --verbosity 2
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python -m pip check
git diff --check
git status --short
```

Expected: all verification commands exit 0; no QA process/data/artifact remains; status contains only intended Phase 5 source changes.

Commit Task 7 and any browser-proven correction together:

```bash
git add swaps/views.py swaps/urls.py templates/swaps/lini.html templates/swaps/swap_list.html templates/swaps/swap_detail.html templates/base.html swaps/tests/test_tukar.py swaps/tests/test_creation.py swaps/tests/test_lini.py swaps/tests/test_acceptance.py static/css/sarangbuku.css
git commit -m "Add private Tukar views"
```

If `static/css/sarangbuku.css` did not change, Git ignores it. Do not create a separate empty verification commit.

## Completion Gate

Phase 5 is complete only when all of the following are evidenced:

- The reversible migration maps Boolean true/false to `available`/`unavailable`, rollback restores the Boolean values, and no runtime `is_available` reference remains.
- Member forms never offer or accept `reserved`.
- Exact pending duplicates are refused at validation and database-race boundaries while other combinations and resolved resubmission remain allowed.
- Both participants see each Minat only in the correct private Lini section with no pre-acceptance identity leak.
- `Batal`, `Tolak`, and `Terima` are role-correct authenticated CSRF POST actions; stale/unauthorized attempts cannot mutate state.
- Acceptance creates exactly one coordinating Tukar, stores the accepted Sarang, reserves both copies, and automatically rejects every conflict in one transaction.
- PostgreSQL thread races with barriers and per-thread `close_old_connections()` prove only one acceptance can reserve a shared copy.
- Available-to-unavailable transitions and account deactivation automatically reject all relevant pending Minat and attempt post-commit emails.
- Reserved copies cannot be edited, hidden, or deleted; historical copies cannot be deleted.
- Administrative deactivation cannot bypass `deactivate_account()` and is refused during any accepted unfinished coordinating Tukar.
- New, accepted, rejected, and automatically rejected notifications run after commit; delivery failures cannot undo state and logs contain no address, credential, body, or exception text.
- Only accepted participants see display names on Tukar pages; outsiders get 404 and emails remain private everywhere.
- No Phase 6 control or schema appears.
- Full automated, migration, dependency, static, diff, 390×844, 1280×900, keyboard, focus, contrast, overflow, privacy, console, page-error, and network checks pass after cleanup.
