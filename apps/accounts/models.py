from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.accounts.roles import ROLE_LABELS, get_role


class User(AbstractUser):
    organization = models.CharField(max_length=150, blank=True)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(get_role(self), "")
