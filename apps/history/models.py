from django.db import models

from apps.emergencies.models import EmergencyType
from apps.places.models import Department, Municipality


class UngrdRecord(models.Model):
    source_row = models.PositiveIntegerField(unique=True)
    source_code = models.CharField(max_length=50, blank=True)
    occurred_on = models.DateField()
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="+")
    municipality = models.ForeignKey(
        Municipality, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    emergency_type = models.ForeignKey(EmergencyType, on_delete=models.PROTECT, related_name="+")
    deceased = models.PositiveIntegerField(default=0)
    injured = models.PositiveIntegerField(default=0)
    missing = models.PositiveIntegerField(default=0)
    people_affected = models.PositiveIntegerField(default=0)
    families_affected = models.PositiveIntegerField(default=0)
    homes_destroyed = models.PositiveIntegerField(default=0)
    homes_damaged = models.PositiveIntegerField(default=0)
    roads_damaged = models.PositiveIntegerField(default=0)
    bridges_damaged = models.PositiveIntegerField(default=0)
    hectares = models.FloatField(default=0)
    comments = models.TextField(blank=True)
    action_codes = models.JSONField(default=list)
    is_high_impact = models.BooleanField(default=False)

    class Meta:
        ordering = ["source_row"]

    def __str__(self):
        return f"{self.source_row} {self.emergency_type} {self.occurred_on}"
