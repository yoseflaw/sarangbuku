from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import SwapZone, User
from books.models import BookCopy

from .models import BookSwap, Minat
from .notifications import notify_accepted_minat, notify_new_minat, notify_rejected_minat

PENDING_DUPLICATE_CONSTRAINT = "swaps_minat_unique_pending_combination"


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
    transaction.on_commit(lambda: notify_rejected_minat(minat_id=minat.pk, automatic=False))
    return minat


@transaction.atomic
def accept_minat(*, minat_id: int, recipient: User) -> BookSwap:
    seed = (
        Minat.objects.filter(pk=minat_id, recipient=recipient)
        .values(
            "requester_id",
            "recipient_id",
            "requested_copy_id",
            "offered_copy_id",
            "swap_zone_id",
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
        or minat.requester_id != seed["requester_id"]
        or minat.recipient_id != seed["recipient_id"]
        or minat.requested_copy_id != seed["requested_copy_id"]
        or minat.offered_copy_id != seed["offered_copy_id"]
        or minat.swap_zone_id != seed["swap_zone_id"]
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

    automatically_rejected_ids = _automatically_reject_locked(
        (other for other in locked_minat.values() if other.pk != minat.pk),
        resolved_at=resolved_at,
    )

    transaction.on_commit(lambda: notify_accepted_minat(minat_id=minat.pk))
    _schedule_automatic_rejections(automatically_rejected_ids)
    return swap


@transaction.atomic
def update_book_copy(
    *,
    copy_id: int,
    owner: User,
    condition: str,
    condition_note: str,
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

    rejected_ids = []
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
        rejected_ids = _automatically_reject_locked(
            pending,
            resolved_at=timezone.now(),
        )

    copy.condition = condition
    copy.condition_note = condition_note
    copy.availability_status = availability_status
    copy.save(
        update_fields=[
            "condition",
            "condition_note",
            "availability_status",
            "updated_at",
        ]
    )
    _schedule_automatic_rejections(rejected_ids)
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
        pending,
        resolved_at=timezone.now(),
    )
    user.is_active = False
    user.save(update_fields=["is_active"])
    _schedule_automatic_rejections(rejected_ids)
    return user
