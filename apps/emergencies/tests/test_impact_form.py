from apps.emergencies.forms import ImpactForm


def test_hectares_defaults_to_zero():
    field = ImpactForm()["hectares"]
    assert field.initial == 0
    assert field.help_text == "Burned, flooded or otherwise affected land; 0 if none."
