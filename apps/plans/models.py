from django.conf import settings
from django.db import models

from ml.actions import ACTION_VOCABULARY

DRAFT = "draft"
APPROVED = "approved"
PLAN_STATUS_CHOICES = [
    (DRAFT, "Draft"),
    (APPROVED, "Approved"),
]

PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
ACTION_STATUS_CHOICES = [
    (PENDING, "Pending"),
    (IN_PROGRESS, "In progress"),
    (DONE, "Done"),
]

KIT = "kit"
PERSONNEL = "personnel"
EQUIPMENT = "equipment"
RESOURCE_KIND_CHOICES = [
    (KIT, "Kit"),
    (PERSONNEL, "Personnel"),
    (EQUIPMENT, "Equipment"),
]

ACTION_CODE_CHOICES = [(code, rule.label) for code, rule in ACTION_VOCABULARY.items()]


class ActionPlan(models.Model):
    emergency = models.OneToOneField(
        "emergencies.Emergency", on_delete=models.CASCADE, related_name="action_plan"
    )
    status = models.CharField(max_length=20, choices=PLAN_STATUS_CHOICES, default=DRAFT)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Plan for emergency {self.emergency_id}"

    @property
    def is_approved(self):
        return self.status == APPROVED


class Action(models.Model):
    plan = models.ForeignKey(ActionPlan, on_delete=models.CASCADE, related_name="actions")
    description = models.CharField(max_length=300)
    code = models.CharField(max_length=50, blank=True, choices=ACTION_CODE_CHOICES)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_actions",
    )
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ACTION_STATUS_CHOICES, default=PENDING)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.description


class Resource(models.Model):
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=20, choices=RESOURCE_KIND_CHOICES)
    quantity_available = models.PositiveIntegerField()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ResourceAssignment(models.Model):
    plan = models.ForeignKey(ActionPlan, on_delete=models.CASCADE, related_name="assignments")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="assignments")
    quantity = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "resource"], name="unique_resource_per_plan"),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="assignment_quantity_positive"
            ),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.resource}"
