from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import SwapZone, User
from books.models import BookCopy

from .models import Minat
from .notifications import notify_new_minat, notify_rejected_minat

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
