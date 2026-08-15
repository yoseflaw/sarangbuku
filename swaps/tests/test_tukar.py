from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SwapZone
from books.models import Book, BookCopy
from swaps.models import BookSwap, Minat


class TukarTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user(
            email="requester@example.com",
            password="safe-test-password",
            display_name="Peminta Rahasia",
        )
        self.recipient = User.objects.create_user(
            email="recipient@example.com",
            password="safe-test-password",
            display_name="Penerima Rahasia",
        )
        self.outsider = User.objects.create_user(
            email="outsider@example.com",
            password="safe-test-password",
            display_name="Anggota Lain",
        )
        self.zone = SwapZone.objects.create(name="Blok M", description="Bertemu di lobi.")
        self.other_zone = SwapZone.objects.create(
            name="Kemang", description="Bertemu di taman."
        )
        self.requester.swap_zones.add(self.zone)
        self.recipient.swap_zones.add(self.zone)
        self.outsider.swap_zones.add(self.zone)
        self.requested = self.make_copy(
            self.recipient, "Matilda", BookCopy.Condition.GOOD, "Sampul sedikit terlipat."
        )
        self.offered = self.make_copy(
            self.requester, "Laskar Pelangi", BookCopy.Condition.VERY_GOOD, ""
        )
        self.minat = Minat.objects.create(
            requester=self.requester,
            recipient=self.recipient,
            requested_copy=self.requested,
            offered_copy=self.offered,
            swap_zone=self.zone,
            status=Minat.Status.ACCEPTED,
            resolved_at=timezone.now(),
        )
        self.swap = BookSwap.objects.create(minat=self.minat, swap_zone=self.zone)

    def make_copy(self, owner, title, condition, note=""):
        return BookCopy.objects.create(
            owner=owner,
            book=Book.objects.create(title=title, authors=f"Penulis {title}", language="Indonesia"),
            condition=condition,
            condition_note=note,
        )

    def make_resolved_minat(self, status):
        return Minat.objects.create(
            requester=self.requester,
            recipient=self.recipient,
            requested_copy=self.requested,
            offered_copy=self.offered,
            swap_zone=self.zone,
            status=status,
            resolved_at=timezone.now(),
        )

    def test_anonymous_tukar_pages_redirect_to_login(self):
        for route in (
            reverse("swaps:swap_list"),
            reverse("swaps:swap_detail", args=[self.swap.pk]),
        ):
            with self.subTest(route=route):
                self.assertRedirects(
                    self.client.get(route), f"{reverse('accounts:login')}?next={route}"
                )

    def test_only_participants_can_list_or_open_tukar(self):
        for participant in (self.requester, self.recipient):
            with self.subTest(participant=participant.pk):
                self.client.force_login(participant)
                self.assertContains(self.client.get(reverse("swaps:swap_list")), "Tukar")
                self.assertEqual(
                    self.client.get(reverse("swaps:swap_detail", args=[self.swap.pk])).status_code,
                    200,
                )

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("swaps:swap_list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("swaps:swap_detail", args=[self.swap.pk])).status_code,
            404,
        )

    def test_list_shows_only_members_accepted_tukar_newest_first(self):
        newer_minat = Minat.objects.create(
            requester=self.recipient,
            recipient=self.requester,
            requested_copy=self.offered,
            offered_copy=self.requested,
            swap_zone=self.zone,
            status=Minat.Status.ACCEPTED,
            resolved_at=timezone.now(),
        )
        newer = BookSwap.objects.create(minat=newer_minat, swap_zone=self.zone)
        other_user = get_user_model().objects.create_user(
            email="other@example.com", password="safe-test-password", display_name="Anggota Keempat"
        )
        other_user.swap_zones.add(self.zone)
        other_minat = Minat.objects.create(
            requester=self.outsider,
            recipient=other_user,
            requested_copy=self.make_copy(other_user, "Buku Orang Lain", BookCopy.Condition.GOOD),
            offered_copy=self.make_copy(self.outsider, "Buku Lain", BookCopy.Condition.GOOD),
            swap_zone=self.zone,
            status=Minat.Status.ACCEPTED,
            resolved_at=timezone.now(),
        )
        other_swap = BookSwap.objects.create(minat=other_minat, swap_zone=self.zone)
        BookSwap.objects.filter(pk=self.swap.pk).update(created_at=timezone.now() - timedelta(days=1))

        self.client.force_login(self.requester)
        response = self.client.get(reverse("swaps:swap_list"))

        self.assertEqual(list(response.context["swaps"]), [newer, self.swap])
        self.assertContains(response, reverse("swaps:swap_detail", args=[newer.pk]))
        self.assertNotContains(response, reverse("swaps:swap_detail", args=[other_swap.pk]))

    def test_participants_see_names_but_never_contact_data(self):
        for participant in (self.requester, self.recipient):
            with self.subTest(participant=participant.pk):
                self.client.force_login(participant)
                response = self.client.get(reverse("swaps:swap_detail", args=[self.swap.pk]))
                self.assertContains(response, self.requester.display_name)
                self.assertContains(response, self.recipient.display_name)
                self.assertNotContains(response, self.requester.email)
                self.assertNotContains(response, self.recipient.email)

        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(reverse("swaps:swap_detail", args=[self.swap.pk])).status_code,
            404,
        )

    def test_detail_shows_accepted_books_and_sarang_without_private_or_future_controls(self):
        self.client.force_login(self.requester)

        response = self.client.get(reverse("swaps:swap_detail", args=[self.swap.pk]))

        for value in (
            self.requested.book.title,
            self.requested.book.authors,
            self.requested.get_condition_display(),
            self.requested.condition_note,
            self.offered.book.title,
            self.offered.book.authors,
            self.offered.get_condition_display(),
            self.zone.name,
            self.zone.description,
        ):
            self.assertContains(response, value)
        for value in (
            f">{self.requester.display_name}</a>",
            f">{self.recipient.display_name}</a>",
            "@example.com",
            "telepon",
            "alamat",
            "jadwal",
            "pesan",
            "Batal",
            "Terima",
            "Tolak",
            "Konfirmasi",
            "Masalah",
        ):
            self.assertNotContains(response, value)

    def test_detail_keeps_stored_sarang_after_participant_memberships_change(self):
        self.requester.swap_zones.remove(self.zone)
        self.recipient.swap_zones.remove(self.zone)
        self.requester.swap_zones.add(self.other_zone)
        self.recipient.swap_zones.add(self.other_zone)
        self.client.force_login(self.requester)

        response = self.client.get(reverse("swaps:swap_detail", args=[self.swap.pk]))

        self.assertContains(response, self.zone.name)
        self.assertContains(response, self.zone.description)
        self.assertNotContains(response, self.other_zone.name)

    def test_accepted_history_links_to_its_tukar_but_other_resolved_minat_do_not(self):
        self.make_resolved_minat(Minat.Status.REJECTED)
        self.make_resolved_minat(Minat.Status.AUTOMATICALLY_REJECTED)
        self.client.force_login(self.requester)

        response = self.client.get(reverse("swaps:lini"))

        self.assertContains(response, reverse("swaps:swap_detail", args=[self.swap.pk]))
        self.assertEqual(response.content.decode().count("Lihat Tukar"), 1)

    def test_authenticated_navigation_has_real_phase_five_links(self):
        self.client.force_login(self.requester)

        response = self.client.get(reverse("swaps:swap_list"))

        expected_links = {
            "Temukan": reverse("books:discover"),
            "Lemari": reverse("books:shelf"),
            "Tambah": reverse("books:add"),
            "Daftar Minat": reverse("books:wishlist"),
            "Lini": reverse("swaps:lini"),
            "Tukar": reverse("swaps:swap_list"),
            "Profil": reverse("accounts:profile"),
        }
        for label, url in expected_links.items():
            with self.subTest(label=label):
                self.assertContains(response, f'href="{url}"')
                self.assertContains(response, label)

    def test_phase_five_pages_have_single_headings_and_accessible_forms_without_tables(self):
        self.client.force_login(self.requester)
        pages = [
            self.client.get(reverse("swaps:lini")),
            self.client.get(reverse("swaps:swap_list")),
            self.client.get(reverse("swaps:swap_detail", args=[self.swap.pk])),
            self.client.get(reverse("swaps:minat_create", args=[self.requested.pk])),
        ]

        for response in pages:
            with self.subTest(path=response.request["PATH_INFO"]):
                content = response.content.decode()
                self.assertEqual(content.count("<h1"), 1)
                self.assertNotIn("<table", content)
        form = pages[-1].content.decode()
        self.assertIn("<label", form)
        self.assertIn('type="hidden" name="csrfmiddlewaretoken"', form)
