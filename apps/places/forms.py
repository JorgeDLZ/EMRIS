from django import forms

from .models import Department


class MunicipalityForm(forms.Form):
    department = forms.ModelChoiceField(queryset=Department.objects.order_by("name"))
    name = forms.CharField(max_length=100)
    confirm_new = forms.BooleanField(required=False, label="This is a new municipality, register it anyway")
