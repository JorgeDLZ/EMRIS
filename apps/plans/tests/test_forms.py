from apps.plans.forms import ActionForm
from apps.plans.models import ACTION_CODE_CHOICES


def action_data(**extra):
    return {"description": "", "code": "", "owner": "", "due_date": "", **extra}


def test_action_description_defaults_to_type(db):
    code, label = ACTION_CODE_CHOICES[0]
    form = ActionForm(data=action_data(code=code))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["description"] == label


def test_action_needs_description_or_type(db):
    form = ActionForm(data=action_data())
    assert not form.is_valid()
    assert form.errors["description"] == ["Describe the action or choose an action type."]


def test_action_keeps_written_description(db):
    code, _ = ACTION_CODE_CHOICES[0]
    form = ActionForm(data=action_data(code=code, description="Send water trucks"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["description"] == "Send water trucks"
