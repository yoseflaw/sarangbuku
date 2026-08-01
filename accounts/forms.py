from django import forms
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.db import transaction

from .models import Invitation, SwapZone, User
from .services import generate_invitation_code, redeem_invitation


class InvitationAdminForm(forms.ModelForm):
    recipient_email = forms.EmailField(label="Email penerima", required=False)

    class Meta:
        model = Invitation
        fields = ("recipient_email", "expires_at", "max_uses", "is_active")

    def clean_recipient_email(self):
        email = self.cleaned_data["recipient_email"]
        if self.instance._state.adding and not email:
            raise forms.ValidationError("Email penerima wajib diisi.")
        return email

    def save(self, commit=True):
        invitation = super().save(commit=False)
        if invitation._state.adding:
            code, invitation.code_digest = generate_invitation_code()
            invitation._usable_code = code
            invitation._recipient_email = self.cleaned_data["recipient_email"]
        if commit:
            invitation.save()
        return invitation


class RegistrationForm(UserCreationForm):
    invitation_code = forms.CharField(label="Kode undangan")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("invitation_code", "email", "display_name")

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email ini sudah terdaftar.")
        return email

    def save(self, commit=True):
        if not commit:
            raise ValueError("RegistrationForm must save atomically.")
        return redeem_invitation(
            code=self.cleaned_data["invitation_code"],
            email=self.cleaned_data["email"],
            display_name=self.cleaned_data["display_name"],
            password=self.cleaned_data["password1"],
        )


class UserProfileForm(forms.ModelForm):
    swap_zones = forms.ModelMultipleChoiceField(
        label="Sarang",
        queryset=SwapZone.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple,
        error_messages={
            "required": "Pilih setidaknya satu Sarang.",
            "invalid_choice": "Pilih Sarang yang masih aktif.",
        },
    )

    class Meta:
        model = User
        fields = ("display_name", "email", "swap_zones")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["swap_zones"].queryset = SwapZone.objects.filter(
            is_active=True
        ).order_by("name")

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if (
            User.objects.filter(email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("Email ini sudah digunakan.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        inactive_ids = list(
            self.instance.swap_zones.filter(is_active=False).values_list(
                "pk", flat=True
            )
        )
        user = super().save(commit=commit)
        if commit:
            active_ids = [zone.pk for zone in self.cleaned_data["swap_zones"]]
            user.swap_zones.set([*inactive_ids, *active_ids])
        return user


class AdminUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "display_name")


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
