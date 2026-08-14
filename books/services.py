from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch

from accounts.models import SwapZone

from .models import Book, BookCopy, WishlistItem, normalize_isbn


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
