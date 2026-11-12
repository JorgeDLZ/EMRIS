from django.conf import settings
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


REPORTED = "reported"
IN_RESPONSE = "in_response"
CONTROLLED = "controlled"
CLOSED = "closed"
STATUS_CHOICES = [
    (REPORTED, "Reported"),
    (IN_RESPONSE, "In response"),
    (CONTROLLED, "Controlled"),
    (CLOSED, "Closed"),
]


class Emergency(models.Model):
    emergency_type = models.ForeignKey(
        EmergencyType, on_delete=models.PROTECT, related_name="emergencies"
    )
    municipality = models.ForeignKey(
        "places.Municipality", on_delete=models.PROTECT, related_name="emergencies"
    )
    site = models.CharField(max_length=200, blank=True)
    occurred_at = models.DateTimeField()
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=REPORTED, db_index=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    seismic_event = models.ForeignKey(
        "seismic.SeismicEvent", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    seismic_link_distance_km = models.FloatField(null=True, blank=True)
    reported_magnitude = models.FloatField(null=True, blank=True)
    reported_depth_km = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]

    def __str__(self):
        return f"{self.emergency_type} in {self.municipality} on {self.occurred_at:%Y-%m-%d}"

    @property
    def is_closed(self):
        return self.status == CLOSED

    @property
    def is_earthquake(self):
        return self.emergency_type.seed_key == EARTHQUAKE

    @property
    def magnitude(self):
        if self.seismic_event is not None:
            return self.seismic_event.magnitude
        return self.reported_magnitude

    @property
    def depth_km(self):
        if self.seismic_event is not None:
            return self.seismic_event.depth_km
        return self.reported_depth_km


class Impact(models.Model):
    emergency = models.OneToOneField(Emergency, on_delete=models.CASCADE, related_name="impact")
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
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Impact of emergency {self.emergency_id}"


class StatusLog(models.Model):
    emergency = models.ForeignKey(Emergency, on_delete=models.CASCADE, related_name="status_log")
    status = models.CharField(max_length=20)
    previous_status = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.emergency_id} {self.status}"

    @property
    def is_status_change(self):
        return self.previous_status != ""
