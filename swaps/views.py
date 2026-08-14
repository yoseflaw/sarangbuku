from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from books.services import discoverable_copies

from .forms import MinatCreateForm
from .models import Minat
from .services import DuplicatePendingMinat, MinatEligibilityError, create_minat


@login_required
def minat_create(request, requested_copy_id):
    requested_copy = get_object_or_404(
        discoverable_copies(viewer=request.user), pk=requested_copy_id
    )
    form = MinatCreateForm(
        request.POST or None,
        requester=request.user,
        requested_copy=requested_copy,
    )
    if request.method == "POST" and form.is_valid():
        try:
            minat = create_minat(
                requester=request.user,
                requested_copy_id=requested_copy.pk,
                offered_copy_id=form.cleaned_data["offered_copy"].pk,
                swap_zone_id=form.cleaned_data["swap_zone"].pk,
            )
        except (DuplicatePendingMinat, MinatEligibilityError) as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Minatmu sudah dikirim.")
            return redirect("swaps:minat_detail", pk=minat.pk)
    return render(
        request,
        "swaps/minat_form.html",
        {"form": form, "requested_copy": requested_copy},
    )


@login_required
def minat_detail(request, pk):
    minat = get_object_or_404(
        Minat.objects.filter(Q(requester=request.user) | Q(recipient=request.user)).select_related(
            "requested_copy__book", "offered_copy__book", "swap_zone"
        ),
        pk=pk,
    )
    return render(
        request,
        "swaps/minat_detail.html",
        {"minat": minat, "is_requester": minat.requester_id == request.user.pk},
    )
