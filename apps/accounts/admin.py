from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import User


@admin.register(User)
class EmrisUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Organization", {"fields": ("organization",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Organization", {"fields": ("organization",)}),)
