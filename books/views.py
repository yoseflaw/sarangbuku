from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import BookCopyForm, CatalogSearchForm, DiscoveryFilterForm, ManualBookCopyForm
from .models import Book, BookCopy, WishlistItem, normalize_isbn
from .open_library import OpenLibraryError, search_open_library
from .services import discoverable_copies
from swaps.services import (
    HistoricalCopyError,
    ReservedCopyError,
    delete_book_copy,
    update_book_copy,
)


def _active_zone_redirect(request):
    if request.user.swap_zones.filter(is_active=True).exists():
        return None
    messages.error(
        request,
        "Pilih setidaknya satu Sarang aktif di Profil untuk melanjutkan.",
    )
    return redirect("accounts:profile")


def _local_catalog_results(query):
    normalized = normalize_isbn(query)
    predicate = Q(title__icontains=query) | Q(authors__icontains=query)
    if normalized:
        predicate |= Q(isbn=normalized)
    return Book.objects.filter(predicate).order_by("title", "authors", "pk")[:25]


def _post_redirect(request, fallback):
    destination = request.POST.get("next", "")
    if destination and url_has_allowed_host_and_scheme(
        destination,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(destination)
    return redirect(fallback)


@login_required
def discover(request):
    if response := _active_zone_redirect(request):
        return response

    form = DiscoveryFilterForm(request.GET or None, viewer=request.user)
    copies = BookCopy.objects.none()
    if not form.is_bound or form.is_valid():
        copies = discoverable_copies(viewer=request.user)
        if form.is_bound:
            if book := form.cleaned_data["book"]:
                copies = copies.filter(book=book)
            query = form.cleaned_data["q"]
            if query:
                normalized = normalize_isbn(query)
                predicate = Q(book__title__icontains=query) | Q(
                    book__authors__icontains=query
                )
                if normalized:
                    predicate |= Q(book__isbn=normalized)
                copies = copies.filter(predicate)
            if sarang := form.cleaned_data["sarang"]:
                copies = copies.filter(owner__swap_zones=sarang)
            if condition := form.cleaned_data["condition"]:
                conditions = [value for value, _ in BookCopy.Condition.choices]
                copies = copies.filter(
                    condition__in=conditions[: conditions.index(condition) + 1]
                )
            if form.cleaned_data["wishlist"]:
                copies = copies.filter(is_wishlisted=True)

    copies = copies.order_by("book__title", "book__authors", "pk").distinct()
    page_obj = Paginator(copies, 24).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "books/discover.html",
        {
            "form": form,
            "page_obj": page_obj,
            "filter_query": query_params.urlencode(),
        },
    )


@login_required
def discovery_detail(request, pk):
    if response := _active_zone_redirect(request):
        return response

    copy = get_object_or_404(
        discoverable_copies(viewer=request.user),
        pk=pk,
    )
    return render(request, "books/discovery_detail.html", {"copy": copy})


@login_required
def shelf(request):
    copies = BookCopy.objects.filter(owner=request.user).select_related("book")
    return render(request, "books/shelf.html", {"copies": copies})


@login_required
def copy_edit(request, pk):
    copy = get_object_or_404(BookCopy, pk=pk, owner=request.user)
    if copy.availability_status == BookCopy.Availability.RESERVED and request.method == "GET":
        messages.error(request, ReservedCopyError.message)
        return redirect("books:shelf")
    form = BookCopyForm(request.POST or None, instance=copy)
    if request.method == "POST" and form.is_valid():
        try:
            update_book_copy(
                copy_id=copy.pk,
                owner=request.user,
                condition=form.cleaned_data["condition"],
                condition_note=form.cleaned_data["condition_note"],
                availability_status=form.cleaned_data["availability_status"],
            )
        except ReservedCopyError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Bukumu sudah diperbarui.")
        return redirect("books:shelf")
    return render(request, "books/copy_form.html", {"copy": copy, "form": form})


@login_required
def copy_delete(request, pk):
    copy = get_object_or_404(BookCopy, pk=pk, owner=request.user)
    if copy.availability_status == BookCopy.Availability.RESERVED and request.method == "GET":
        messages.error(request, ReservedCopyError.message)
        return redirect("books:shelf")
    if request.method == "POST":
        try:
            delete_book_copy(copy_id=copy.pk, owner=request.user)
        except (ReservedCopyError, HistoricalCopyError) as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Buku sudah dihapus dari Lemari.")
        return redirect("books:shelf")
    return render(request, "books/copy_confirm_delete.html", {"copy": copy})


@login_required
def add(request):
    if response := _active_zone_redirect(request):
        return response

    form = CatalogSearchForm(request.GET or None)
    books = Book.objects.none()
    if form.is_valid():
        books = _local_catalog_results(form.cleaned_data["q"])

    return render(
        request,
        "books/add.html",
        {"form": form, "books": books},
    )


@login_required
def wishlist(request):
    if response := _active_zone_redirect(request):
        return response

    form = CatalogSearchForm(request.GET or None)
    books = Book.objects.none()
    if form.is_valid():
        books = _local_catalog_results(form.cleaned_data["q"]).annotate(
            is_wishlisted=Exists(
                WishlistItem.objects.filter(
                    user=request.user,
                    book_id=OuterRef("pk"),
                )
            )
        )

    items = WishlistItem.objects.filter(user=request.user).select_related("book")
    return render(
        request,
        "books/wishlist.html",
        {"form": form, "books": books, "items": items},
    )


@login_required
@require_POST
def wishlist_add(request, book_id):
    if response := _active_zone_redirect(request):
        return response

    book = get_object_or_404(Book, pk=book_id)
    _, created = WishlistItem.objects.get_or_create(user=request.user, book=book)
    if created:
        messages.success(request, "Sudah ditambahkan ke Daftar Minat.")
    else:
        messages.info(request, "Sudah ada di Daftar Minat.")
    return _post_redirect(request, "books:wishlist")


@login_required
@require_POST
def wishlist_remove(request, book_id):
    if response := _active_zone_redirect(request):
        return response

    item = get_object_or_404(
        WishlistItem,
        user=request.user,
        book_id=book_id,
    )
    item.delete()
    messages.success(request, "Sudah dihapus dari Daftar Minat.")
    return _post_redirect(request, "books:wishlist")


@login_required
def copy_create(request, book_id):
    if response := _active_zone_redirect(request):
        return response

    book = get_object_or_404(Book, pk=book_id)
    form = BookCopyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        copy = form.save(commit=False)
        copy.owner = request.user
        copy.book = book
        copy.save()
        messages.success(request, "Buku sudah ditambahkan ke Lemari.")
        return redirect("books:shelf")
    return render(
        request,
        "books/copy_form.html",
        {"book": book, "form": form},
    )


@login_required
def manual_create(request):
    if response := _active_zone_redirect(request):
        return response

    form = ManualBookCopyForm(request.POST or None, initial=request.GET or None)
    if request.method == "POST" and form.is_valid():
        form.save(owner=request.user)
        messages.success(request, "Buku sudah ditambahkan ke Lemari.")
        return redirect("books:shelf")
    return render(request, "books/manual_form.html", {"form": form})


@login_required
def open_library_search(request):
    if response := _active_zone_redirect(request):
        return response

    form = CatalogSearchForm(request.GET or None)
    external_results = []
    external_error = None

    if form.is_valid():
        try:
            external_results = search_open_library(form.cleaned_data["q"])
            for result in external_results:
                prefill = {
                    name: result.get(name, "")
                    for name in ("title", "authors", "isbn", "language", "cover_url")
                }
                result["add_url"] = (
                    f"{reverse('books:manual_create')}?{urlencode(prefill)}"
                )
        except OpenLibraryError as error:
            external_error = str(error)

    return render(
        request,
        "books/add.html",
        {
            "form": form,
            "external_results": external_results,
            "external_error": external_error,
        },
    )
