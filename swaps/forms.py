from django import forms

from accounts.models import SwapZone, User
from books.models import BookCopy


class MinatCreateForm(forms.Form):
    offered_copy = forms.ModelChoiceField(
        label="Buku yang kamu tawarkan",
        queryset=BookCopy.objects.none(),
        error_messages={"invalid_choice": "Pilih buku yang masih tersedia di Lemarimu."},
    )
    swap_zone = forms.ModelChoiceField(
        label="Sarang",
        queryset=SwapZone.objects.none(),
        error_messages={"invalid_choice": "Pilih Sarang aktif yang kalian gunakan bersama."},
    )

    def __init__(self, *args, requester: User, requested_copy: BookCopy, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["offered_copy"].queryset = (
            BookCopy.objects.filter(
                owner=requester,
                availability_status=BookCopy.Availability.AVAILABLE,
            )
            .select_related("book")
            .order_by("book__title", "pk")
        )
        self.fields["swap_zone"].queryset = (
            SwapZone.objects.filter(
                is_active=True,
                pk__in=requester.swap_zones.filter(is_active=True).values("pk"),
                users=requested_copy.owner_id,
            )
            .order_by("name")
            .distinct()
        )
