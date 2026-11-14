from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.accounts.models import User
from apps.accounts.roles import ROLE_LABELS
from apps.accounts.throttling import (
    LOCKED_MESSAGE,
    clear_failures,
    client_ip,
    release_attempt,
    reserve_attempt,
)


class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "organization")

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username


class UserRoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=[("", "No role"), *ROLE_LABELS.items()],
        required=False,
    )


class LoginThrottlingMixin:
    def clean(self):
        username = self.cleaned_data.get("username") or ""
        ip = client_ip(self.request)
        attempt = reserve_attempt(username, ip)
        if attempt is None:
            raise forms.ValidationError(LOCKED_MESSAGE, code="locked")
        try:
            cleaned_data = super().clean()
        except forms.ValidationError:
            if self.user_cache is not None:
                release_attempt(attempt)
            raise
        release_attempt(attempt)
        if self.user_cache is not None:
            clear_failures(username, ip)
        return cleaned_data


class ThrottledAuthenticationForm(LoginThrottlingMixin, AuthenticationForm):
    pass
