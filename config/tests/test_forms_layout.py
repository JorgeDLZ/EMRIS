import re

from django.urls import reverse

from apps.accounts.forms import RegistrationForm
from apps.accounts.roles import ADMINISTRATOR, OPERATOR
from apps.emergencies.forms import EmergencyForm, ImpactForm
from apps.emergencies.tests.test_emergency_views import make_user
from apps.plans.forms import ResourceForm

REQUIRED_NOTE = "Fields marked * are required."


def report_page(client, data=None):
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("emergencies:emergency_create")
    response = client.post(url, data) if data is not None else client.get(url)
    return response.content.decode()


def test_emergency_form_sections(client, db):
    html = report_page(client)
    legends = re.findall(r"<legend>(.*?)</legend>", html)
    assert legends == ["What happened", "Where", "When", "Earthquake details"]
    assert '<fieldset class="form-section" data-show-when="earthquake">' in html
    assert html.count('<div class="form-grid">') == 4


def test_required_mark_and_note(client, db):
    html = report_page(client)
    assert REQUIRED_NOTE in html
    assert html.index(REQUIRED_NOTE) < html.index("<fieldset")
    label = html.split('<label for="id_emergency_type">', 1)[1].split("</label>", 1)[0]
    assert '<span class="required-mark" aria-hidden="true">*</span>' in label
    optional = html.split('<label for="id_site">', 1)[1].split("</label>", 1)[0]
    assert "required-mark" not in optional


def test_error_summary_links_fields(client, db):
    html = report_page(client, {"site": ""})
    summary = html.split('<div class="error-summary" role="alert" tabindex="-1">', 1)[1].split("</div>", 1)[0]
    assert "Please correct the following:" in summary
    assert '<a href="#id_emergency_type">' in summary
    assert '<a href="#id_occurred_at">' in summary


def test_no_error_summary_without_errors(client, db):
    assert "error-summary" not in report_page(client)


def test_values_kept_after_error(client, db):
    html = report_page(client, {"description": "Bridge collapsed near the school"})
    assert "error-summary" in html
    assert ">\nBridge collapsed near the school</textarea>" in html


def test_forms_without_fieldsets_unchanged(client, db):
    client.force_login(make_user("ada", ADMINISTRATOR))
    html = client.get(reverse("emergencies:type_create")).content.decode()
    assert "<fieldset" not in html
    assert 'id="id_name"' in html


def test_help_texts(db):
    form = EmergencyForm(user=make_user("olga", OPERATOR))
    assert form["site"].help_text == "Village, neighbourhood or landmark."
    assert form["occurred_at"].help_text == "Local date and time; it cannot be in the future."
    assert form["description"].help_text == "What happened and what is needed now."
    assert RegistrationForm()["organization"].help_text == "Your agency or team, if any."
    assert ResourceForm()["quantity_available"].help_text == "Units ready to assign."


def test_impact_form_sections():
    assert ImpactForm.fieldsets == [
        ("People", ["deceased", "injured", "missing", "people_affected", "families_affected"]),
        ("Homes", ["homes_destroyed", "homes_damaged"]),
        ("Infrastructure", ["roads_damaged", "bridges_damaged"]),
        ("Land", ["hectares"]),
    ]
