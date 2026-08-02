import json
from collections.abc import Mapping
from http.client import IncompleteRead
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError

from .models import normalize_isbn, validate_isbn

SEARCH_URL = "https://openlibrary.org/search.json"
COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
USER_AGENT = "SarangBuku/1.0 (https://sarangbuku.id; noreply@sarangbuku.id)"
RESULT_LIMIT = 10
FIELDS = (
    "title",
    "author_name",
    "isbn",
    "language",
    "cover_i",
    "editions",
    "editions.title",
    "editions.author_name",
    "editions.isbn",
    "editions.language",
    "editions.cover_i",
)
ERROR_MESSAGE = (
    "Open Library sedang tidak dapat dihubungi. "
    "Coba lagi atau masukkan buku secara manual."
)
FIELD_LIMITS = {
    "title": 255,
    "authors": 500,
    "isbn": 17,
    "language": 100,
    "cover_url": 500,
}


class OpenLibraryError(Exception):
    pass


def _isbn_query(query):
    isbn = normalize_isbn(query)
    try:
        validate_isbn(isbn)
    except ValidationError:
        return None
    return isbn


def _best_edition(work):
    editions = work.get("editions")
    if isinstance(editions, Mapping) and isinstance(editions.get("docs"), list):
        return next(
            (edition for edition in editions["docs"] if isinstance(edition, Mapping)),
            work,
        )
    return work


def _valid_isbn(values):
    valid = []
    if isinstance(values, list):
        for value in values:
            if not isinstance(value, str):
                continue
            isbn = normalize_isbn(value)
            try:
                validate_isbn(isbn)
            except ValidationError:
                continue
            valid.append(isbn)
    return next((isbn for isbn in valid if len(isbn) == 13), valid[0] if valid else "")


def _strings(values):
    if not isinstance(values, list):
        return []
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def _result(work):
    if not isinstance(work, Mapping):
        return None
    source = _best_edition(work)
    title = source.get("title")
    if not isinstance(title, str) or not (title := title.strip()):
        return None

    authors = ", ".join(_strings(source.get("author_name"))) or "Penulis tidak diketahui"
    languages = _strings(source.get("language"))
    cover_id = source.get("cover_i")
    result = {
        "title": title,
        "authors": authors,
        "isbn": _valid_isbn(source.get("isbn")),
        "language": languages[0] if languages else "Bahasa tidak diketahui",
        "cover_url": (
            COVER_URL.format(cover_id=cover_id)
            if type(cover_id) is int and cover_id > 0
            else ""
        ),
    }
    return result if all(len(result[name]) <= limit for name, limit in FIELD_LIMITS.items()) else None


def search_open_library(query: str, *, timeout: float = 5.0) -> list[dict[str, str]]:
    isbn = _isbn_query(query)
    params = {"isbn": isbn} if isbn else {"q": query}
    params.update({"limit": RESULT_LIMIT, "fields": ",".join(FIELDS)})
    request = Request(
        f"{SEARCH_URL}?{urlencode(params)}",
        headers={"User-Agent": USER_AGENT},
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise OpenLibraryError(ERROR_MESSAGE)
            payload = json.load(response)
    except (OSError, IncompleteRead, json.JSONDecodeError, UnicodeError) as error:
        raise OpenLibraryError(ERROR_MESSAGE) from error

    if not isinstance(payload, Mapping) or not isinstance(payload.get("docs"), list):
        raise OpenLibraryError(ERROR_MESSAGE)
    results = [result for work in payload["docs"][:RESULT_LIMIT] if (result := _result(work))]
    if not results:
        raise OpenLibraryError(ERROR_MESSAGE)
    return results
