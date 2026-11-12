from django.conf import settings
from django.db import models

from apps.accounts.roles import OPERATOR, get_role
from ml.text import normalize_name


class Department(models.Model):
    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=100)
    name_key = models.CharField(max_length=100, editable=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name_key = normalize_name(self.name)
        super().save(*args, **kwargs)


class MunicipalityQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(validation=Municipality.APPROVED)

    def visible_to(self, user):
        if get_role(user) == OPERATOR:
            return self.filter(models.Q(validation=Municipality.APPROVED) | models.Q(created_by=user))
        return self.all()


class Municipality(models.Model):
    OFFICIAL = "official"
    USER = "user"
    SOURCE_CHOICES = [(OFFICIAL, "Official"), (USER, "User")]

    APPROVED = "approved"
    PENDING = "pending"
    VALIDATION_CHOICES = [(APPROVED, "Approved"), (PENDING, "Pending")]

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="municipalities")
    code = models.CharField(max_length=5, null=True, blank=True, unique=True)
    name = models.CharField(max_length=100)
    name_key = models.CharField(max_length=100, editable=False)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=OFFICIAL)
    validation = models.CharField(max_length=10, choices=VALIDATION_CHOICES, default=APPROVED)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects = MunicipalityQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["department", "name_key"], name="unique_municipality_name_per_department"),
        ]

    def __str__(self):
        return f"{self.name} ({self.department.name})"

    def save(self, *args, **kwargs):
        self.name_key = normalize_name(self.name)
        super().save(*args, **kwargs)
