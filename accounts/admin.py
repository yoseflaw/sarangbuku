from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.mail import send_mail
from django.db import transaction

from .forms import (
    AdminUserChangeForm,
    AdminUserCreationForm,
    InvitationAdminForm,
)
from .models import Invitation, SwapZone, User


@admin.register(User)
class AccountUserAdmin(UserAdmin):
    add_form = AdminUserCreationForm
    form = AdminUserChangeForm
    model = User
    ordering = ("email",)
    list_display = ("email", "display_name", "is_staff", "is_active")
    search_fields = ("email", "display_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profil", {"fields": ("display_name", "swap_zones")}),
        (
            "Izin",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Tanggal penting", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "display_name",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )
    filter_horizontal = ("groups", "user_permissions", "swap_zones")


@admin.register(SwapZone)
class SwapZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    form = InvitationAdminForm
    list_display = ("id", "use_count", "max_uses", "expires_at", "is_active")
    list_filter = ("is_active",)
    readonly_fields = (
        "code_digest",
        "use_count",
        "created_by",
        "created_at",
        "updated_at",
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            code = getattr(obj, "_usable_code", None)
            if code:
                registration_url = request.build_absolute_uri("/akun/daftar/")
                send_mail(
                    "Undangan Sarang Buku",
                    (
                        "Kamu diundang untuk bergabung di Sarang Buku.\n\n"
                        f"Kode undanganmu: {code}\n"
                        f"Daftar di: {registration_url}\n"
                    ),
                    settings.DEFAULT_FROM_EMAIL,
                    [obj._recipient_email],
                )
                self.message_user(
                    request,
                    f"Undangan dibuat. Kode ini hanya ditampilkan sekali: {code}",
                    messages.SUCCESS,
                )
