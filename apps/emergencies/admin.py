from django.contrib import admin

from config.admin import ReadOnlyAdmin

from .models import Emergency, EmergencyType, Impact, StatusLog


@admin.register(EmergencyType)
class EmergencyTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Emergency)
class EmergencyAdmin(ReadOnlyAdmin):
    list_display = ("emergency_type", "municipality", "status", "occurred_at")
    list_filter = ("status",)


@admin.register(Impact)
class ImpactAdmin(ReadOnlyAdmin):
    list_display = ("emergency", "deceased", "people_affected", "updated_at")


@admin.register(StatusLog)
class StatusLogAdmin(ReadOnlyAdmin):
    list_display = ("emergency", "status", "previous_status", "author", "created_at")
