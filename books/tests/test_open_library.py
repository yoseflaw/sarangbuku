import json
from http.client import IncompleteRead
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import SwapZone
from books.models import Book, BookCopy
from books.open_library import OpenLibraryError, search_open_library

User = get_user_model()


class OpenLibraryClientTests(SimpleTestCase):
    def setUp(self):
        patcher = patch("books.open_library.urlopen")
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)

    def set_response(self, payload=None, *, raw=None, status=200):
        response = Mock(status=status)
        response.read.return_value = raw if raw is not None else json.dumps(payload).encode()
        self.urlopen.return_value.__enter__.return_value = response

    def test_text_search_maps_best_edition_and_builds_bounded_request(self):
        self.set_response(
            {
                "docs": [
                    {
                        "title": "Work title",
                        "editions": {
                            "docs": [
                                {
                                    "title": "Matilda",
                                    "author_name": ["Roald Dahl"],
                                    "isbn": ["0140328726", "9780140328721"],
                                    "language": ["eng"],
                                    "cover_i": 123,
                                }
                            ]
                        },
                    }
                ]
            }
        )

        results = search_open_library("Matilda")

        self.assertEqual(
            results,
            [
                {
                    "title": "Matilda",
                    "authors": "Roald Dahl",
                    "isbn": "9780140328721",
                    "language": "eng",
                    "cover_url": "https://covers.openlibrary.org/b/id/123-M.jpg",
                }
            ],
        )
        request = self.urlopen.call_args.args[0]
        parsed = urlsplit(request.full_url)
        params = parse_qs(parsed.query)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "https://openlibrary.org/search.json")
        self.assertEqual(params["q"], ["Matilda"])
        self.assertEqual(params["limit"], ["10"])
        self.assertIn("editions.isbn", params["fields"][0].split(","))
        self.assertIn("SarangBuku", request.get_header("User-agent"))
        self.assertEqual(self.urlopen.call_args.kwargs, {"timeout": 5.0})

    def test_valid_isbn_search_uses_only_exact_isbn_parameter(self):
        self.set_response({"docs": [{"title": "Matilda"}]})

        search_open_library("978-0-14-032872-1")

        params = parse_qs(urlsplit(self.urlopen.call_args.args[0].full_url).query)
        self.assertEqual(params["isbn"], ["9780140328721"])
        self.assertNotIn("q", params)

    def test_network_failures_raise_conversational_error(self):
        failures = (
            TimeoutError(),
            HTTPError("https://openlibrary.org", 500, "error", {}, None),
            URLError("connection failed"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.urlopen.reset_mock()
                self.urlopen.side_effect = failure
                with self.assertRaisesMessage(
                    OpenLibraryError,
                    "Open Library sedang tidak dapat dihubungi. Coba lagi atau masukkan buku secara manual.",
                ):
                    search_open_library("Matilda")

    def test_response_read_failures_raise_conversational_error(self):
        failures = (ConnectionResetError(), IncompleteRead(b"partial", 1))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.set_response({"docs": [{"title": "Matilda"}]})
                response = self.urlopen.return_value.__enter__.return_value
                response.read.side_effect = failure
                with self.assertRaisesMessage(
                    OpenLibraryError,
                    "Open Library sedang tidak dapat dihubungi. Coba lagi atau masukkan buku secara manual.",
                ):
                    search_open_library("Matilda")

    def test_non_200_response_raises_conversational_error(self):
        self.set_response({"docs": []}, status=503)
        with self.assertRaises(OpenLibraryError):
            search_open_library("Matilda")

    def test_malformed_response_raises_conversational_error(self):
        malformed_responses = (
            {"raw": b"not json"},
            {"payload": []},
            {"payload": {"docs": "not a list"}},
            {"payload": {"docs": [{"author_name": ["Roald Dahl"]}]}},
        )
        for response in malformed_responses:
            with self.subTest(response=response):
                self.urlopen.reset_mock()
                self.urlopen.side_effect = None
                self.set_response(**response)
                with self.assertRaisesMessage(
                    OpenLibraryError,
                    "Open Library sedang tidak dapat dihubungi. Coba lagi atau masukkan buku secara manual.",
                ):
                    search_open_library("Matilda")

    def test_results_are_limited_and_isbn_13_is_preferred(self):
        self.set_response(
            {
                "docs": [
                    {
                        "title": f"Book {index}",
                        "isbn": ["0140328726", "9780140328721"],
                    }
                    for index in range(15)
                ]
            }
        )

        results = search_open_library("Book")

        self.assertEqual(len(results), 10)
        self.assertTrue(all(result["isbn"] == "9780140328721" for result in results))

    def test_malformed_optional_values_use_safe_defaults(self):
        self.set_response(
            {
                "docs": [
                    {
                        "title": "Matilda",
                        "isbn": ["not-an-isbn", 123],
                        "author_name": None,
                        "language": None,
                        "cover_i": "123",
                    }
                ]
            }
        )

        result = search_open_library("Matilda")[0]

        self.assertEqual(result["isbn"], "")
        self.assertEqual(result["authors"], "Penulis tidak diketahui")
        self.assertEqual(result["language"], "Bahasa tidak diketahui")
        self.assertEqual(result["cover_url"], "")

    def test_first_mapping_edition_is_used(self):
        self.set_response(
            {
                "docs": [
                    {
                        "title": "Work title",
                        "editions": {
                            "docs": ["malformed", {"title": "Edition title"}]
                        },
                    }
                ]
            }
        )

        self.assertEqual(search_open_library("Matilda")[0]["title"], "Edition title")

    def test_results_exceeding_model_field_limits_are_skipped(self):
        self.set_response(
            {
                "docs": [
                    {"title": "T" * 256},
                    {"title": "Long authors", "author_name": ["A" * 501]},
                    {"title": "Long language", "language": ["L" * 101]},
                    {"title": "Usable book"},
                ]
            }
        )

        self.assertEqual(
            [result["title"] for result in search_open_library("Book")],
            ["Usable book"],
        )


class OpenLibraryViewTests(TestCase):
    result = {
        "title": "Matilda",
        "authors": "Roald Dahl",
        "isbn": "9780140328721",
        "language": "eng",
        "cover_url": "https://covers.openlibrary.org/b/id/123-M.jpg",
        "owner_email": "must-not-leak@example.com",
    }

    def setUp(self):
        self.user = User.objects.create_user(
            email="reader@example.com",
            password="testpass123",
            display_name="Pembaca",
        )
        self.zone = SwapZone.objects.create(
            name="Blok M",
            description="Bertemu di lobi.",
            is_active=True,
        )
        self.user.swap_zones.add(self.zone)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("books:open_library"))
        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={reverse("books:open_library")}',
        )

    def test_user_without_active_sarang_is_redirected_to_profile(self):
        self.user.swap_zones.clear()
        self.client.force_login(self.user)
        response = self.client.get(reverse("books:open_library"))
        self.assertRedirects(response, reverse("accounts:profile"))

    @patch("books.views.search_open_library")
    def test_search_is_called_only_after_explicit_valid_submission(self, search):
        self.client.force_login(self.user)
        for params in ({}, {"q": "   "}):
            with self.subTest(params=params):
                self.client.get(reverse("books:open_library"), params)
        search.assert_not_called()

        self.client.get(reverse("books:open_library"), {"q": "  Matilda  "})
        search.assert_called_once_with("Matilda")

    @patch("books.views.search_open_library")
    def test_local_results_offer_explicit_external_and_manual_actions(self, search):
        self.client.force_login(self.user)
        response = self.client.get(reverse("books:add"), {"q": "Matilda"})

        search.assert_not_called()
        self.assertContains(response, "Cari di Open Library")
        self.assertContains(response, f'action="{reverse("books:open_library")}"')
        self.assertContains(response, 'name="q" value="Matilda"')
        self.assertContains(response, "Masukkan manual")

    @patch("books.views.search_open_library")
    def test_results_render_metadata_and_whitelisted_manual_link(self, search):
        search.return_value = [self.result.copy()]
        self.client.force_login(self.user)

        response = self.client.get(reverse("books:open_library"), {"q": "Matilda"})

        self.assertContains(response, "Matilda")
        self.assertContains(response, "Roald Dahl")
        self.assertContains(response, "9780140328721")
        self.assertContains(response, "Tambah buku ini")
        add_url = response.context["external_results"][0]["add_url"]
        parsed = urlsplit(add_url)
        self.assertEqual(parsed.path, reverse("books:manual_create"))
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "title": ["Matilda"],
                "authors": ["Roald Dahl"],
                "isbn": ["9780140328721"],
                "language": ["eng"],
                "cover_url": ["https://covers.openlibrary.org/b/id/123-M.jpg"],
            },
        )

    @patch("books.views.search_open_library")
    def test_rendering_and_selecting_external_result_create_nothing(self, search):
        search.return_value = [self.result.copy()]
        self.client.force_login(self.user)

        response = self.client.get(reverse("books:open_library"), {"q": "Matilda"})
        selected = self.client.get(response.context["external_results"][0]["add_url"])

        self.assertEqual(selected.status_code, 200)
        self.assertContains(selected, 'value="Matilda"')
        self.assertEqual(Book.objects.count(), 0)
        self.assertEqual(BookCopy.objects.count(), 0)

    @patch("books.views.search_open_library")
    def test_service_failure_keeps_local_search_and_manual_entry_visible(self, search):
        search.side_effect = OpenLibraryError(
            "Open Library sedang tidak dapat dihubungi. Coba lagi atau masukkan buku secara manual."
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("books:open_library"), {"q": "Matilda"})

        self.assertContains(response, "Open Library sedang tidak dapat dihubungi")
        self.assertContains(response, f'action="{reverse("books:add")}"')
        self.assertContains(response, "Masukkan manual")

    def test_manual_post_revalidates_tampered_prefilled_values(self):
        self.client.force_login(self.user)
        prefilled_url = (
            f'{reverse("books:manual_create")}?'
            "title=Matilda&authors=Roald+Dahl&isbn=9780140328721&language=eng"
        )
        response = self.client.post(
            prefilled_url,
            {
                "title": "",
                "authors": "Roald Dahl",
                "isbn": "tampered",
                "language": "eng",
                "cover_url": "javascript:alert(1)",
                "condition": BookCopy.Condition.GOOD,
                "availability_status": "available",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.context["form"].errors),
            {"title", "isbn", "cover_url"},
        )
        self.assertEqual(Book.objects.count(), 0)
        self.assertEqual(BookCopy.objects.count(), 0)
