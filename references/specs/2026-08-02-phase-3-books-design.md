# Phase 3 Books Design

## Goal

Let an authenticated user add physical books to Sarang Buku and manage them in a private `Lemari`, using the local catalog first, Open Library only when needed, and manual entry as a reliable fallback.

## Scope

Phase 3 includes:

- Local catalog records
- Physical book copies owned by users
- Local search by ISBN, title, or author
- Explicit Open Library fallback
- Manual catalog entry
- Copy condition, condition note, and availability
- The owner's private `Lemari`
- Adding, editing, and deleting unreferenced copies
- Django Admin support for catalog records and copies

Phase 3 excludes wishlist, discovery, Minat, reservations, ownership history, exchange side effects, and public book-detail pages.

## Architecture

Phase 3 stays in the existing `books` Django app. It uses Django models, forms, views, templates, and PostgreSQL, following the server-rendered patterns already used by `accounts`.

The app stores catalog metadata separately from each owned physical copy. Local catalog and `Lemari` pages read only local data. Open Library is contacted only when a user explicitly requests an external search.

No new dependency is required. The Open Library client uses Python's standard library with a short timeout and an identifying `User-Agent`.

## Data model

### Book

`Book` is a local bibliographic record with:

- `title`
- `authors`, stored as display-ready text
- `isbn`, optional and normalized by removing spaces and hyphens
- `language`
- `cover_url`, optional
- `created_at`
- `updated_at`

A nonempty ISBN must be a valid ISBN-10 or ISBN-13 and is unique. Records without an ISBN may coexist because title, author, and language alone cannot reliably identify an edition.

Imported Open Library metadata becomes an ordinary local `Book`. The application does not require Open Library to display it later.

### BookCopy

`BookCopy` represents one owned physical copy with:

- `owner`
- `book`
- `condition`
- `condition_note`, optional and limited to 140 characters
- `is_available`, defaulting to true
- `created_at`
- `updated_at`

Condition choices are:

1. Like new -> Seperti Baru
2. Very good -> Sangat Bagus
3. Good -> Masih Bagus
4. Fair -> Cukup Bagus
5. Bad -> Sudah Buruk

The Indonesian interface presents natural labels for these stored choices.

One user may own multiple copies of the same `Book`. Foreign keys protect catalog records and owners from accidental destructive deletion. Account deactivation remains soft deletion through `is_active=False`.

An owner may delete a copy while it has no related historical or active exchange record. Later swap phases will add the reservation and history protections required by the MVP.

## Access rules

All Phase 3 pages require authentication. A user may view, edit, hide, or delete only their own `BookCopy` rows.

Adding a book requires the user to have at least one selected active Sarang. A user without one is redirected to `Profil` with a conversational Indonesian message. This keeps book entry consistent with the onboarding sequence established in Phase 2.

`Lemari` is private in Phase 3. It is not a discovery page and does not reveal another user's books or identity.

## Book-entry flow

1. The unavailable profile card becomes an active `Tambah` link.
2. The authenticated navigation adds `Lemari` and `Tambah`.
3. The user searches by ISBN, title, or author.
4. Matching local `Book` records appear first.
5. The user may select a local record, explicitly search Open Library, or choose manual entry.
6. Selecting a result leads to the physical-copy form.
7. The user enters condition, an optional condition note, and availability.
8. The application validates and saves the catalog record when needed and the physical copy in one transaction.
9. Success redirects to `Lemari`.

External or manual metadata is not persisted before the final copy form succeeds, avoiding abandoned catalog records.

## Local search

Local search is case-insensitive across title and authors. ISBN input is normalized before exact matching. Empty or whitespace-only searches are rejected with a form error.

Results show cover or placeholder, title, authors, language, and ISBN when present. They do not expose owners or copy counts.

## Open Library integration

Open Library search is an explicit fallback rather than an automatic request on every local search. Requests use the official JSON Search API and request only the fields Phase 3 stores.

The client:

- Sends an identifying `User-Agent`
- Uses a bounded timeout
- Limits result count
- Normalizes missing and malformed fields
- Accepts only `http` or `https` cover URLs
- Maps cover identifiers to the official Covers API URL
- Never treats external response data as trusted input

ISBN searches preserve the matching ISBN. Title or author searches use the best matching edition data available; if no reliable ISBN is present, the imported local record leaves ISBN blank rather than attaching an arbitrary edition identifier.

A timeout, network failure, non-success response, invalid JSON response, or malformed result produces a conversational Indonesian error. Local search and manual entry remain available.

## Manual entry

Manual entry collects only:

- Title
- Authors
- ISBN, optional
- Language
- Cover URL, optional
- Physical-copy condition
- Optional condition note
- Availability

Manual and imported entries share the same server-side validators. When a valid ISBN already exists locally, the application reuses that `Book` rather than creating a duplicate.

## Lemari and copy management

`Lemari` shows every copy owned by the signed-in user, including unavailable copies. Each card shows:

- Cover or placeholder
- Title
- Authors
- Language
- ISBN when present
- Condition
- Condition note when present
- Availability

The empty state explains how to add the first book and provides a `Tambah` action.

An owner may edit condition, condition note, and availability. Catalog metadata is not edited through the copy form because it is shared by every copy using that `Book`.

Deletion requires POST and a confirmation page. It removes only the physical copy, not the shared catalog record. Catalog cleanup is an administrative concern and is not automated in Phase 3.

## Pages and URLs

The `books` app provides:

- `Lemari`: list the signed-in user's copies
- `Tambah`: local catalog search and entry choices
- Open Library results for the current search
- Physical-copy creation from a selected local or external record
- Manual book and copy entry
- Copy editing
- Copy deletion confirmation

User-facing page titles and controls use `Lemari` and `Tambah`, not `Buku Saya` or `Tambahkan Buku`.

## Validation and security

- Every form uses Django CSRF protection.
- Every mutation validates ownership server-side.
- ISBN validation checks format and checksum after normalization.
- Text fields have explicit length limits.
- Condition notes are limited to 140 characters.
- Cover URLs accept only `http` and `https` schemes.
- External response values pass through the same validation as manual values.
- Copy creation and any required catalog creation happen atomically.
- Deletion is POST-only after an explicit confirmation page.
- Templates escape external and user-entered text through Django defaults.

Forms provide visible labels, accessible error summaries, keyboard operation, visible focus, adequate contrast, and mobile layouts. User-facing copy follows EYD in natural conversational Indonesian and avoids em dashes.

## Administration

Django Admin registers `Book` and `BookCopy` with useful search and filters. Staff may inspect and correct local records, but normal users manage only their own copies through the product interface.

## Error handling

Validation errors preserve safe entered values and identify the affected field. Duplicate ISBN races are handled by reusing the existing local `Book` when valid.

Open Library failures do not block local search, manual entry, or existing `Lemari` pages. Unexpected persistence failures do not leave a `Book` without its intended `BookCopy` from the same submission.

Unauthorized copy identifiers return 404 rather than revealing whether another user's copy exists.

## Testing

Automated tests cover:

- `Book` and `BookCopy` fields, constraints, and deletion behavior
- ISBN-10 and ISBN-13 normalization, checksums, and uniqueness
- Multiple copies of one `Book`, including multiple copies by one owner
- Local search by title, author, and ISBN
- Open Library request parameters, mapping, result limits, timeout, invalid JSON, malformed data, and service failure without live network calls
- Manual entry and existing-ISBN reuse
- Transactional catalog and copy creation
- Active-Sarang requirement
- `Lemari` privacy and cross-user 404 responses
- Copy creation, editing, availability, and POST-only deletion
- Navigation labels and redirects
- Form labels, validation summaries, keyboard use, focus visibility, contrast, and mobile layout
- Full regression, migration drift, dependency integrity, and Django checks

Browser QA covers the complete local, Open Library, and manual flows at mobile and desktop widths. Open Library success may use a controlled fake response for deterministic QA, while one separate smoke check may verify the configured live endpoint.
