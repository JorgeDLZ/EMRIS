from django.contrib import admin

from .models import Department, Municipality


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(Municipality)
class MunicipalityAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "code", "source", "validation")
    list_filter = ("department", "source", "validation")
    search_fields = ("name", "code")
