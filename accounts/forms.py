from django import forms
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import Invitation, User
from .services import generate_invitation_code


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


class AdminUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "display_name")


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
