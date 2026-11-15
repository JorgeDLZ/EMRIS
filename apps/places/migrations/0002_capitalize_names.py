from django.db import migrations


def capitalize(value):
    return " ".join(value.split()).upper()


def capitalize_names(apps, schema_editor):
    for row in apps.get_model("places", "Department").objects.exclude(name=""):
        value = capitalize(row.name)
        if value != row.name:
            row.name = value
            row.save(update_fields=["name"])
    for row in apps.get_model("places", "Municipality").objects.exclude(name=""):
        value = capitalize(row.name)
        if value != row.name:
            row.name = value
            row.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [("places", "0001_initial")]

    operations = [migrations.RunPython(capitalize_names, migrations.RunPython.noop)]
