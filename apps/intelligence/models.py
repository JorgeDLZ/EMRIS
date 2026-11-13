from django.conf import settings
from django.db import models

IMPACT = "impact"
PROFILES = "profiles"
SIMILARITY = "similarity"
MUNICIPAL_RISK = "municipal_risk"
COMPONENTS = (IMPACT, PROFILES, SIMILARITY, MUNICIPAL_RISK)
COMPONENT_CHOICES = [
    (IMPACT, "Impact estimator"),
    (PROFILES, "Emergency profiles"),
    (SIMILARITY, "Similar emergencies"),
    (MUNICIPAL_RISK, "Municipal risk"),
]


class ModelVersion(models.Model):
    component = models.CharField(max_length=20, choices=COMPONENT_CHOICES)
    version = models.PositiveIntegerField()
    artifact = models.BinaryField()
    primary_metric = models.CharField(max_length=40)
    score = models.FloatField()
    metrics = models.JSONField()
    trained_on = models.JSONField()
    metadata = models.JSONField(default=dict)
    library_versions = models.JSONField()
    trained_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["component", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["component", "version"], name="unique_version_per_component"),
            models.UniqueConstraint(
                fields=["component"],
                condition=models.Q(is_active=True),
                name="one_active_version_per_component",
            ),
        ]

    def __str__(self):
        return f"{self.get_component_display()} v{self.version}"


class TrainingRun(models.Model):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STATUS_CHOICES = [(RUNNING, "Running"), (SUCCEEDED, "Succeeded"), (FAILED, "Failed")]

    component = models.CharField(max_length=20, choices=COMPONENT_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    message = models.TextField(blank=True)
    candidate_version = models.ForeignKey(
        ModelVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    activated = models.BooleanField(default=False)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-started_at", "-pk"]

    def __str__(self):
        return f"{self.get_component_display()} run ({self.status})"


class Prediction(models.Model):
    emergency = models.ForeignKey(
        "emergencies.Emergency", on_delete=models.CASCADE, related_name="predictions"
    )
    model_version = models.ForeignKey(
        ModelVersion, on_delete=models.PROTECT, related_name="predictions"
    )
    component = models.CharField(max_length=20, choices=COMPONENT_CHOICES)
    output = models.JSONField()
    score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["emergency", "component", "-created_at"])]

    def __str__(self):
        return f"{self.get_component_display()} prediction for emergency {self.emergency_id}"
