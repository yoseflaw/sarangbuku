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