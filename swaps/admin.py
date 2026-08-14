from django.contrib import admin

from .models import BookSwap, Minat


@admin.register(Minat)
class MinatAdmin(admin.ModelAdmin):
    list_display = (
        "id", "requester", "recipient", "requested_copy", "offered_copy",
        "swap_zone", "status", "created_at", "resolved_at",
    )
    list_filter = ("status", "swap_zone")
    search_fields = (
        "requester__email", "recipient__email", "requested_copy__book__title",
        "offered_copy__book__title",
    )
    list_select_related = (
        "requester", "recipient", "requested_copy__book", "offered_copy__book", "swap_zone",
    )
    readonly_fields = (
        "requester", "recipient", "requested_copy", "offered_copy", "swap_zone",
        "status", "created_at", "updated_at", "resolved_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BookSwap)
class BookSwapAdmin(admin.ModelAdmin):
    list_display = ("id", "minat", "swap_zone", "status", "created_at")
    list_filter = ("status", "swap_zone")
    search_fields = (
        "minat__requester__email", "minat__recipient__email",
        "minat__requested_copy__book__title", "minat__offered_copy__book__title",
    )
    list_select_related = ("minat", "swap_zone")
    readonly_fields = ("minat", "swap_zone", "status", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
