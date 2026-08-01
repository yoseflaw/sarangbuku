from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import UserProfileForm


@login_required
def profile(request):
    form = UserProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilmu sudah diperbarui.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})
