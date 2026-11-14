from django.contrib import admin

from config.admin import ReadOnlyAdmin

from .models import UngrdRecord


@admin.register(UngrdRecord)
class UngrdRecordAdmin(ReadOnlyAdmin):
    list_display = ("source_row", "occurred_on", "emergency_type", "department", "municipality", "is_high_impact")
    list_select_related = ("emergency_type", "department", "municipality__department")
    list_filter = ("emergency_type", "is_high_impact")
    search_fields = ("source_code",)
