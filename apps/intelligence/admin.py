from django.contrib import admin

from config.admin import ReadOnlyAdmin

from .models import ModelVersion, Prediction, TrainingRun


@admin.register(ModelVersion)
class ModelVersionAdmin(ReadOnlyAdmin):
    list_display = ("component", "version", "primary_metric", "score", "is_active", "trained_at")
    list_filter = ("component", "is_active")
    exclude = ("artifact",)

    def get_queryset(self, request):
        return super().get_queryset(request).defer("artifact")


@admin.register(TrainingRun)
class TrainingRunAdmin(ReadOnlyAdmin):
    list_display = ("component", "status", "started_at", "finished_at", "activated")
    list_filter = ("component", "status")


@admin.register(Prediction)
class PredictionAdmin(ReadOnlyAdmin):
    list_display = ("emergency", "component", "model_version", "score", "created_at")
    list_filter = ("component",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("emergency", "model_version")
            .defer("model_version__artifact")
        )
