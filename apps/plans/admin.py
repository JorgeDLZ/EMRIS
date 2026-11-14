from django.contrib import admin

from config.admin import ReadOnlyAdmin

from .models import Action, ActionPlan, Resource, ResourceAssignment


@admin.register(ActionPlan)
class ActionPlanAdmin(ReadOnlyAdmin):
    list_display = ("emergency", "status", "proposed_by", "approved_by", "approved_at")
    list_filter = ("status",)


@admin.register(Action)
class ActionAdmin(ReadOnlyAdmin):
    list_display = ("description", "plan", "owner", "due_date", "status")
    list_filter = ("status",)


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "quantity_available")
    list_filter = ("kind",)
    search_fields = ("name",)


@admin.register(ResourceAssignment)
class ResourceAssignmentAdmin(ReadOnlyAdmin):
    list_display = ("plan", "resource", "quantity")
