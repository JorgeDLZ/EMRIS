from django import forms

from .models import EmergencyType


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
