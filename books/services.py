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