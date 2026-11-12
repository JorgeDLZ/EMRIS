from django.db import models

EARTHQUAKE = "Earthquake"


class EmergencyType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    seed_key = models.CharField(max_length=100, unique=True, null=True, blank=True, editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
