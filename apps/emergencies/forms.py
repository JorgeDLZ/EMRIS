from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.places.models import Municipality

from .models import EARTHQUAKE, Emergency, EmergencyType, Impact

DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


class EmergencyTypeForm(forms.ModelForm):
    class Meta:
        model = EmergencyType
        fields = ["name", "is_active"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        duplicates = EmergencyType.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("An emergency type with this name already exists.")
        return name


class EmergencyForm(forms.ModelForm):
    occurred_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_LOCAL_FORMAT),
        input_formats=[DATETIME_LOCAL_FORMAT],
    )
    reported_magnitude = forms.FloatField(
        required=False, min_value=0, max_value=10, label="Magnitude"
    )
    reported_depth_km = forms.FloatField(required=False, min_value=0, label="Depth (km)")

    class Meta:
        model = Emergency
        fields = [
            "emergency_type",
            "municipality",
            "site",
            "occurred_at",
            "description",
            "reported_magnitude",
            "reported_depth_km",
        ]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        types = Q(is_active=True)
        municipalities = Municipality.objects.visible_to(user)
        if self.instance.pk:
            types |= Q(pk=self.instance.emergency_type_id)
            municipalities = municipalities | Municipality.objects.filter(
                pk=self.instance.municipality_id
            )
        self.fields["emergency_type"].queryset = EmergencyType.objects.filter(types)
        self.fields["municipality"].queryset = municipalities.select_related("department")

    def clean_occurred_at(self):
        occurred_at = self.cleaned_data["occurred_at"]
        if occurred_at > timezone.now():
            raise forms.ValidationError("The date cannot be in the future.")
        return occurred_at

    def clean(self):
        cleaned = super().clean()
        emergency_type = cleaned.get("emergency_type")
        has_quake_fields = (
            cleaned.get("reported_magnitude") is not None
            or cleaned.get("reported_depth_km") is not None
        )
        if emergency_type is not None and has_quake_fields and emergency_type.seed_key != EARTHQUAKE:
            raise forms.ValidationError("Magnitude and depth apply only to earthquakes.")
        return cleaned


class ImpactForm(forms.ModelForm):
    hectares = forms.FloatField(min_value=0)

    class Meta:
        model = Impact
        fields = [
            "deceased",
            "injured",
            "missing",
            "people_affected",
            "families_affected",
            "homes_destroyed",
            "homes_damaged",
            "roads_damaged",
            "bridges_damaged",
            "hectares",
        ]
