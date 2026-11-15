from django.db import migrations


def capitalize(value):
    return " ".join(value.split()).upper()


def capitalize_sites(apps, schema_editor):
    for row in apps.get_model("emergencies", "Emergency").objects.exclude(site=""):
        value = capitalize(row.site)
        if value != row.site:
            row.site = value
            row.save(update_fields=["site"])


class Migration(migrations.Migration):
    dependencies = [("emergencies", "0004_emergency_impact_statuslog")]

    operations = [migrations.RunPython(capitalize_sites, migrations.RunPython.noop)]
