from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import BookCopyForm
from .models import BookCopy


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
