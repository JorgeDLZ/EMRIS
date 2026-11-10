from django.contrib import admin

from .models import SeismicEvent


@admin.register(SeismicEvent)
class SeismicEventAdmin(admin.ModelAdmin):
    list_display = ("sgc_id", "event_time", "magnitude", "place", "municipality")
    search_fields = ("sgc_id", "place")
