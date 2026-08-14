# Phase 4 Wishlist and Discovery Design

**Date:** 2026-08-14
**Status:** Approved design

## Goal

Let an authenticated member privately record catalog entries they want and discover eligible copies from other members without exposing owner identity.

Phase 4 covers `Daftar Minat`, anonymous discovery, discovery filters, and anonymous copy details. Creating or managing a `Minat` remains Phase 5.

## Product decisions

- Phase 4 stays inside the existing `books` app.
- Wishlist additions use existing local `Book` records only.
- Open Library lookup and manual catalog creation remain part of the physical-copy entry flow, not the wishlist flow.
- Discovery details have no disabled or inactive `Minat` action.
- The discovery navigation and page label is `Temukan`.
- Phase 4 copy omits `Buku` wherever the surrounding context already makes the object clear.
- User-facing text remains natural Indonesian. Project documentation and collaboration remain English.

## Non-goals

Phase 4 does not add:

- `Minat` creation, acceptance, rejection, withdrawal, or notifications
- Owner identity or owner bookshelf access
- Coordination messages or handover behavior
- Open Library or manual entry from `Daftar Minat`
- A new Django app, search service, cache, search index, or JavaScript frontend

## Architecture

Wishlist and discovery remain in `books`, beside the existing `Book` and `BookCopy` models and views. This is the smallest boundary that matches the current modular monolith. A separate discovery app is deferred until discovery owns enough independent behavior to justify one.

Discovery is computed from local PostgreSQL data on each request. One shared discoverable-copy queryset is used by both the list and detail views so eligibility and privacy rules cannot drift between pages.

## Data model

Add `WishlistItem` with:

- `user`: foreign key to the configured user model
- `book`: foreign key to `Book`
- `created_at`: creation timestamp
- a database uniqueness constraint on `(user, book)`

A wishlist item represents one local catalog record, not a physical copy. Different editions represented by different `Book` records may be saved separately. Deleting a wishlist item never deletes its catalog record. Foreign keys and the uniqueness constraint provide the required indexes; no speculative indexes are added.

The model is visible in Django Admin with user, title, author, and creation information sufficient for pilot support.

Discovery requires no new persisted model.

## Discovery eligibility

A copy is discoverable by a viewer only when all of these remain true at request time:

1. The viewer is authenticated and has at least one active Sarang.
2. The copy is available.
3. The owner account is active.
4. The owner is not the viewer.
5. The owner and viewer share at least one active Sarang.

The base queryset selects related book data, filters through the owners' active shared Sarang, and uses `distinct()` because two members may share multiple Sarang.

The detail view resolves its copy only through this same queryset. A copy that becomes unavailable, an owner who becomes inactive, a removed shared Sarang, an inactive Sarang, a self-owned copy, or an unknown identifier produces HTTP 404. This prevents stale URLs from bypassing discovery privacy.

## `Temukan`

`Temukan` is available under the existing `/buku/` URL namespace and appears in authenticated navigation.

The page may be browsed without a text query. GET parameters support:

- Search by title, author, or normalized ISBN
- One active Sarang shared with the viewer
- One canonical condition
- Wishlist matches only

Django forms validate and preserve filter values. Invalid filter choices show field errors and do not broaden the result set. Search and filtering read only local data.

Results use Django pagination. Each result may show:

- Cover or placeholder
- Title and author
- ISBN and language when available
- Condition and optional condition note
- Active Sarang shared with the viewer
- A private `Daftar Minat` match indicator

Each result links to a dedicated anonymous copy-detail page showing the same permitted information. Neither page renders the owner's display name, email address, contact information, schedule, precise location, other copies, or a link that could expose the owner.

The result and detail templates offer authenticated POST controls to add or remove the associated catalog record from `Daftar Minat`. They do not show a disabled future action.

## `Daftar Minat`

`Daftar Minat` is private to the authenticated user and appears in authenticated navigation.

The page:

- Lists the user's saved local catalog records
- Provides local catalog search using the existing title, author, and normalized ISBN behavior
- Caps and deterministically orders search results using the established local catalog pattern
- Allows adding and removing entries through POST requests
- Links each saved entry to `Temukan` filtered to matching available copies
- Shows clear empty states for no saved entries, no search results, and no discoverable matches

Adding an existing `(user, book)` pair is idempotent from the user's perspective and cannot create a duplicate because the database enforces uniqueness. Removal is scoped to the authenticated user's item; another user's identifier cannot be used to remove it.

## Request and mutation behavior

All Phase 4 pages require login. Members without an active Sarang are redirected to `Profil`, matching the existing protected book flows.

Searches and filters use GET. Wishlist additions and removals use POST with Django CSRF protection. Successful mutations redirect to a validated local destination or the owning page and show concise Indonesian feedback. The implementation must not trust an arbitrary external `next` URL.

Expected missing or ineligible discovery records return 404 rather than revealing which privacy rule failed. Invalid forms render accessible field errors and retain safe submitted values.

## Interface and accessibility

The existing Django Templates and Bootstrap patterns remain in use. The design adds no frontend dependency and does not require HTMX.

Phase 4 pages must:

- Remain usable at narrow mobile widths without horizontal overflow
- Use visible form labels and native controls
- Preserve keyboard operation and visible focus states
- Associate validation errors with their fields
- Keep filters usable when navigation wraps
- Use adequate contrast

Authenticated navigation uses the concise labels `Temukan`, `Lemari`, `Tambah`, `Daftar Minat`, and `Profil`.

## Testing

Implementation follows test-driven development. The smallest tests proving each rule cover:

### Model and wishlist

- One user cannot save the same `Book` twice
- Different users may save the same `Book`
- Different local editions may be saved separately
- Adding an existing entry remains harmless
- Removal affects only the authenticated user's entry
- Wishlist pages and state are not visible to another user
- Anonymous and no-active-Sarang guards

### Discovery

- Available copies from active owners in a shared active Sarang appear
- Self-owned copies do not appear
- Unavailable copies do not appear
- Copies owned by inactive users do not appear
- Copies without a shared Sarang do not appear
- Inactive Sarang do not qualify
- Multiple shared Sarang do not duplicate a copy
- Search matches title, author, and normalized ISBN
- Sarang, condition, and wishlist filters work independently and together
- Invalid filters do not broaden results
- Pagination preserves active filters

### Detail privacy

- Eligible detail pages show only permitted catalog, condition, note, and shared-Sarang data
- Unknown and newly ineligible copy URLs return 404
- Rendered discovery HTML contains neither owner display name nor owner email
- Detail pages do not expose the owner's other copies
- No future `Minat` control is rendered

### Interface verification

- Navigation exposes `Temukan` and `Daftar Minat`
- Product copy follows the approved concise terminology
- Mobile and desktop browser checks cover layout, filters, empty states, forms, keyboard focus, and privacy-sensitive rendering
- Django system checks, migration drift checks, and the full existing test suite remain clean

## Acceptance criteria

Phase 4 is complete when an invited active member with an active Sarang can:

1. Search the local catalog and privately add or remove a `Daftar Minat` entry.
2. Browse and filter eligible anonymous copies from active members in a shared active Sarang.
3. Recognize private wishlist matches in discovery.
4. Open an eligible anonymous detail page without learning owner identity or seeing the owner's other copies.
5. Lose access immediately when a copy or relationship no longer satisfies discovery rules.
6. Use both flows on mobile and by keyboard.

At completion, no Phase 4 page creates a `Minat`, queries Open Library for wishlist use, or exposes personal contact or precise location data.
