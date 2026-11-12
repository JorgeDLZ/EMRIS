from django import forms

from .models import Action, Resource
from .services import assignable_owners


class ActionForm(forms.ModelForm):
    class Meta:
        model = Action
        fields = ["description", "code", "owner", "due_date"]
        labels = {"code": "Action type"}
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = assignable_owners()


class AssignmentForm(forms.Form):
    resource = forms.ModelChoiceField(queryset=Resource.objects.all())
    quantity = forms.IntegerField(min_value=1)


class ResourceForm(forms.ModelForm):
    class Meta:
        model = Resource
        fields = ["name", "kind", "quantity_available"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        duplicates = Resource.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("A resource with this name already exists.")
        return name
