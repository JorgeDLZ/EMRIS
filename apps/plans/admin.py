from django.contrib import admin

from .models import Action, ActionPlan, Resource, ResourceAssignment


@admin.register(ActionPlan)
class ActionPlanAdmin(admin.ModelAdmin):
    list_display = ("emergency", "status", "proposed_by", "approved_by", "approved_at")
    list_filter = ("status",)


@admin.register(Action)
class ActionAdmin(admin.ModelAdmin):
    list_display = ("description", "plan", "owner", "due_date", "status")
    list_filter = ("status",)


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "quantity_available")
    list_filter = ("kind",)
    search_fields = ("name",)


@admin.register(ResourceAssignment)
class ResourceAssignmentAdmin(admin.ModelAdmin):
    list_display = ("plan", "resource", "quantity")
