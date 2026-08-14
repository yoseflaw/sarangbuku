# Phase 5 Minat Design

## Goal

Let an eligible member offer exactly one available book for one anonymously discovered available book, let the recipient accept or reject without negotiation, and turn an accepted Minat into a reserved Tukar safely.

Phase 5 covers the Minat decision lifecycle. Coordination messages, cancellation after acceptance, handover confirmation, ownership transfer, problem reporting, and completed swap history remain for Phase 6.

## Product decisions

- The member-facing Minat list is named `Lini`.
- `Lini` groups received pending Minat under `Ditunggu`, sent pending Minat under `Menunggu`, and all resolved Minat under `Riwayat`.
- A requester cancels a pending sent Minat with the action label `Batal`.
- History labels are `Diterima`, `Ditolak`, `Dibatalkan`, and `Ditolak otomatis`.
- Resolved Minat remain visible to both participants.
- An accepted Minat remains in `Lini` under `Riwayat` and links to its separate `Tukar` record.
- Exact duplicate pending Minat are forbidden when requester, requested copy, offered copy, and Sarang all match. Other combinations remain allowed, and the same combination may be submitted again after resolution.
- No pagination or HTMX is needed for the invitation-only pilot.

## Non-goals

Phase 5 does not add:

- Pre-acceptance negotiation or messages
- Coordination messages
- Cancellation of accepted Tukar
- Handover confirmation or ownership transfer
- Problem reporting or administrative resolution actions
- Completed swap history
- Inactive controls or copy promising later functionality
- A new Django app, frontend dependency, task queue, cache, or speculative abstraction

## Architecture

All new exchange behavior belongs in the existing `swaps` app. Models persist state, forms validate user choices, views handle HTTP concerns, and transactional service functions in `swaps/services.py` own state transitions.

The service boundary is the only path for creating, cancelling, rejecting, or accepting a Minat. It is reusable from later administration behavior without coupling business rules to views.

Email helpers send notifications only after a successful database commit. They catch and log delivery failures without exposing email addresses or provider credentials and without rolling back valid product actions.

## Data model

### Book copy availability

Replace `BookCopy.is_available` with a status field whose values are:

- `available`: visible in discovery and eligible for Minat
- `reserved`: part of an accepted, unfinished Tukar
- `unavailable`: hidden from discovery

The data migration maps existing `True` values to `available` and `False` values to `unavailable`. Existing discovery, shelf, forms, administration, and tests must use the status field after the migration.

Members may switch their own copies between `available` and `unavailable`. Reserved copies cannot be edited, hidden, or removed.

### Minat

A Minat stores:

- Requester
- Recipient
- Requested book copy
- Offered book copy
- Selected Sarang
- Status: `pending`, `accepted`, `rejected`, `withdrawn`, or `automatically_rejected`
- Created and updated timestamps
- Resolution timestamp when it leaves `pending`

The recipient is stored explicitly so the original participants remain unambiguous in historical records even after later ownership transfers.

Database constraints prevent a copy from being requested in exchange for itself and prevent an exact duplicate pending Minat. Service validation enforces ownership, account, availability, recipient, and Sarang relationships that cannot be expressed safely as static database constraints.

### BookSwap

A BookSwap is linked one-to-one with its accepted Minat. In Phase 5 it stores its `coordination` status and timestamps. The accepted Minat already preserves the participants, copies, and Sarang, so BookSwap does not duplicate those fields.

Phase 6 may add fields required for coordination, confirmations, cancellation, problems, and completion. Phase 5 does not scaffold them early.

## Eligibility and privacy

A Minat may be created only when:

- Both accounts are active
- The requested copy belongs to the recipient and is `available`
- The offered copy belongs to the requester and is `available`
- Requester and recipient are different users
- Requested and offered copies are different
- The selected Sarang is active and belongs to both participants
- No identical pending Minat exists

The Minat creation form fixes the requested copy from the eligible `Temukan` detail. It limits the offered-copy choices to the requester's available copies and the Sarang choices to active zones shared with the recipient.

Before acceptance, both participants may see only the two books, their conditions and condition notes, the selected Sarang, timestamps, and Minat status. They must not see the other participant's display name, email, profile, bookshelf, or other books.

After acceptance, both display names are visible on the resulting Tukar. Rejected, withdrawn, and automatically rejected Minat never reveal identities.

Unauthorized or ineligible detail requests return 404 rather than revealing which privacy rule failed.

## Member flow

### Creating a Minat

An eligible `Temukan` detail shows `Ajukan Minat`. The requester chooses one offered copy and one shared active Sarang, reviews the fixed requested copy, and submits by POST with CSRF protection.

The creation service revalidates all eligibility rules inside a transaction. On success it creates one pending Minat, redirects to its private detail or `Lini`, shows concise Indonesian feedback, and sends a new-Minat email to the recipient after commit. The email does not reveal the requester.

### Lini

`Lini` contains three responsive sections:

- `Ditunggu`: received pending Minat requiring `Terima` or `Tolak`
- `Menunggu`: sent pending Minat allowing `Batal`
- `Riwayat`: accepted, rejected, withdrawn, and automatically rejected Minat involving the member

Each row or card links to a private Minat detail. Actions appear only for the authorized participant and only while the Minat is pending. Every mutation is an authenticated CSRF-protected POST.

Newest items appear first within each section. The pilot list is not paginated.

### Rejecting and cancelling

Only the recipient may reject a pending Minat. Rejection changes only that Minat and sends a rejection email to the requester after commit.

Only the requester may use `Batal` on a pending Minat. This records the model status `withdrawn`. The MVP email requirements do not require a withdrawal email.

### Accepting

Only the recipient may accept a pending Minat. The acceptance service locks the Minat and both book copies in deterministic order and revalidates:

- The Minat remains pending
- Both accounts remain active
- Both participants still own their respective copies
- Both copies remain `available`
- The selected Sarang remains active and shared

A successful acceptance performs one database transaction that:

1. Marks the Minat `accepted` and records its resolution time
2. Creates its BookSwap in `coordination`
3. Marks both copies `reserved`
4. Marks every other pending Minat involving either copy `automatically_rejected`

Locking the copies makes their `reserved` status the single exclusivity guard, so concurrent acceptances cannot claim the same copy. There is no separate reservation model.

After commit, both accepted participants receive acceptance emails. Every requester affected by automatic rejection receives an automatic-rejection email. The accepted Minat appears in `Riwayat` as `Diterima` and links to its Tukar detail.

### Making a copy unavailable

When an owner changes a copy from `available` to `unavailable`, the same service boundary automatically rejects every pending Minat involving that copy and sends the required emails after commit.

This behavior must be integrated with existing shelf mutations so it cannot be bypassed by a normal member flow.

## Error handling and concurrency

Expected stale or invalid transitions return a clear conversational Indonesian message and leave all records unchanged. The interface must not reveal hidden identity or eligibility details in error text.

Database row locks and status checks protect acceptance and availability changes from races. Lock acquisition uses deterministic copy order to reduce deadlock risk. Database constraint failures for duplicate pending Minat are converted into the same form-level duplicate message used by normal validation.

Email delivery happens after commit. Delivery exceptions are caught and logged with the notification type and record identifier, never an address or credential. A delivery failure does not change the successful HTTP product action.

## Interface and accessibility

Authenticated navigation adds `Lini` and `Tukar` while preserving the existing concise labels.

Lini and detail pages use existing Django Template and Bootstrap patterns. They must:

- Work without JavaScript
- Remain usable on narrow mobile screens without horizontal overflow
- Use one clear page heading and logical section headings
- Use visible labels and native controls
- Associate validation errors with their fields
- Keep action names explicit and status labels distinguishable without color alone
- Preserve keyboard operation, visible focus, and adequate contrast

Empty states explain the next useful action and link to `Temukan` where appropriate.

Tukar list and detail pages show accepted exchanges, both display names, both books, conditions, and Sarang. They contain no inactive coordination, cancellation, or handover controls in Phase 5.

## Administration

Django Admin registers Minat and BookSwap with useful list columns, filters, search, and read-only timestamps. Phase 5 administration is for inspection only; it adds no manual state-transition actions.

Historical Minat and accepted Tukar use protected relationships where deletion would destroy required exchange records.

## Testing

Implementation follows test-driven development with the smallest test proving each rule. Coverage includes:

- Availability-status schema and data migration
- Minat status and database constraints
- Exact pending-duplicate prevention
- Creation eligibility and form choice restrictions
- Pre-acceptance anonymity and participant-only access
- Authorized rejection and cancellation
- Atomic acceptance and Tukar creation
- Automatic rejection of every conflicting pending Minat
- Concurrent attempts involving the same copy
- Unavailable-copy automatic rejection
- Reserved-copy edit and availability protection
- Email events, concealed identities, and failure isolation
- Lini grouping, ordering, labels, actions, and empty states
- Accepted identity reveal only through participant-authorized Tukar pages
- Mobile and desktop browser flows, keyboard access, focus, contrast, and overflow
- Full Django test suite, system checks, migration checks, dependency checks, and diff checks

## Acceptance criteria

Phase 5 is complete when:

1. An eligible member can submit one valid one-for-one Minat from an anonymous discovery detail.
2. An exact duplicate pending Minat is refused without blocking other combinations.
3. Both participants can see the Minat in the correct private `Lini` section without identity leakage.
4. The requester can use `Batal` while the Minat is pending.
5. The recipient can reject a pending Minat without changing either copy's availability.
6. The recipient can atomically accept a still-valid Minat.
7. Acceptance creates one Tukar, reserves both copies, reveals both display names only to the participants, and automatically rejects every conflicting pending Minat.
8. Making an available copy unavailable automatically rejects its pending Minat.
9. Required new, accepted, rejected, and automatically rejected emails are attempted after commit, and delivery failure cannot undo product state.
10. Resolved Minat remain visible under `Riwayat`, and accepted Minat link to `Tukar`.
11. Reserved copies cannot be edited, hidden, or removed through member flows.
12. The complete feature remains private, accessible, mobile-usable, and safe under concurrent acceptance attempts.
