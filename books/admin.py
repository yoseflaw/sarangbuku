from django.contrib import admin

from .models import Book, BookCopy


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "authors", "isbn", "language")
    search_fields = ("title", "authors", "isbn")


@admin.register(BookCopy)
class BookCopyAdmin(admin.ModelAdmin):
    list_display = ("book", "owner", "condition", "is_available")
    list_filter = ("condition", "is_available")
    search_fields = ("book__title", "book__authors", "book__isbn", "owner__email")
    list_select_related = ("book", "owner")