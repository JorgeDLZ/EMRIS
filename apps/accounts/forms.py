from django import forms
from django.contrib.auth.forms import UserCreationForm

from apps.accounts.models import User
from apps.accounts.roles import ROLE_LABELS


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
