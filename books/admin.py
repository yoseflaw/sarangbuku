from django.contrib import admin

from .models import Book, BookCopy, WishlistItem


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "authors", "isbn", "language")
    search_fields = ("title", "authors", "isbn")


@admin.register(BookCopy)
class BookCopyAdmin(admin.ModelAdmin):
    list_display = ("book", "owner", "condition", "availability_status")
    list_filter = ("condition", "availability_status")
    search_fields = ("book__title", "book__authors", "book__isbn", "owner__email")
    list_select_related = ("book", "owner")
    readonly_fields = ("owner", "book", "availability_status")


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "book_authors", "created_at")
    search_fields = ("user__email", "book__title", "book__authors", "book__isbn")
    list_select_related = ("user", "book")

    @admin.display(description="Penulis", ordering="book__authors")
    def book_authors(self, obj):
        return obj.book.authors