from django.contrib import admin

from config.admin import ReadOnlyAdmin

from .models import SeismicEvent


@admin.register(SeismicEvent)
class SeismicEventAdmin(ReadOnlyAdmin):
    list_display = ("sgc_id", "event_time", "magnitude", "place", "municipality")
    list_select_related = ("municipality__department",)
    search_fields = ("sgc_id", "place")
