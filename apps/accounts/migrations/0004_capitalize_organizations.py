from django.db import migrations


def capitalize(value):
    return " ".join(value.split()).upper()


def capitalize_organizations(apps, schema_editor):
    for row in apps.get_model("accounts", "User").objects.exclude(organization=""):
        value = capitalize(row.organization)
        if value != row.organization:
            row.organization = value
            row.save(update_fields=["organization"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_loginattempt")]

    operations = [migrations.RunPython(capitalize_organizations, migrations.RunPython.noop)]
