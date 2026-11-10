from django.db import models

from apps.places.models import Department, Municipality


class SeismicEvent(models.Model):
    sgc_id = models.CharField(max_length=50, unique=True)
    event_time = models.DateTimeField(db_index=True)
    magnitude = models.FloatField()
    depth_km = models.FloatField()
    latitude = models.FloatField()
    longitude = models.FloatField()
    place = models.CharField(max_length=200)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    municipality = models.ForeignKey(
        Municipality, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    def __str__(self):
        return f"{self.sgc_id} M{self.magnitude}"
