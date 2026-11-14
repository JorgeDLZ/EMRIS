import re

from django import forms
from django.template.loader import render_to_string


class SampleForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, help_text="Units ready to assign.")
    name = forms.CharField()


def render_field(form, name):
    return render_to_string("_form_field.html", {"field": form[name]})


def input_tag(html, field_id):
    match = re.search(rf'<input[^>]*id="{field_id}"[^>]*>', html)
    assert match, html
    return match.group(0)


def described_by(html, field_id):
    described = re.search(r'aria-describedby="([^"]*)"', input_tag(html, field_id))
    return described.group(1).split() if described else []


def test_field_error_is_described_by_its_input():
    form = SampleForm(data={"quantity": "1", "name": ""})
    html = render_field(form, "name")
    assert 'id="id_name_error"' in html
    assert described_by(html, "id_name") == ["id_name_error"]
    assert 'aria-invalid="true"' in input_tag(html, "id_name")


def test_help_text_and_error_are_both_described_in_order():
    form = SampleForm(data={"quantity": "0", "name": "kits"})
    html = render_field(form, "quantity")
    assert described_by(html, "id_quantity") == ["id_quantity_helptext", "id_quantity_error"]


def test_valid_field_is_described_by_its_help_only():
    form = SampleForm(data={"quantity": "3", "name": "kits"})
    form.is_valid()
    html = render_field(form, "quantity")
    assert described_by(html, "id_quantity") == ["id_quantity_helptext"]
    assert "aria-invalid" not in html
