from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.accounts.roles import ADMINISTRATOR, CAPABILITIES, ROLE_LABELS, get_role


class User(AbstractUser):
    organization = models.CharField(max_length=150, blank=True)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(get_role(self), "")

    @property
    def is_administrator(self) -> bool:
        return self.is_superuser or get_role(self) == ADMINISTRATOR

    def _can(self, capability: str) -> bool:
        return self.is_superuser or get_role(self) in CAPABILITIES[capability]

    @property
    def can_manage_catalogs(self) -> bool:
        return self._can("manage_catalogs")

    @property
    def can_register_municipalities(self) -> bool:
        return self._can("register_municipalities")

    @property
    def can_edit_emergencies(self) -> bool:
        return self._can("edit_emergencies")

    @property
    def can_manage_resources(self) -> bool:
        return self._can("manage_resources")

    @property
    def can_browse_history(self) -> bool:
        return self._can("browse_history")


class LoginAttempt(models.Model):
    username = models.CharField(max_length=150)
    ip_address = models.GenericIPAddressField()
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)
