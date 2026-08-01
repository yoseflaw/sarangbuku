from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from .managers import UserManager


class SwapZone(models.Model):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=150)
    swap_zones = models.ManyToManyField(
        SwapZone,
        blank=True,
        related_name="users",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_email_ci_unique",
            )
        ]

    def __str__(self):
        return self.display_name


class Invitation(models.Model):
    code_digest = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField(blank=True, null=True)
    max_uses = models.PositiveIntegerField(default=1)
    use_count = models.PositiveIntegerField(default=0, editable=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invitations",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(max_uses__gt=0),
                name="accounts_invitation_max_uses_positive",
            ),
            models.CheckConstraint(
                condition=Q(use_count__gte=0),
                name="accounts_invitation_use_count_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(use_count__lte=F("max_uses")),
                name="accounts_invitation_use_count_within_limit",
            ),
        ]

    def __str__(self):
        return f"Undangan {self.pk or 'baru'}"
