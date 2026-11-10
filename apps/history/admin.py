from django.contrib import admin

from .models import UngrdRecord


@admin.register(UngrdRecord)
class UngrdRecordAdmin(admin.ModelAdmin):
    list_display = ("source_row", "occurred_on", "emergency_type", "department", "municipality", "is_high_impact")
    list_filter = ("emergency_type", "is_high_impact")
    search_fields = ("source_code",)
