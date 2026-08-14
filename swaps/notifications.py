import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import Minat

logger = logging.getLogger(__name__)


def _deliver(*, notification_type: str, record_id: int, subject: str, body: str, recipient: str) -> None:
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient])
    except Exception:
        logger.error(
            "Notification delivery failed: type=%s record_id=%s",
            notification_type,
            record_id,
        )


def _exchange_context(minat: Minat) -> dict[str, str]:
    return {
        "requested_title": minat.requested_copy.book.title,
        "requested_condition": minat.requested_copy.get_condition_display(),
        "offered_title": minat.offered_copy.book.title,
        "offered_condition": minat.offered_copy.get_condition_display(),
        "swap_zone_name": minat.swap_zone.name,
    }


def notify_new_minat(*, minat_id: int) -> None:
    minat = Minat.objects.select_related(
        "recipient", "requested_copy__book", "offered_copy__book", "swap_zone"
    ).get(pk=minat_id)
    _deliver(
        notification_type="new_minat",
        record_id=minat.pk,
        subject="Ada Minat baru di Sarang Buku",
        body=render_to_string("swaps/emails/new_minat.txt", _exchange_context(minat)),
        recipient=minat.recipient.email,
    )


def notify_rejected_minat(*, minat_id: int, automatic: bool) -> None:
    minat = Minat.objects.select_related(
        "requester", "requested_copy__book", "offered_copy__book", "swap_zone"
    ).get(pk=minat_id)
    context = {**_exchange_context(minat), "automatic": automatic}
    _deliver(
        notification_type=("automatically_rejected" if automatic else "rejected"),
        record_id=minat.pk,
        subject=("Minatmu tidak dapat dilanjutkan" if automatic else "Minatmu ditolak"),
        body=render_to_string("swaps/emails/rejected_minat.txt", context),
        recipient=minat.requester.email,
    )


def notify_accepted_minat(*, minat_id: int) -> None:
    minat = Minat.objects.select_related(
        "requester", "recipient", "requested_copy__book", "offered_copy__book", "swap_zone"
    ).get(pk=minat_id)
    exchange = _exchange_context(minat)
    for recipient, other_name in (
        (minat.requester, minat.recipient.display_name),
        (minat.recipient, minat.requester.display_name),
    ):
        _deliver(
            notification_type="accepted",
            record_id=minat.pk,
            subject="Minat diterima",
            body=render_to_string(
                "swaps/emails/accepted_minat.txt",
                {**exchange, "other_name": other_name},
            ),
            recipient=recipient.email,
        )
