from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.places.models import Department, Municipality

from .models import EARTHQUAKE, Emergency, EmergencyType, Impact

DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
WRONG_DEPARTMENT = "Choose a municipality in the selected department."
EARTHQUAKE_FIELDS = ("reported_magnitude", "reported_depth_km")


class EarthquakeAwareSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, "instance", None)
        if instance is not None and instance.seed_key == EARTHQUAKE:
            option["attrs"]["data-earthquake"] = "true"
        return option


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
    department = forms.ModelChoiceField(queryset=Department.objects.order_by("name"))

    field_order = ["emergency_type", "department", "municipality"]

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
        widgets = {
            "emergency_type": EarthquakeAwareSelect,
            "site": forms.TextInput(attrs={"class": "input-caps"}),
        }

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
        self.fields["municipality"].widget.attrs.update(
            {"data-combobox": "municipality", "data-department-field": "id_department"}
        )
        if self.instance.pk:
            self.initial.setdefault("department", self.instance.municipality.department_id)

    def general_fields(self):
        return [field for field in self.visible_fields() if field.name not in EARTHQUAKE_FIELDS]

    def earthquake_fields(self):
        return [self[name] for name in EARTHQUAKE_FIELDS]

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
        department = cleaned.get("department")
        municipality = cleaned.get("municipality")
        if department and municipality and municipality.department_id != department.pk:
            self.add_error("municipality", WRONG_DEPARTMENT)
        return cleaned


class ImpactForm(forms.ModelForm):
    hectares = forms.FloatField(
        min_value=0, initial=0, help_text="Burned, flooded or otherwise affected land; 0 if none."
    )

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
