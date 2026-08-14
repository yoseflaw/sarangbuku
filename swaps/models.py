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
