from django.contrib import admin

from .models import EmergencyType


@admin.register(EmergencyType)
class EmergencyTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
