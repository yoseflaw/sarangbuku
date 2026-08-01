from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import RegistrationForm, UserProfileForm
from .services import (
    DuplicateEmail,
    GENERIC_INVITATION_ERROR,
    InvalidInvitation,
)


def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = form.save()
        except InvalidInvitation:
            form.add_error("invitation_code", GENERIC_INVITATION_ERROR)
        except DuplicateEmail:
            form.add_error("email", "Email ini sudah terdaftar.")
        else:
            login(request, user)
            return redirect("accounts:profile")

    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile(request):
    form = UserProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilmu sudah diperbarui.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})
