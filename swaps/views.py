from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from books.services import discoverable_copies

from .forms import MinatCreateForm
from .models import Minat
from .services import (
    DuplicatePendingMinat,
    MinatEligibilityError,
    MinatTransitionError,
    accept_minat,
    create_minat,
    reject_minat,
    withdraw_minat,
)


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
def lini(request):
    received = Minat.objects.filter(
        recipient=request.user, status=Minat.Status.PENDING
    ).select_related("requested_copy__book", "offered_copy__book", "swap_zone")
    sent = Minat.objects.filter(
        requester=request.user, status=Minat.Status.PENDING
    ).select_related("requested_copy__book", "offered_copy__book", "swap_zone")
    history = (
        Minat.objects.filter(Q(requester=request.user) | Q(recipient=request.user))
        .exclude(status=Minat.Status.PENDING)
        .select_related("requested_copy__book", "offered_copy__book", "swap_zone")
        .distinct()
    )
    return render(request, "swaps/lini.html", {"received": received, "sent": sent, "history": history})


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


@login_required
def minat_withdraw(request, pk):
    get_object_or_404(Minat, pk=pk, requester=request.user)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        withdraw_minat(minat_id=pk, requester=request.user)
    except MinatTransitionError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Minat sudah dibatalkan.")
    return redirect("swaps:minat_detail", pk=pk)


@login_required
def minat_reject(request, pk):
    get_object_or_404(Minat, pk=pk, recipient=request.user)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        reject_minat(minat_id=pk, recipient=request.user)
    except MinatTransitionError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Minat sudah ditolak.")
    return redirect("swaps:minat_detail", pk=pk)


@login_required
def minat_accept(request, pk):
    get_object_or_404(Minat, pk=pk, recipient=request.user)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        accept_minat(minat_id=pk, recipient=request.user)
    except MinatTransitionError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Minat diterima. Tukar ini siap dikoordinasikan.")
    return redirect("swaps:minat_detail", pk=pk)
