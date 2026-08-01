# Phase 2 Accounts Design

## Goal

Allow invited visitors to create an account, sign in, recover access, and choose one or more administrator-managed Sarang. Registration and Sarang onboarding are separate steps: a successful registration signs the new user in and redirects immediately to Profil.

Book entry remains Phase 3. During Phase 2, Profil shows an unavailable book-entry card explaining that users will be able to add books after completing their Sarang selection.

## Scope

Phase 2 includes:

- Invitation generation and administration
- Invitation-only registration
- Login and logout
- Django's built-in password-reset flow
- Sarang administration
- Profile editing and multi-Sarang selection
- Session-aware navigation

Phase 2 excludes catalog records, physical book copies, discovery, invitations sent between users, phone numbers, precise coordinates, and home addresses.

## Data model

### Invitation

`accounts.Invitation` stores:

- A unique SHA-256 digest of a high-entropy invitation code
- Nullable expiration time
- Positive maximum usage count
- Nonnegative usage count
- Administrator-controlled active status
- The staff user who created it
- Creation and update timestamps

The usable code is never stored. It is available only when generated and in its delivery email.

### SwapZone

`accounts.SwapZone` stores:

- Name
- Public meeting guidance without precise coordinates or addresses
- Active status
- Creation and update timestamps

### User

`accounts.User` gains a many-to-many relation to `SwapZone`. No intermediary membership model is needed because zone selection has no additional metadata.

## Registration flow

1. Staff creates an invitation through Django Admin and provides a delivery email address.
2. The application generates a high-entropy code, stores only its digest, and sends the usable code by email.
3. A visitor submits the invitation code, email, display name, and password confirmation.
4. A service opens a database transaction and locks the matching invitation row.
5. The service rejects an unknown, expired, disabled, or exhausted invitation with the same user-facing error.
6. The service creates the user, increments invitation usage exactly once, and commits both changes together.
7. The view signs in the new user and redirects to Profil.

Registration does not collect Sarang. If validation or persistence fails, no account is created and invitation usage is unchanged.

## Profile and onboarding flow

Profil allows an authenticated user to:

- Edit display name
- Edit email while preserving case-insensitive uniqueness
- Select one or more active Sarang

Submitting zero Sarang or an inactive Sarang is rejected server-side. Existing selections of a Sarang later made inactive remain stored for history but are not presented as usable choices.

A newly registered user lands on Profil and must select at least one Sarang before the product's future exchange flows become useful. During Phase 2, login consistently redirects to Profil; later phases may redirect users who already have a Sarang to discovery.

Profil also displays an unavailable `Tambahkan Buku` card. It explains that book entry follows Sarang selection, but it does not create placeholder book models or routes.

## Authentication and password reset

Django's built-in authentication views and token machinery handle login, logout, and password reset.

Password reset follows this flow:

1. A visitor enters an email address.
2. The application always shows the same confirmation response to prevent account discovery.
3. Django sends active matching users a single-use signed reset link.
4. The user opens the link and submits a valid new password twice.
5. Django updates the password hash, invalidates the token, and redirects to login.

All pages and emails use natural conversational Indonesian. Invitation codes are not required for password reset.

## Pages and navigation

Pre-login pages:

- Landing
- Login
- Invitation registration
- Password-reset request, sent, confirmation, and completion

Authenticated page:

- Profil with account fields, Sarang selection, and unavailable book-entry card

The shared header shows login and registration links to signed-out visitors. It shows Profil and a POST logout control to signed-in users.

## Validation and security

- Invitation redemption uses `transaction.atomic()` and `select_for_update()` so concurrent requests cannot exceed `max_uses`.
- Database constraints enforce positive maximum usage and nonnegative usage.
- User email remains case-insensitively unique and is never shown to another user.
- Passwords use Django hashing and configured validators.
- Forms use CSRF protection, visible labels, appropriate autocomplete attributes, keyboard-accessible controls, and accessible error summaries.
- Invitation failures use one generic message instead of revealing invitation state.
- Password-reset responses do not reveal whether an account exists.
- Inactive users cannot sign in or receive a usable password-reset link.

## Administration

Authorized staff can manage users, invitations, and Sarang through Django Admin. The invitation creation form collects a recipient email without storing it, exposes the usable code only once, and sends it through Django email. Staff can disable invitations and Sarang without deleting historical records.

## Error handling

- Form errors remain attached to their fields and preserve safe submitted values.
- If synchronous invitation email sending fails, invitation creation fails and its database row is rolled back.
- A failed registration transaction does not consume invitation usage.
- Duplicate email registration and profile updates return a form error rather than a server error.
- Unknown, expired, disabled, and exhausted invitations share one conversational Indonesian error message.

## Testing

The smallest tests proving Phase 2 cover:

- High-entropy invitation generation, digest-only storage, and delivery email
- Valid redemption creates one user and increments usage once
- Unknown, expired, disabled, and exhausted invitations are rejected
- Concurrent redemption cannot exceed the usage limit
- Registration rollback preserves invitation usage
- Email normalization and case-insensitive uniqueness
- Login, POST logout, and inactive-user rejection
- Password-reset email and successful password replacement without account enumeration
- Multiple active Sarang can be selected; zero or inactive Sarang cannot
- Another user never sees an email address
- Registration redirects to Profil and Profil displays the unavailable book-entry card

Browser QA covers the registration, login, password-reset, and Profil flows at mobile and desktop widths, including labels, keyboard operation, focus visibility, validation messages, and contrast.
