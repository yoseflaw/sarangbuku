# Phase 2 Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add invitation-only registration, authentication, password recovery, and profile onboarding with one or more administrator-managed Sarang.

**Design:** `references/specs/2026-08-01-phase-2-accounts-design.md`

**Architecture:** Keep Phase 2 inside the existing `accounts` app. Models store invitations and Sarang, a small service atomically redeems invitation codes under a PostgreSQL row lock, and ordinary Django forms/views/templates handle registration and profile editing. Django's built-in authentication and password-reset views provide the security-sensitive session and token behavior.

**Tech Stack:** Django 5.2.16, PostgreSQL 18, Django Templates, Bootstrap 5.3.8, Django Admin, and the Python standard library. Add no dependencies and no HTMX where a normal POST/redirect/get flow works.

## Global Constraints

- Work directly on `main`; do not create a worktree.
- Preserve the user's uncommitted `.gitignore` change. Never stage it with Phase 2 work.
- Stage explicit paths instead of `git add .`.
- Use PostgreSQL for development and tests; do not add a SQLite fallback.
- Use English internal identifiers and the public Indonesian terms defined in `references/mvp/MVP_SPEC.md`.
- User-facing UI and email copy must use natural conversational Indonesian following EYD, without em dashes.
- Registration and Sarang selection are separate steps.
- Successful registration signs in the new user and redirects immediately to Profil.
- Profil requires one or more active Sarang and shows an unavailable `Tambahkan Buku` card.
- Book records and physical copies remain Phase 3 work.
- Use Django's built-in login, logout, and password-reset machinery.
- Logout accepts POST only.
- All invitation failure states share one generic user-facing message.
- Invitation redemption must lock the invitation with `select_for_update()` inside `transaction.atomic()`.
- Do not collect phone numbers, coordinates, or home addresses.

## Preflight

- [ ] Run the current checks before changing implementation files.

```bash
cd /Users/yosef/Projects/sarangbuku
git branch --show-current
git status --short
git diff -- .gitignore
/Library/PostgreSQL/18/bin/pg_isready
.venv/bin/python manage.py test --verbosity 2
```

Expected: branch `main`, PostgreSQL accepts connections, the existing nine tests pass, and the user's `.gitignore` edit remains visible and unstaged.

## File Map

### Create

- `accounts/forms.py`: invitation admin form, registration form, custom user admin forms, and profile form.
- `accounts/services.py`: invitation code generation/digest and atomic redemption.
- `accounts/urls.py`: registration, profile, login/logout, and password-reset routes.
- `accounts/migrations/0002_phase_2_accounts.py`: Invitation, SwapZone, constraints, and User relation.
- `accounts/tests/test_invitations.py`: models, code generation, admin delivery, and rollback.
- `accounts/tests/test_registration.py`: redemption service, concurrency, form, and request flow.
- `accounts/tests/test_authentication.py`: login/logout, navigation, and password reset.
- `accounts/tests/test_profile.py`: profile editing and Sarang rules.
- `templates/accounts/register.html`: invitation registration.
- `templates/accounts/login.html`: email login.
- `templates/accounts/profile.html`: account editing, Sarang choices, and book placeholder.
- `templates/accounts/password_reset_form.html`
- `templates/accounts/password_reset_done.html`
- `templates/accounts/password_reset_confirm.html`
- `templates/accounts/password_reset_complete.html`
- `templates/accounts/password_reset_email.txt`
- `templates/accounts/password_reset_subject.txt`

### Modify

- `accounts/models.py`: add Invitation, SwapZone, and `User.swap_zones`.
- `accounts/admin.py`: register the three account models and generate/email invitations.
- `accounts/views.py`: registration and profile views.
- `config/settings.py`: authentication redirects and development email defaults.
- `config/urls.py`: mount `accounts.urls`.
- `templates/base.html`: session-aware account navigation and POST logout.
- `static/css/sarangbuku.css`: only the minimal shared form/navigation styles needed by the new templates.

## Shared Interfaces

```python
# accounts/services.py
class InvalidInvitation(ValueError):
    pass


class DuplicateEmail(ValueError):
    pass


def digest_invitation_code(code: str) -> str:
    """Return a SHA-256 hexadecimal digest for a stripped invitation code."""


def generate_invitation_code() -> tuple[str, str]:
    """Return (usable_code, digest); only the digest may be persisted."""


def redeem_invitation(
    *, code: str, email: str, display_name: str, password: str
) -> User:
    """Atomically consume one use and return the newly created user."""
```

Form contracts:

- `InvitationAdminForm(forms.ModelForm)` adds transient `recipient_email` and generates a code only for new invitations.
- `AdminUserCreationForm(UserCreationForm)` and `AdminUserChangeForm(UserChangeForm)` support the email-based custom user in Django Admin.
- `RegistrationForm(UserCreationForm).save(commit: bool = True) -> User` delegates account creation to `redeem_invitation()`.
- `UserProfileForm(forms.ModelForm).save(commit: bool = True) -> User` saves profile fields and active Sarang while retaining prior inactive memberships.

View contracts:

- `register(request: HttpRequest) -> HttpResponse` creates and signs in invited users.
- `profile(request: HttpRequest) -> HttpResponse` requires authentication and edits only the current user.

Named routes:

```text
accounts:register
accounts:login
accounts:logout
accounts:profile
accounts:password_reset
accounts:password_reset_done
accounts:password_reset_confirm
accounts:password_reset_complete
```

---

### Task 1: Invitation and Sarang Data with Admin Delivery

**Files:**
- Modify: `accounts/models.py`
- Create: `accounts/forms.py`
- Create: `accounts/services.py`
- Modify: `accounts/admin.py`
- Create: `accounts/migrations/0002_phase_2_accounts.py`
- Create: `accounts/tests/test_invitations.py`

**Interfaces:**
- Consumes: existing `accounts.User` and `UserManager`.
- Produces: `Invitation`, `SwapZone`, `User.swap_zones`, `digest_invitation_code()`, and `generate_invitation_code()`.

- [ ] **Step 1: Write failing model and code-generation tests**

```python
# accounts/tests/test_invitations.py
import hashlib
from smtplib import SMTPException
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import Invitation, SwapZone
from accounts.services import generate_invitation_code


class InvitationCodeTests(SimpleTestCase):
    def test_generated_code_has_256_bits_and_matching_digest(self):
        code, digest = generate_invitation_code()

        self.assertGreaterEqual(len(code), 43)
        self.assertEqual(digest, hashlib.sha256(code.encode()).hexdigest())
        self.assertNotEqual(code, digest)


class InvitationModelTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="test-password",
            display_name="Admin",
        )

    def test_max_uses_must_be_positive(self):
        invitation = Invitation(
            code_digest="a" * 64,
            max_uses=0,
            created_by=self.staff,
        )

        with self.assertRaises(ValidationError):
            invitation.full_clean()

    def test_use_count_cannot_exceed_max_uses(self):
        invitation = Invitation.objects.create(
            code_digest="b" * 64,
            max_uses=1,
            created_by=self.staff,
        )
        invitation.use_count = 2

        with self.assertRaises(ValidationError):
            invitation.full_clean()

    def test_user_can_select_multiple_swap_zones(self):
        user = get_user_model().objects.create_user(
            email="member@example.com",
            password="test-password",
            display_name="Anggota",
        )
        zones = [
            SwapZone.objects.create(name="Blok M", description="Lobi"),
            SwapZone.objects.create(name="Gambir", description="Pintu utama"),
        ]

        user.swap_zones.set(zones)

        self.assertCountEqual(user.swap_zones.all(), zones)
```

Also assert duplicate `code_digest` values fail and `str(Invitation)` never contains a usable code.

- [ ] **Step 2: Run the tests and confirm the expected import/model failures**

```bash
.venv/bin/python manage.py test accounts.tests.test_invitations --verbosity 2
```

Expected: FAIL because Invitation, SwapZone, and the service do not exist.

- [ ] **Step 3: Add the minimal models and generation helpers**

```python
# accounts/models.py
from django.conf import settings
from django.db import models
from django.db.models import F, Q


class SwapZone(models.Model):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Invitation(models.Model):
    code_digest = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField(blank=True, null=True)
    max_uses = models.PositiveIntegerField(default=1)
    use_count = models.PositiveIntegerField(default=0, editable=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invitations",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(max_uses__gt=0),
                name="accounts_invitation_max_uses_positive",
            ),
            models.CheckConstraint(
                condition=Q(use_count__gte=0),
                name="accounts_invitation_use_count_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(use_count__lte=F("max_uses")),
                name="accounts_invitation_use_count_within_limit",
            ),
        ]

    def __str__(self):
        return f"Undangan {self.pk or 'baru'}"
```

Define `SwapZone` before `User`, then add this field to `User`:

```python
swap_zones = models.ManyToManyField(
    SwapZone,
    blank=True,
    related_name="users",
)
```

```python
# accounts/services.py
import hashlib
import secrets


def digest_invitation_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def generate_invitation_code() -> tuple[str, str]:
    code = secrets.token_urlsafe(32)
    return code, digest_invitation_code(code)
```

- [ ] **Step 4: Generate, inspect, and apply the migration**

```bash
.venv/bin/python manage.py makemigrations accounts --name phase_2_accounts
.venv/bin/python manage.py sqlmigrate accounts 0002
.venv/bin/python manage.py migrate
```

Expected SQL: Invitation and SwapZone tables, three Invitation checks, and the User/SwapZone join table.

- [ ] **Step 5: Run model tests until they pass**

```bash
.venv/bin/python manage.py test accounts.tests.test_invitations --verbosity 2
.venv/bin/python manage.py makemigrations --check
```

Expected: PASS and no migration drift.

- [ ] **Step 6: Add failing Django Admin invitation tests**

```python
class InvitationAdminTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="test-password",
            display_name="Admin",
        )
        self.client.force_login(self.staff)

    def test_admin_emails_code_but_persists_only_digest(self):
        response = self.client.post(
            reverse("admin:accounts_invitation_add"),
            {
                "recipient_email": "reader@example.com",
                "max_uses": 1,
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        invitation = Invitation.objects.get()
        self.assertEqual(invitation.created_by, self.staff)
        self.assertEqual(len(mail.outbox), 1)
        code = mail.outbox[0].body.split("Kode undanganmu: ", 1)[1].splitlines()[0]
        self.assertEqual(hashlib.sha256(code.encode()).hexdigest(), invitation.code_digest)
        self.assertNotIn(code, str(invitation.__dict__))

    @patch("accounts.admin.send_mail", side_effect=SMTPException("offline"))
    def test_email_failure_rolls_back_invitation(self, _send_mail):
        with self.assertRaises(SMTPException):
            self.client.post(
                reverse("admin:accounts_invitation_add"),
                {
                    "recipient_email": "reader@example.com",
                    "max_uses": 1,
                    "is_active": "on",
                },
            )

        self.assertFalse(Invitation.objects.exists())
```

- [ ] **Step 7: Implement the admin forms and registrations**

```python
# accounts/forms.py
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
```

Use a `UserAdmin` subclass with `email` in place of `username`, `display_name`, `is_active`, staff permissions, and `swap_zones`. Register `SwapZone` with name search and active filtering.

For Invitation, set `form = InvitationAdminForm`, make digest/creator/count/timestamps readonly, and send synchronously from `save_model`:

```python
# accounts/admin.py
@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    form = InvitationAdminForm
    list_display = ("id", "use_count", "max_uses", "expires_at", "is_active")
    readonly_fields = ("code_digest", "use_count", "created_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            code = getattr(obj, "_usable_code", None)
            if code:
                registration_url = request.build_absolute_uri("/akun/daftar/")
                send_mail(
                    "Undangan Sarang Buku",
                    (
                        "Kamu diundang untuk bergabung di Sarang Buku.\n\n"
                        f"Kode undanganmu: {code}\n"
                        f"Daftar di: {registration_url}\n"
                    ),
                    settings.DEFAULT_FROM_EMAIL,
                    [obj._recipient_email],
                )
                self.message_user(
                    request,
                    f"Undangan dibuat. Kode ini hanya ditampilkan sekali: {code}",
                    messages.SUCCESS,
                )
```

Do not expose `code_digest` as an editable admin field. Keep `recipient_email` transient.

- [ ] **Step 8: Run Task 1 checks and commit explicit files**

```bash
.venv/bin/python manage.py test accounts.tests.test_user accounts.tests.test_invitations --verbosity 2
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check
git add accounts/models.py accounts/forms.py accounts/services.py accounts/admin.py \
  accounts/migrations/0002_phase_2_accounts.py accounts/tests/test_invitations.py
git commit -m "Implement invitation and Sarang administration"
git status --short
```

Expected: tests pass and `.gitignore` remains unstaged.

---

### Task 2: Profil and Sarang Onboarding

**Files:**
- Modify: `accounts/forms.py`
- Modify: `accounts/views.py`
- Create: `accounts/urls.py`
- Modify: `config/urls.py`
- Create: `templates/accounts/profile.html`
- Modify: `static/css/sarangbuku.css`
- Create: `accounts/tests/test_profile.py`

**Interfaces:**
- Consumes: `User.swap_zones`, active `SwapZone` records, and Django messages.
- Produces: `UserProfileForm`, `profile()`, and `accounts:profile`.

- [ ] **Step 1: Write failing profile tests**

```python
class ProfileTests(TestCase):
    def test_multiple_active_zones_can_be_selected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "display_name": "Nadia",
                "email": "member@example.com",
                "swap_zones": [self.zone_one.pk, self.zone_two.pk],
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertCountEqual(
            self.user.swap_zones.values_list("pk", flat=True),
            [self.zone_one.pk, self.zone_two.pk],
        )

    def test_zero_zones_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {"display_name": "Nadia", "email": "member@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pilih setidaknya satu Sarang.")
```

Also prove anonymous redirect, active-only choices, rejection of posted inactive IDs, retention of existing inactive memberships, normalized email updates, duplicate-email field errors, absence of another user's email, and a disabled `Tambahkan Buku` control with no book URL.

- [ ] **Step 2: Implement `UserProfileForm`**

```python
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
            self.instance.swap_zones.filter(is_active=False)
            .values_list("pk", flat=True)
        )
        user = super().save(commit=commit)
        if commit:
            active_ids = [zone.pk for zone in self.cleaned_data["swap_zones"]]
            user.swap_zones.set([*inactive_ids, *active_ids])
        return user
```

Retaining inactive IDs preserves historical selection while preventing the user from newly choosing an inactive Sarang.

- [ ] **Step 3: Implement profile view and route**

```python
@login_required
def profile(request):
    form = UserProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilmu sudah diperbarui.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})
```

```python
# accounts/urls.py
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("profil/", views.profile, name="profile"),
]
```

Mount the account routes once:

```python
# config/urls.py
path("akun/", include("accounts.urls")),
```

- [ ] **Step 4: Add the accessible profile template**

Render visible labels and errors for display name, email, and active Sarang checkboxes. Show each Sarang's public meeting guidance. Use CSRF and POST/redirect/get.

Add a noninteractive book card only:

```django
<section class="card" aria-labelledby="tambahkan-buku">
  <div class="card-body">
    <h2 id="tambahkan-buku" class="h5">Tambahkan Buku</h2>
    <p>
      Setelah memilih Sarang, nanti kamu bisa menambahkan buku yang sudah selesai kamu baca.
      Fitur ini belum tersedia.
    </p>
    <button type="button" class="btn btn-secondary" disabled>Belum tersedia</button>
  </div>
</section>
```

Do not add a book model, route, form, or inactive anchor. Add only enough CSS for header form alignment, error spacing, and mobile-safe checkbox/card layout.

- [ ] **Step 5: Run and commit Task 2**

```bash
.venv/bin/python manage.py test accounts.tests.test_profile --verbosity 2
.venv/bin/python manage.py check
git add accounts/forms.py accounts/views.py accounts/urls.py config/urls.py \
  templates/accounts/profile.html static/css/sarangbuku.css accounts/tests/test_profile.py
git commit -m "Add profile and Sarang onboarding"
git status --short
```

---

### Task 3: Login, POST Logout, and Password Reset

**Files:**
- Modify: `accounts/urls.py`
- Modify: `config/settings.py`
- Modify: `templates/base.html`
- Create: `templates/accounts/login.html`
- Create: `templates/accounts/password_reset_form.html`
- Create: `templates/accounts/password_reset_done.html`
- Create: `templates/accounts/password_reset_confirm.html`
- Create: `templates/accounts/password_reset_complete.html`
- Create: `templates/accounts/password_reset_email.txt`
- Create: `templates/accounts/password_reset_subject.txt`
- Create: `accounts/tests/test_authentication.py`

**Interfaces:**
- Consumes: existing case-insensitive `UserManager.get_by_natural_key()` and `accounts:profile`.
- Produces: built-in authentication routes and session-aware navigation.

- [ ] **Step 1: Write failing login/logout tests**

```python
class LoginLogoutTests(TestCase):
    def test_email_login_ignores_case_and_redirects_to_profile(self):
        user = get_user_model().objects.create_user(
            email="member@example.com",
            password="safe-test-password",
            display_name="Nadia",
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "MEMBER@EXAMPLE.COM", "password": "safe-test-password"},
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)

    def test_post_logout_clears_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("landing"))
        self.assertNotIn("_auth_user_id", self.client.session)
```

Also test wrong credentials, inactive users, signed-out navigation, and signed-in Profil/POST logout navigation.

- [ ] **Step 2: Write failing password-reset tests**

For an active user, POST their email, assert the generic done redirect and one email, extract the reset URL, follow Django's token-cleaning redirect, submit two matching new passwords, and assert the old password fails while the new one works.

```python
def test_reset_response_does_not_reveal_account_existence(self):
    known = self.client.post(
        reverse("accounts:password_reset"),
        {"email": "member@example.com"},
    )
    unknown = self.client.post(
        reverse("accounts:password_reset"),
        {"email": "unknown@example.com"},
    )

    self.assertEqual(known.status_code, unknown.status_code)
    self.assertEqual(known.url, unknown.url)
```

Also assert unknown and inactive accounts receive no email and a used token cannot reset a password again.

- [ ] **Step 3: Configure standard authentication settings and routes**

```python
# config/settings.py
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:profile"
LOGOUT_REDIRECT_URL = "landing"
DEFAULT_FROM_EMAIL = "Sarang Buku <noreply@sarangbuku.id>"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

The console backend is the development default; production deployment must supply a real backend through deployment configuration before inviting pilot users.

```python
# accounts/urls.py
path(
    "masuk/",
    LoginView.as_view(template_name="accounts/login.html"),
    name="login",
),
path("keluar/", LogoutView.as_view(), name="logout"),
path(
    "lupa-kata-sandi/",
    PasswordResetView.as_view(
        template_name="accounts/password_reset_form.html",
        email_template_name="accounts/password_reset_email.txt",
        subject_template_name="accounts/password_reset_subject.txt",
        success_url=reverse_lazy("accounts:password_reset_done"),
    ),
    name="password_reset",
),
path(
    "lupa-kata-sandi/terkirim/",
    PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html"
    ),
    name="password_reset_done",
),
path(
    "atur-ulang/<uidb64>/<token>/",
    PasswordResetConfirmView.as_view(
        template_name="accounts/password_reset_confirm.html",
        success_url=reverse_lazy("accounts:password_reset_complete"),
    ),
    name="password_reset_confirm",
),
path(
    "atur-ulang/selesai/",
    PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html"
    ),
    name="password_reset_complete",
),
```

Do not create custom reset tokens or require Django Sites.

- [ ] **Step 4: Add authentication templates and navigation**

The login form posts Django's `username` field but labels it `Email`, includes `autocomplete="email"` and `autocomplete="current-password"`, and links to registration and password reset.

Use this non-enumerating reset message:

```text
Jika ada akun aktif dengan email tersebut, kami akan mengirim tautan untuk mengatur ulang kata sandimu.
```

Use Django's supplied `protocol`, `domain`, `uid`, and `token` in `password_reset_email.txt`:

```django
Kamu menerima email ini karena ada permintaan untuk mengatur ulang kata sandi Sarang Buku.

Buka tautan berikut untuk membuat kata sandi baru:
{{ protocol }}://{{ domain }}{% url 'accounts:password_reset_confirm' uidb64=uid token=token %}

Jika kamu tidak meminta perubahan ini, abaikan email ini.
```

Update the header without JavaScript:

```django
{% if user.is_authenticated %}
  <a href="{% url 'accounts:profile' %}">Profil</a>
  <form method="post" action="{% url 'accounts:logout' %}">
    {% csrf_token %}
    <button type="submit" class="btn btn-link">Keluar</button>
  </form>
{% else %}
  <a href="{% url 'accounts:login' %}">Masuk</a>
  <a href="{% url 'accounts:register' %}">Daftar dengan undangan</a>
{% endif %}
```

- [ ] **Step 5: Run and commit Task 3**

```bash
.venv/bin/python manage.py test accounts.tests.test_authentication --verbosity 2
.venv/bin/python manage.py check
git add accounts/urls.py config/settings.py templates/base.html \
  templates/accounts/login.html templates/accounts/password_reset_form.html \
  templates/accounts/password_reset_done.html templates/accounts/password_reset_confirm.html \
  templates/accounts/password_reset_complete.html templates/accounts/password_reset_email.txt \
  templates/accounts/password_reset_subject.txt accounts/tests/test_authentication.py
git commit -m "Add account authentication and recovery"
git status --short
```

---

### Task 4: Atomic Invitation Registration

**Files:**
- Modify: `accounts/services.py`
- Modify: `accounts/forms.py`
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Create: `templates/accounts/register.html`
- Create: `accounts/tests/test_registration.py`

**Interfaces:**
- Consumes: `Invitation`, `UserManager.create_user()`, invitation digest helpers, `accounts:profile`, and `accounts:login`.
- Produces: `redeem_invitation()`, `RegistrationForm`, `register()`, and `accounts:register`.

- [ ] **Step 1: Write failing service-state tests**

```python
# accounts/tests/test_registration.py
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import Invitation
from accounts.services import InvalidInvitation, redeem_invitation


class InvitationRedemptionTests(TestCase):
    def test_valid_code_creates_user_and_consumes_once(self):
        user = redeem_invitation(
            code=self.code,
            email="MEMBER@EXAMPLE.COM",
            display_name="Nadia",
            password="safe-test-password",
        )

        self.invitation.refresh_from_db()
        self.assertEqual(user.email, "member@example.com")
        self.assertTrue(user.check_password("safe-test-password"))
        self.assertEqual(self.invitation.use_count, 1)
```

Create subtests for unknown, disabled, expired, and exhausted invitations. Every state must raise `InvalidInvitation` without creating a user or incrementing `use_count`.

Add a rollback test by patching `Invitation.save` to raise after user creation, then assert the user and increment are both absent.

- [ ] **Step 2: Write the PostgreSQL concurrency test**

```python
class ConcurrentRedemptionTests(TransactionTestCase):
    def redeem(self, barrier, email):
        close_old_connections()
        barrier.wait()
        try:
            redeem_invitation(
                code=self.code,
                email=email,
                display_name=email,
                password="safe-test-password",
            )
            return "created"
        except InvalidInvitation:
            return "rejected"
        finally:
            close_old_connections()

    def test_max_uses_cannot_be_exceeded(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda email: self.redeem(barrier, email),
                    ["one@example.com", "two@example.com"],
                )
            )

        self.assertCountEqual(results, ["created", "rejected"])
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.use_count, 1)
        self.assertEqual(get_user_model().objects.count(), 1)
```

Use `TransactionTestCase`, not `TestCase`, so worker connections can observe real PostgreSQL commits and row locks.

- [ ] **Step 3: Run service tests and confirm failure**

```bash
.venv/bin/python manage.py test accounts.tests.test_registration --verbosity 2
```

Expected: FAIL because the exceptions and redemption function are missing.

- [ ] **Step 4: Implement atomic redemption**

```python
# accounts/services.py
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Invitation

GENERIC_INVITATION_ERROR = (
    "Kode undangan ini tidak dapat digunakan. "
    "Periksa kembali kodenya atau hubungi pengelola Sarang Buku."
)


class InvalidInvitation(ValueError):
    pass


class DuplicateEmail(ValueError):
    pass


def redeem_invitation(*, code, email, display_name, password):
    try:
        with transaction.atomic():
            try:
                invitation = Invitation.objects.select_for_update().get(
                    code_digest=digest_invitation_code(code)
                )
            except Invitation.DoesNotExist as error:
                raise InvalidInvitation from error

            now = timezone.now()
            if (
                not invitation.is_active
                or invitation.use_count >= invitation.max_uses
                or invitation.expires_at is not None
                and invitation.expires_at <= now
            ):
                raise InvalidInvitation

            user = get_user_model().objects.create_user(
                email=email,
                display_name=display_name,
                password=password,
            )
            invitation.use_count += 1
            invitation.save(update_fields=["use_count", "updated_at"])
            return user
    except IntegrityError as error:
        raise DuplicateEmail from error
```

Acquire the lock before checking invitation state. Let any non-uniqueness failure escape rather than continuing inside a broken transaction.

- [ ] **Step 5: Add failing form and request tests**

Prove that:

```python
def test_valid_registration_signs_in_and_redirects_to_profile(self):
    response = self.client.post(
        reverse("accounts:register"),
        {
            "invitation_code": self.code,
            "email": "member@example.com",
            "display_name": "Nadia",
            "password1": "safe-test-password",
            "password2": "safe-test-password",
        },
    )

    self.assertRedirects(response, reverse("accounts:profile"))
    user = get_user_model().objects.get(email="member@example.com")
    self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
    self.assertFalse(user.swap_zones.exists())
```

Also test generic invitation errors, duplicate-email form errors, password validation, preserved safe values, and authenticated-user redirect.

- [ ] **Step 6: Implement `RegistrationForm`**

```python
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
```

Map `InvalidInvitation` to `invitation_code` and `DuplicateEmail` to `email` in the view; never expose the invitation's actual state.

- [ ] **Step 7: Implement registration view and routes**

```python
# accounts/views.py
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
```

Add this route to the existing `accounts.urls.urlpatterns` list without replacing the profile or authentication routes:

```python
path("daftar/", views.register, name="register"),
```

- [ ] **Step 8: Add the accessible registration template**

Use a single server-rendered `<form method="post" novalidate>`, `{% csrf_token %}`, visible labels, and field errors. Set `autocomplete` to `email`, `name`, and `new-password`; never repopulate passwords. Include this summary before the fields:

```django
{% if form.errors %}
  <div class="alert alert-danger" role="alert" tabindex="-1">
    Periksa kembali data pendaftaranmu.
  </div>
{% endif %}
```

Link to `{% url 'accounts:login' %}` but do not combine login and registration into one POST form.

- [ ] **Step 9: Run and commit Task 4**

```bash
.venv/bin/python manage.py test accounts.tests.test_registration --verbosity 2
.venv/bin/python manage.py check
git add accounts/services.py accounts/forms.py accounts/views.py accounts/urls.py \
  templates/accounts/register.html accounts/tests/test_registration.py
git commit -m "Implement invitation-only registration"
git status --short
```

---

### Task 5: Full Verification and Browser QA

**Files:** No implementation files should change unless verification reveals a defect.

**Interfaces:**
- Consumes: all Phase 2 behavior.
- Produces: evidence that Phase 2 satisfies its design and does not disturb Phase 1.

- [ ] **Step 1: Run all automated checks**

```bash
cd /Users/yosef/Projects/sarangbuku
.venv/bin/python manage.py test --verbosity 2
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python -m pip check
git diff --check
```

Expected: all tests and checks pass without new migrations or dependency errors.

- [ ] **Step 2: Run the PostgreSQL locking test independently**

```bash
.venv/bin/python manage.py test \
  accounts.tests.test_registration.ConcurrentRedemptionTests \
  --verbosity 2
```

Expected: one account created, one redemption rejected, and `use_count == 1`.

- [ ] **Step 3: Run browser QA at mobile and desktop widths**

Start the server:

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

At 390 px and 1280 px verify:

1. Signed-out navigation shows Masuk and registration.
2. A staff-created invitation email contains a usable code and the database does not.
3. Registration signs in and redirects immediately to `/akun/profil/`.
4. Profil rejects zero Sarang and accepts multiple active Sarang.
5. `Tambahkan Buku` is visibly unavailable and has no active link.
6. Logout works by POST and GET logout returns 405.
7. Login accepts email case-insensitively.
8. Password reset gives the same acknowledgement for known and unknown email addresses.
9. A reset email link changes the password once and cannot be reused.
10. Labels, keyboard operation, focus visibility, validation summaries, contrast, and mobile layout remain usable.

- [ ] **Step 4: Verify repository safety and final diff**

```bash
git status --short
git diff -- .gitignore
git diff --check
git log --oneline --decorate -6
```

Expected: the user's `.gitignore` change remains unstaged, generated files are absent, and Phase 2 is represented by focused commits.

## Plan Self-Review Checklist

- Invitation generation, digest-only storage, email delivery, failure rollback, and administration: Task 1.
- Unknown, disabled, expired, exhausted, rolled-back, and concurrent redemption: Task 4.
- Separate registration and Sarang onboarding with immediate Profil redirect: Tasks 2 and 4.
- Login, POST logout, inactive-user handling, and non-enumerating password reset: Task 3.
- Multiple active Sarang, inactive retention, email privacy, and unavailable book entry: Task 2.
- Mobile, accessibility, migration, dependency, and full regression checks: Task 5.
