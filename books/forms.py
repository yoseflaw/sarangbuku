from django import forms
from django.core.validators import URLValidator

from accounts.models import SwapZone

from .models import Book, BookCopy, normalize_isbn, validate_isbn


class BookCopyForm(forms.ModelForm):
    class Meta:
        model = BookCopy
        fields = ("condition", "condition_note", "is_available")
        labels = {
            "condition": "Kondisi",
            "condition_note": "Catatan kondisi",
            "is_available": "Tersedia untuk ditukar",
        }
        help_texts = {
            "condition_note": "Opsional, maksimal 140 karakter.",
        }
        widgets = {
            "condition_note": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }


class DiscoveryFilterForm(forms.Form):
    q = forms.CharField(
        label="Cari",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    book = forms.ModelChoiceField(
        label="Buku",
        queryset=Book.objects.all(),
        required=False,
        error_messages={"invalid_choice": "Pilih pilihan yang valid."},
        widget=forms.HiddenInput(),
    )
    sarang = forms.ModelChoiceField(
        label="Sarang",
        queryset=SwapZone.objects.none(),
        required=False,
        empty_label="Semua Sarang",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    condition = forms.ChoiceField(
        label="Kondisi minimum",
        choices=(),
        required=False,
        error_messages={"invalid_choice": "Pilih pilihan yang valid."},
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    wishlist = forms.BooleanField(
        label="Daftar Minat saja",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, viewer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sarang"].queryset = viewer.swap_zones.filter(is_active=True)
        self.fields["condition"].choices = [
            ("", "Semua kondisi"),
            *BookCopy.Condition.choices,
        ]

    def clean_q(self):
        return self.cleaned_data["q"].strip()


class CatalogSearchForm(forms.Form):
    q = forms.CharField(
        label="ISBN, judul, atau penulis",
        max_length=255,
        error_messages={"required": "Masukkan ISBN, judul, atau penulis."},
    )

    def clean_q(self):
        value = self.cleaned_data["q"].strip()
        if not value:
            raise forms.ValidationError("Masukkan ISBN, judul, atau penulis.")
        return value


class ManualBookCopyForm(forms.Form):
    title = forms.CharField(label="Judul", max_length=255)
    authors = forms.CharField(label="Penulis", max_length=500)
    isbn = forms.CharField(label="ISBN", max_length=17, required=False)
    language = forms.CharField(label="Bahasa", max_length=100)
    cover_url = forms.URLField(
        label="URL sampul",
        max_length=500,
        required=False,
        validators=(URLValidator(schemes=("http", "https")),),
    )
    condition = forms.ChoiceField(
        label="Kondisi", choices=BookCopy.Condition.choices
    )
    condition_note = forms.CharField(
        label="Catatan kondisi",
        max_length=140,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        help_text="Opsional, maksimal 140 karakter.",
    )
    is_available = forms.BooleanField(
        label="Tersedia untuk ditukar", required=False, initial=True
    )

    def clean_isbn(self):
        isbn = normalize_isbn(self.cleaned_data["isbn"])
        if isbn:
            validate_isbn(isbn)
        return isbn or None

    def save(self, *, owner):
        from .services import create_book_copy

        book_fields = ("title", "authors", "isbn", "language", "cover_url")
        copy_fields = ("condition", "condition_note", "is_available")
        return create_book_copy(
            owner=owner,
            book_data={name: self.cleaned_data[name] for name in book_fields},
            copy_data={name: self.cleaned_data[name] for name in copy_fields},
        )