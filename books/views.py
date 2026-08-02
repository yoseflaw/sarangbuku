from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import BookCopyForm, CatalogSearchForm, ManualBookCopyForm
from .models import Book, BookCopy, normalize_isbn
from .open_library import OpenLibraryError, search_open_library


def _active_zone_redirect(request):
    if request.user.swap_zones.filter(is_active=True).exists():
        return None
    messages.error(
        request,
        "Pilih setidaknya satu Sarang aktif di Profil sebelum menambahkan buku.",
    )
    return redirect("accounts:profile")


@login_required
def shelf(request):
    copies = BookCopy.objects.filter(owner=request.user).select_related("book")
    return render(request, "books/shelf.html", {"copies": copies})


@login_required
def copy_edit(request, pk):
    copy = get_object_or_404(BookCopy, pk=pk, owner=request.user)
    form = BookCopyForm(request.POST or None, instance=copy)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Bukumu sudah diperbarui.")
        return redirect("books:shelf")
    return render(request, "books/copy_form.html", {"copy": copy, "form": form})


@login_required
def copy_delete(request, pk):
    copy = get_object_or_404(BookCopy, pk=pk, owner=request.user)
    if request.method == "POST":
        copy.delete()
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
        query = form.cleaned_data["q"]
        normalized = normalize_isbn(query)
        predicate = Q(title__icontains=query) | Q(authors__icontains=query)
        if normalized:
            predicate |= Q(isbn=normalized)
        books = Book.objects.filter(predicate).order_by("title", "authors", "pk")[:25]

    return render(
        request,
        "books/add.html",
        {"form": form, "books": books},
    )


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
