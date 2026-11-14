from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm

from apps.accounts.forms import LoginThrottlingMixin


def superuser_only(request) -> bool:
    return request.user.is_active and request.user.is_superuser


class ThrottledAdminAuthenticationForm(LoginThrottlingMixin, AdminAuthenticationForm):
    pass


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
