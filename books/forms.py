from django import forms

from .models import BookCopy


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
            "condition_note": forms.Textarea(attrs={"rows": 3}),
        }


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