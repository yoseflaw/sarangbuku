import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q


def normalize_isbn(value: str | None) -> str:
    return re.sub(r"[-\s]", "", value or "").upper()


def validate_isbn(value: str) -> None:
    value = normalize_isbn(value)
    valid = False

    if len(value) == 10 and value[:9].isdigit() and (
        value[9].isdigit() or value[9] == "X"
    ):
        total = sum((10 - index) * int(char) for index, char in enumerate(value[:9]))
        total += 10 if value[9] == "X" else int(value[9])
        valid = total % 11 == 0
    elif len(value) == 13 and value.isdigit():
        total = sum(
            int(char) * (1 if index % 2 == 0 else 3)
            for index, char in enumerate(value[:12])
        )
        valid = (10 - total % 10) % 10 == int(value[12])

    if not valid:
        raise ValidationError("Masukkan ISBN-10 atau ISBN-13 yang valid.")


class Book(models.Model):
    title = models.CharField(max_length=255)
    authors = models.CharField(max_length=500)
    isbn = models.CharField(max_length=17, blank=True, null=True)
    language = models.CharField(max_length=100)
    cover_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title", "authors", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("isbn",),
                condition=Q(isbn__isnull=False),
                name="books_book_isbn_unique",
            ),
            models.CheckConstraint(
                condition=Q(isbn__isnull=True) | ~Q(isbn=""),
                name="books_book_isbn_not_empty",
            ),
        ]

    def clean(self):
        super().clean()
        self.isbn = normalize_isbn(self.isbn) or None
        if self.isbn:
            validate_isbn(self.isbn)
        if self.cover_url:
            URLValidator(schemes=("http", "https"))(self.cover_url)

    def save(self, *args, **kwargs):
        self.isbn = normalize_isbn(self.isbn) or None
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} — {self.authors}"


class BookCopy(models.Model):
    class Condition(models.TextChoices):
        LIKE_NEW = "like_new", "Seperti Baru"
        VERY_GOOD = "very_good", "Sangat Bagus"
        GOOD = "good", "Masih Bagus"
        FAIR = "fair", "Cukup Bagus"
        BAD = "bad", "Sudah Buruk"

    class Availability(models.TextChoices):
        AVAILABLE = "available", "Tersedia"
        RESERVED = "reserved", "Ada Peminat"
        UNAVAILABLE = "unavailable", "Tidak tersedia"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="book_copies",
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.PROTECT,
        related_name="copies",
    )
    condition = models.CharField(max_length=20, choices=Condition.choices)
    condition_note = models.CharField(max_length=140, blank=True)
    availability_status = models.CharField(
        max_length=11,
        choices=Availability.choices,
        default=Availability.AVAILABLE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(condition__in=["like_new", "very_good", "good", "fair", "bad"]),
                name="books_bookcopy_condition_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    availability_status__in=["available", "reserved", "unavailable"]
                ),
                name="books_bookcopy_availability_valid",
            ),
        ]

    def __str__(self):
        return f"{self.book} milik {self.owner}"


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