import hashlib
import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Invitation

GENERIC_INVITATION_ERROR = (
    "Kode undangan ini tidak dapat digunakan. "
    "Periksa kembali kodenya atau hubungi pengelola Sarang Buku."
)


class InvalidInvitation(ValueError):
    pass


class DuplicateEmail(ValueError):
    pass


def digest_invitation_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def generate_invitation_code() -> tuple[str, str]:
    code = secrets.token_urlsafe(32)
    return code, digest_invitation_code(code)


def redeem_invitation(*, code, email, display_name, password):
    with transaction.atomic():
        try:
            invitation = Invitation.objects.select_for_update().get(
                code_digest=digest_invitation_code(code)
            )
        except Invitation.DoesNotExist as error:
            raise InvalidInvitation from error

        now = timezone.now()
        if (
            not invitation.is_active
            or invitation.use_count >= invitation.max_uses
            or invitation.expires_at is not None
            and invitation.expires_at <= now
        ):
            raise InvalidInvitation

        try:
            with transaction.atomic():
                user = get_user_model().objects.create_user(
                    email=email,
                    display_name=display_name,
                    password=password,
                )
        except IntegrityError as error:
            raise DuplicateEmail from error

        invitation.use_count += 1
        invitation.save(update_fields=["use_count", "updated_at"])
        return user
